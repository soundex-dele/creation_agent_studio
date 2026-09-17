import asyncio
import json
from unittest.mock import patch
from types import SimpleNamespace
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit
import uuid

import pytest
from channels.layers import InMemoryChannelLayer
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from modules.catalog.models import (
    ApplicationDeployment,
    ApplicationRevision,
    SkillDeployment,
    SkillRevision,
)
from apps.applications.models import Application, Skill
from apps.conversations.models import Conversation, Message
from modules.catalog.services import canonical_content_hash
from django.utils import timezone

from modules.execution.application.runs import (
    LeaseFence,
    create_run,
    record_artifact,
    suspend_attempt_for_input,
)
from modules.execution.api.streaming import (
    _cross_process_channel_layer,
    stream_run_events,
)
from modules.execution.infrastructure.claim import claim_next_run
from modules.execution.application.event_retention import (
    apply_projection_event,
    compact_run_events,
    empty_projection,
)
from modules.execution.application.runs import append_event_and_transition
from modules.execution.models import IdempotencyRecord, Run, RunArtifact, RunAttempt
from apps.enterprise.models import Membership, Organization
from apps.applications.models import ApplicationCategory


def test_run_event_contract_fixture_matches_backend_projection():
    contract_path = Path(__file__).resolve().parents[4] / "contracts" / "run-events-v1.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    projection = empty_projection(contract["run_id"])
    for item in contract["events"]:
        projection = apply_projection_event(projection, SimpleNamespace(
            run_id=contract["run_id"],
            sequence=item["sequence"],
            type=item["type"],
            payload=item["payload"],
        ))
    assert projection == contract["projection"]


def test_in_memory_channel_layer_uses_database_polling_fallback():
    layer = InMemoryChannelLayer()

    assert _cross_process_channel_layer(layer) is None


def test_shared_channel_layer_keeps_notification_transport():
    layer = object()

    assert _cross_process_channel_layer(layer) is layer


@pytest.fixture
def api_actor(db):
    return get_user_model().objects.create_user(
        username="execution-api-owner",
        email="execution-api-owner@example.com",
        password="test-password",
    )


@pytest.fixture
def api_organization(api_actor):
    organization = Organization.objects.create(
        name="Execution API Organization",
        slug="execution-api-organization",
        owner=api_actor,
    )
    Membership.objects.create(
        organization=organization,
        user=api_actor,
        role=Membership.Role.OWNER,
    )
    return organization


@pytest.fixture
def api_run(api_actor, api_organization):
    return create_run(
        organization=api_organization,
        owner=api_actor,
        executor_kind=Run.ExecutorKind.MEDIA,
        source_type="application",
        source_id="batch-transcribe",
        definition_snapshot={"application_revision": "revision-1"},
        input_data={"files": ["one.mp4"]},
    )


@pytest.fixture
def authenticated_client(api_actor):
    client = APIClient()
    client.force_authenticate(api_actor)
    return client


@pytest.fixture
def deployed_application(api_actor, api_organization):
    category, _ = ApplicationCategory.objects.get_or_create(
        slug="execution-tests", defaults={"name": "Execution Tests"}
    )
    application = Application.objects.create(
        organization=api_organization,
        created_by=api_actor,
        category=category,
        name="Batch Transcribe",
        slug="batch-transcribe-runtime",
        description="Batch transcription application",
    )
    content = {
        "executor_kind": "media",
        "executor_key": "batch-transcribe",
        "retry_policy": {"max_attempts": 2, "retry_safe": True},
    }
    revision = ApplicationRevision.objects.create(
        organization=api_organization,
        application=application,
        revision_no=1,
        content=content,
        content_hash=canonical_content_hash(content),
        created_by=api_actor,
    )
    ApplicationDeployment.objects.create(
        organization=api_organization,
        application=application,
        revision=revision,
        updated_by=api_actor,
    )
    return application


def _run_url(organization, run, suffix=""):
    return f"/api/v1/organizations/{organization.id}/runs/{run.id}{suffix}"


@pytest.mark.django_db
@patch("modules.execution.api.views.open_workspace_directory")
def test_workflow_run_opens_its_shared_workspace(
    open_directory,
    authenticated_client,
    api_actor,
    api_organization,
    settings,
    tmp_path,
):
    settings.LOCAL_FILE_MANAGER_ENABLED = True
    settings.AGENT_WORKSPACE_ROOT = tmp_path
    run = create_run(
        organization=api_organization,
        owner=api_actor,
        executor_kind=Run.ExecutorKind.WORKFLOW,
        executor_key="workflow-dag",
        source_type="workflow",
        source_id="workflow-1",
        definition_snapshot={"durable_children": True},
        input_data={},
    )

    response = authenticated_client.post(
        _run_url(api_organization, run, "/open-workspace"),
        {},
        format="json",
    )

    expected = (
        tmp_path / "organizations" / str(api_organization.id)
        / "workflows" / str(run.id)
    ).resolve()
    assert response.status_code == 200
    assert Path(response.data["working_directory"]) == expected
    open_directory.assert_called_once_with(str(expected))


def test_run_list_uses_canonical_history_and_source_filter(
    authenticated_client, api_organization, api_run,
):
    response = authenticated_client.get(
        f"/api/v1/organizations/{api_organization.id}/runs",
        {"source_type": "application"},
    )
    assert response.status_code == 200
    assert [item["id"] for item in response.data] == [str(api_run.id)]

    invalid = authenticated_client.get(
        f"/api/v1/organizations/{api_organization.id}/runs",
        {"source_type": "legacy-job"},
    )
    assert invalid.status_code == 400


@pytest.mark.django_db
def test_workflow_run_detail_exposes_child_conversations(
    authenticated_client, api_actor, api_organization,
):
    root = create_run(
        organization=api_organization,
        owner=api_actor,
        executor_kind=Run.ExecutorKind.WORKFLOW,
        executor_key="workflow-dag",
        source_type="workflow",
        source_id="workflow-1",
        definition_snapshot={"durable_children": True},
        input_data={},
    )
    child = create_run(
        organization=api_organization,
        owner=api_actor,
        parent=root,
        node_key="write",
        executor_kind=Run.ExecutorKind.AGENT,
        executor_key="agent-completion",
        source_type="workflow_step",
        source_id="step-1",
        definition_snapshot={"conversation_id": "42"},
        input_data={},
    )

    response = authenticated_client.get(_run_url(api_organization, root))

    assert response.status_code == 200
    assert response.data["workflow_conversations"] == {"write": "42"}
    assert child.parent_id == root.id


@pytest.mark.django_db
def test_finished_run_owner_can_delete_history(
    authenticated_client, api_organization, api_run, api_artifact, settings, tmp_path,
):
    settings.ARTIFACT_ROOT = tmp_path
    artifact_path = Path(tmp_path, api_artifact.object_key)
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_bytes(b"history artifact\n")
    Run.objects.filter(pk=api_run.pk).update(
        status=Run.Status.SUCCEEDED,
        finished_at=timezone.now(),
    )
    api_run.refresh_from_db()

    listed = authenticated_client.get(
        f"/api/v1/organizations/{api_organization.id}/runs",
        {"source_type": "application"},
    )
    assert listed.status_code == 200
    assert listed.data[0]["can_delete"] is True

    deleted = authenticated_client.delete(_run_url(api_organization, api_run))
    assert deleted.status_code == 204
    assert not Run.objects.filter(pk=api_run.pk).exists()
    assert not artifact_path.exists()


@pytest.mark.django_db
def test_queued_run_is_cancelled_and_deleted_in_one_request(
    authenticated_client, api_organization, api_run,
):
    listed = authenticated_client.get(
        f"/api/v1/organizations/{api_organization.id}/runs",
        {"source_type": "application"},
    )
    assert listed.data[0]["can_delete"] is True

    deleted = authenticated_client.delete(_run_url(api_organization, api_run))

    assert deleted.status_code == 204
    assert not Run.objects.filter(pk=api_run.pk).exists()


@pytest.mark.django_db
def test_running_run_starts_cancellation_before_deletion(
    authenticated_client, api_organization, api_run,
):
    Run.objects.filter(pk=api_run.pk).update(status=Run.Status.RUNNING)

    pending = authenticated_client.delete(_run_url(api_organization, api_run))

    assert pending.status_code == 202
    assert pending.data["deletion_pending"] is True
    api_run.refresh_from_db()
    assert api_run.status == Run.Status.CANCELLING

    Run.objects.filter(pk=api_run.pk).update(
        status=Run.Status.CANCELLED,
        finished_at=timezone.now(),
    )
    deleted = authenticated_client.delete(_run_url(api_organization, api_run))
    assert deleted.status_code == 204
    assert not Run.objects.filter(pk=api_run.pk).exists()


@pytest.mark.django_db
def test_deleting_workflow_history_deletes_its_conversations_and_messages(
    authenticated_client, api_actor, api_organization, api_run,
):
    projected_conversation = Conversation.objects.create(
        user=api_actor,
        organization=api_organization,
        title="Workflow writer",
        process_id="workflow:writer",
    )
    empty_conversation = Conversation.objects.create(
        user=api_actor,
        organization=api_organization,
        title="Workflow reviewer",
        process_id="workflow:reviewer",
    )
    Run.objects.filter(pk=api_run.pk).update(
        status=Run.Status.SUCCEEDED,
        finished_at=timezone.now(),
        executor_kind=Run.ExecutorKind.WORKFLOW,
        executor_key="workflow-dag",
        source_type="workflow",
        definition_snapshot={
            "workflow_steps": [
                {"key": "writer", "conversation_id": str(projected_conversation.id)},
                {"key": "reviewer", "conversation_id": str(empty_conversation.id)},
            ],
        },
    )
    child = create_run(
        organization=api_organization,
        owner=api_actor,
        parent=api_run,
        node_key="writer",
        executor_kind=Run.ExecutorKind.AGENT,
        executor_key="agent-completion",
        source_type="workflow_step",
        source_id="writer",
        definition_snapshot={
            "conversation_id": str(projected_conversation.id),
        },
        input_data={"message": "Write the article"},
    )
    Run.objects.filter(pk=child.pk).update(
        status=Run.Status.SUCCEEDED,
        finished_at=timezone.now(),
    )
    message = Message.objects.create(
        conversation=projected_conversation,
        run=child,
        run_event_sequence=1,
        role="assistant",
        content="Finished article",
    )
    attempt = RunAttempt.objects.create(
        run=api_run,
        attempt_no=1,
        status=RunAttempt.Status.SUSPENDED,
        worker_pool=Run.ExecutorKind.WORKFLOW,
        finished_at=timezone.now(),
    )
    checkpoint = RunArtifact.objects.create(
        organization=api_organization,
        run=api_run,
        attempt=attempt,
        kind="checkpoint",
        object_key=f"runs/{api_run.id}/attempts/{attempt.id}/checkpoint.json",
        content_hash="f" * 64,
        mime_type="application/json",
        size=2,
    )
    attempt.checkpoint_artifact = checkpoint
    attempt.save(update_fields=("checkpoint_artifact",))

    deleted = authenticated_client.delete(_run_url(api_organization, api_run))

    assert deleted.status_code == 204
    assert not Run.objects.filter(pk__in=(api_run.pk, child.pk)).exists()
    assert not Conversation.objects.filter(
        pk__in=(projected_conversation.pk, empty_conversation.pk)
    ).exists()
    assert not Message.objects.filter(pk=message.pk).exists()
    assert not RunAttempt.objects.filter(pk=attempt.pk).exists()
    assert not RunArtifact.objects.filter(pk=checkpoint.pk).exists()


@pytest.mark.django_db
def test_active_manual_run_is_ended_and_deleted_in_one_request(
    authenticated_client, api_organization, api_run,
):
    Run.objects.filter(pk=api_run.pk).update(
        status=Run.Status.RUNNING,
        executor_kind=Run.ExecutorKind.WORKFLOW,
        executor_key="workflow-manual",
        source_type="workflow",
    )

    deleted = authenticated_client.delete(_run_url(api_organization, api_run))

    assert deleted.status_code == 204
    assert not Run.objects.filter(pk=api_run.pk).exists()


@pytest.mark.django_db
def test_other_developer_cannot_delete_run(
    authenticated_client, api_organization, api_run,
):

    Run.objects.filter(pk=api_run.pk).update(
        status=Run.Status.FAILED,
        finished_at=timezone.now(),
    )
    developer = get_user_model().objects.create_user(username="run-history-developer")
    Membership.objects.update_or_create(
        organization=api_organization,
        user=developer,
        defaults={"role": Membership.Role.DEVELOPER, "is_active": True},
    )
    authenticated_client.force_authenticate(developer)

    listed = authenticated_client.get(
        f"/api/v1/organizations/{api_organization.id}/runs",
        {"source_type": "application"},
    )
    assert listed.status_code == 200
    assert listed.data[0]["can_delete"] is False

    denied = authenticated_client.delete(_run_url(api_organization, api_run))
    assert denied.status_code == 403
    assert Run.objects.filter(pk=api_run.pk).exists()


@pytest.fixture
def api_artifact(api_run, api_organization):
    return RunArtifact.objects.create(
        organization=api_organization,
        run=api_run,
        kind="result",
        object_key=f"runs/{api_run.id}/result.txt",
        content_hash="d" * 64,
        mime_type="text/plain",
        size=14,
        metadata={"filename": "result.txt"},
    )


@pytest.mark.django_db
def test_run_detail_is_scoped_to_path_organization(
    authenticated_client, api_organization, api_run
):
    response = authenticated_client.get(_run_url(api_organization, api_run))

    assert response.status_code == 200
    assert response.data["id"] == str(api_run.id)
    assert response.data["organization_id"] == str(api_organization.id)
    assert response.data["next_event_sequence"] == 1


@pytest.mark.django_db
def test_artifact_access_uses_short_lived_signed_url_without_exposing_object_key(
    authenticated_client,
    api_organization,
    api_run,
    api_artifact,
    settings,
    tmp_path,
):
    settings.ARTIFACT_ROOT = tmp_path
    artifact_path = Path(tmp_path, api_artifact.object_key)
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_bytes(b"artifact-data\n")

    listed = authenticated_client.get(_run_url(api_organization, api_run, "/artifacts"))
    access = authenticated_client.get(
        _run_url(
            api_organization,
            api_run,
            f"/artifacts/{api_artifact.id}/access",
        )
    )
    content_path = urlsplit(access.data["url"]).path + "?" + urlsplit(
        access.data["url"]
    ).query
    anonymous = APIClient()
    downloaded = anonymous.get(content_path)

    assert listed.status_code == 200
    assert "object_key" not in listed.data["results"][0]
    assert access.status_code == 200
    assert downloaded.status_code == 200
    assert b"".join(downloaded.streaming_content) == b"artifact-data\n"
    assert downloaded["Content-Disposition"].endswith('filename="result.txt"')


@pytest.mark.django_db
def test_artifact_download_rejects_tampered_token_and_unsafe_key(
    authenticated_client,
    api_organization,
    api_run,
    api_artifact,
    settings,
    tmp_path,
):
    settings.ARTIFACT_ROOT = tmp_path
    access = authenticated_client.get(
        _run_url(
            api_organization,
            api_run,
            f"/artifacts/{api_artifact.id}/access",
        )
    )
    parsed = urlsplit(access.data["url"])
    tampered = APIClient().get(f"{parsed.path}?{parsed.query}x")
    assert tampered.status_code == 403
    assert tampered.data["code"] == "invalid_artifact_access_token"

    RunArtifact.objects.filter(pk=api_artifact.id).update(object_key="../secret.txt")
    refreshed_access = authenticated_client.get(
        _run_url(
            api_organization,
            api_run,
            f"/artifacts/{api_artifact.id}/access",
        )
    )
    refreshed = urlsplit(refreshed_access.data["url"])
    unsafe = APIClient().get(f"{refreshed.path}?{refreshed.query}")
    assert unsafe.status_code == 403
    assert unsafe.data["code"] == "unsafe_artifact_object_key"


@pytest.mark.django_db
def test_compacted_event_cursor_returns_snapshot_recovery_contract(
    authenticated_client, api_organization, api_run
):
    append_event_and_transition(
        run_id=api_run.id,
        organization_id=api_organization.id,
        event_type="output.delta",
        payload={"text": "hello"},
    )
    append_event_and_transition(
        run_id=api_run.id,
        organization_id=api_organization.id,
        event_type="progress.updated",
        payload={"current": 1, "total": 2},
    )
    append_event_and_transition(
        run_id=api_run.id,
        organization_id=api_organization.id,
        event_type="output.snapshot",
        payload={"result": "final answer", "model": "test"},
    )
    append_event_and_transition(
        run_id=api_run.id,
        organization_id=api_organization.id,
        event_type="workflow.step.completed",
        payload={"workflow_step_key": "write", "output": {"ok": True}},
    )
    snapshot = compact_run_events(
        run_id=api_run.id,
        before=timezone.now() + timedelta(seconds=1),
        include_active=True,
    )

    compacted = authenticated_client.get(
        _run_url(api_organization, api_run, "/events"),
        {"after": 0},
    )
    recovered = authenticated_client.get(
        _run_url(api_organization, api_run, "/snapshot")
    )
    resumed = authenticated_client.get(
        _run_url(api_organization, api_run, "/events"),
        {"after": snapshot.through_sequence},
    )

    assert compacted.status_code == 410
    assert compacted.data["code"] == "event_history_compacted"
    assert compacted.data["resume_after"] == 5
    assert recovered.status_code == 200
    assert recovered.data["through_sequence"] == 5
    assert recovered.data["projection"]["output"] == "final answer"
    assert recovered.data["projection"]["progress"] == {"current": 1, "total": 2}
    assert recovered.data["projection"]["tools"]["workflow:write"] == {
        "workflow_step_key": "write",
        "output": {"ok": True},
        "event_type": "workflow.step.completed",
    }
    assert resumed.status_code == 200
    assert resumed.data["results"] == []
    assert resumed.data["high_water"] == 5


@pytest.mark.django_db
def test_run_detail_rejects_non_member(api_organization, api_run):
    outsider = get_user_model().objects.create_user(username="execution-api-outsider")
    client = APIClient()
    client.force_authenticate(outsider)

    response = client.get(_run_url(api_organization, api_run))

    assert response.status_code == 403
    assert response["Content-Type"].startswith("application/problem+json")
    assert response.data["code"] == "permission_denied"


@pytest.mark.django_db
def test_events_api_replays_after_sequence(
    authenticated_client, api_organization, api_run
):
    response = authenticated_client.get(
        _run_url(api_organization, api_run, "/events"),
        {"after": 0, "limit": 1},
    )

    assert response.status_code == 200
    assert response.data["next_after"] == 1
    assert response.data["high_water"] == 1
    assert response.data["has_more"] is False
    assert response.data["results"][0] == {
        "schema_version": 1,
        "run_id": str(api_run.id),
        "attempt_id": None,
        "sequence": 1,
        "type": "run.queued",
        "payload": response.data["results"][0]["payload"],
        "created_at": response.data["results"][0]["created_at"],
    }


@pytest.mark.django_db
def test_events_api_rejects_invalid_cursor(
    authenticated_client, api_organization, api_run
):
    response = authenticated_client.get(
        _run_url(api_organization, api_run, "/events"),
        {"after": "not-a-number"},
    )

    assert response.status_code == 400
    assert response["Content-Type"].startswith("application/problem+json")
    assert response.data["code"] == "invalid_event_cursor"


@pytest.mark.django_db
def test_cancel_command_is_atomic_and_idempotent(
    authenticated_client, api_organization, api_run
):
    url = _run_url(api_organization, api_run, "/commands")
    body = {
        "type": "cancel",
        "idempotency_key": "cancel-from-run-page",
        "expected_run_version": 1,
        "payload": {"reason": "user_requested"},
    }

    created = authenticated_client.post(url, body, format="json")
    replayed = authenticated_client.post(url, body, format="json")

    assert created.status_code == 202
    assert created.data["result"] == {
        "accepted": True,
        "run_id": str(api_run.id),
        "run_status": "cancelled",
        "run_version": 2,
    }
    assert replayed.status_code == 202
    assert replayed["Idempotent-Replay"] == "true"
    assert replayed.data["id"] == created.data["id"]
    assert IdempotencyRecord.objects.filter(operation="run.command.submit").count() == 1
    api_run.refresh_from_db()
    assert api_run.status == Run.Status.CANCELLED
    assert api_run.finished_at is not None
    assert list(api_run.events.values_list("sequence", "type")) == [
        (1, "run.queued"),
        (2, "run.cancelled"),
    ]


@pytest.mark.django_db
def test_command_rejects_reused_key_with_different_payload(
    authenticated_client, api_organization, api_run
):
    url = _run_url(api_organization, api_run, "/commands")
    original = {
        "type": "cancel",
        "idempotency_key": "one-key",
        "payload": {"reason": "first"},
    }
    changed = {
        "type": "cancel",
        "idempotency_key": "one-key",
        "payload": {"reason": "changed"},
    }

    assert authenticated_client.post(url, original, format="json").status_code == 202
    response = authenticated_client.post(url, changed, format="json")

    assert response.status_code == 409
    assert response.data["code"] == "idempotency_key_reused"


@pytest.mark.django_db
def test_command_rejects_stale_run_version(
    authenticated_client, api_organization, api_run
):
    response = authenticated_client.post(
        _run_url(api_organization, api_run, "/commands"),
        {
            "type": "cancel",
            "idempotency_key": "stale-command",
            "expected_run_version": 99,
        },
        format="json",
    )

    assert response.status_code == 409
    assert response.data["code"] == "concurrent_run_update"
    assert api_run.commands.count() == 0


@pytest.mark.django_db
def test_interactive_command_requires_waiting_checkpoint(
    authenticated_client, api_organization, api_run
):
    response = authenticated_client.post(
        _run_url(api_organization, api_run, "/commands"),
        {
            "type": "answer",
            "idempotency_key": "answer-before-question",
            "payload": {"answer": "yes"},
        },
        format="json",
    )

    assert response.status_code == 409
    assert response.data["code"] == "command_not_allowed"
    assert api_run.commands.count() == 0


@pytest.mark.django_db(transaction=True)
def test_answer_command_requires_current_request_id_and_requeues(
    authenticated_client, api_actor, api_organization, api_run
):
    claimed = claim_next_run(
        worker_id="api-test-worker",
        worker_pool=Run.ExecutorKind.MEDIA,
    )
    fence = LeaseFence(token=claimed.lease.token, epoch=claimed.lease.epoch)
    checkpoint, _event, _created = record_artifact(
        run_id=api_run.id,
        organization_id=api_organization.id,
        attempt_id=claimed.attempt.id,
        lease_fence=fence,
        kind="checkpoint",
        object_key="api-checkpoint.json",
        content_hash="c" * 64,
        mime_type="application/json",
        size=10,
    )
    input_request_id = uuid.uuid4()
    suspend_attempt_for_input(
        run_id=api_run.id,
        organization_id=api_organization.id,
        attempt_id=claimed.attempt.id,
        lease_fence=fence,
        checkpoint_artifact_id=checkpoint.id,
        input_request_id=input_request_id,
        input_kind=Run.InputKind.ANSWER,
        expires_at=timezone.now() + timedelta(minutes=5),
        request_payload={"prompt": "Approve?"},
    )
    url = _run_url(api_organization, api_run, "/commands")

    attempts = authenticated_client.get(
        _run_url(api_organization, api_run, "/attempts")
    )
    artifacts = authenticated_client.get(
        _run_url(api_organization, api_run, "/artifacts")
    )

    mismatch = authenticated_client.post(
        url,
        {
            "type": "answer",
            "idempotency_key": "wrong-request",
            "input_request_id": str(uuid.uuid4()),
            "payload": {"answer": "yes"},
        },
        format="json",
    )
    accepted = authenticated_client.post(
        url,
        {
            "type": "answer",
            "idempotency_key": "correct-request",
            "input_request_id": str(input_request_id),
            "payload": {"answer": "yes"},
        },
        format="json",
    )

    assert mismatch.status_code == 409
    assert mismatch.data["code"] == "input_request_mismatch"
    assert accepted.status_code == 202
    assert accepted.data["result"]["run_status"] == Run.Status.QUEUED
    assert attempts.status_code == 200
    assert attempts.data["results"][0]["checkpoint_artifact_id"] == str(
        checkpoint.id
    )
    assert artifacts.status_code == 200
    assert artifacts.data["results"][0]["id"] == str(checkpoint.id)
    assert artifacts.data["results"][0]["content_hash"] == "c" * 64


@pytest.mark.django_db
def test_start_application_run_pins_deployed_revision_and_replays(
    authenticated_client, api_actor, api_organization, deployed_application
):
    url = (
        f"/api/v1/organizations/{api_organization.id}/applications/"
        f"{deployed_application.id}/runs"
    )
    body = {"input": {"files": ["one.mp4"]}}

    created = authenticated_client.post(
        url,
        body,
        format="json",
        HTTP_IDEMPOTENCY_KEY="start-one",
    )
    replayed = authenticated_client.post(
        url,
        body,
        format="json",
        HTTP_IDEMPOTENCY_KEY="start-one",
    )

    assert created.status_code == 202
    assert replayed.status_code == 202
    assert replayed["Idempotent-Replay"] == "true"
    assert replayed.data["id"] == created.data["id"]
    run = Run.objects.get(pk=created.data["id"])
    revision = deployed_application.revisions.get()
    assert run.owner == api_actor
    assert run.executor_kind == Run.ExecutorKind.MEDIA
    assert run.max_attempts == 2
    assert run.definition_snapshot["application_revision_id"] == str(revision.id)
    assert run.definition_snapshot["application_content_hash"] == revision.content_hash
    assert created.data["stream_url"].endswith(f"/runs/{run.id}/stream")
    assert created["Location"].endswith(f"/runs/{run.id}")


@pytest.mark.django_db
def test_start_application_run_freezes_deployed_skill_revision(
    authenticated_client, api_actor, api_organization, deployed_application
):
    skill = Skill.objects.create(
        organization=api_organization,
        owner=api_actor,
        slug="storyboard-runtime",
        name="Storyboard Runtime",
        visibility=Skill.Visibility.ORGANIZATION,
    )
    first_content = {"artifact_key": "skills/storyboard/v1"}
    first = SkillRevision.objects.create(
        organization=api_organization,
        skill=skill,
        revision_no=1,
        content=first_content,
        content_hash=canonical_content_hash(first_content),
        created_by=api_actor,
    )
    deployment = SkillDeployment.objects.create(
        organization=api_organization,
        skill=skill,
        revision=first,
        updated_by=api_actor,
    )
    application_revision = deployed_application.revisions.get()
    application_content = {
        **application_revision.content,
        "dependencies": {"agents": [], "skills": [{"skill_id": str(skill.id)}]},
    }
    application_revision = ApplicationRevision.objects.create(
        organization=api_organization,
        application=deployed_application,
        revision_no=2,
        content=application_content,
        content_hash=canonical_content_hash(application_content),
        created_by=api_actor,
    )
    ApplicationDeployment.objects.filter(application=deployed_application).update(
        revision=application_revision, version=2
    )
    url = (
        f"/api/v1/organizations/{api_organization.id}/applications/"
        f"{deployed_application.id}/runs"
    )

    created = authenticated_client.post(
        url, {"input": {}}, format="json",
        HTTP_IDEMPOTENCY_KEY="freeze-skill-revision",
    )
    assert created.status_code == 202, created.data
    run = Run.objects.get(pk=created.data["id"])
    frozen = run.definition_snapshot["skill_revisions"][0]

    second_content = {"artifact_key": "skills/storyboard/v2"}
    second = SkillRevision.objects.create(
        organization=api_organization,
        skill=skill,
        revision_no=2,
        content=second_content,
        content_hash=canonical_content_hash(second_content),
        created_by=api_actor,
    )
    SkillDeployment.objects.filter(pk=deployment.pk).update(
        revision=second, previous_revision=first, version=2
    )
    run.refresh_from_db()

    assert frozen["revision_id"] == str(first.id)
    assert frozen["deployment_version"] == 1
    assert frozen["content"] == first_content
    assert run.definition_snapshot["skill_revisions"][0] == frozen


@pytest.mark.django_db
def test_start_application_run_rejects_undeployed_skill(
    authenticated_client, api_actor, api_organization, deployed_application
):
    skill = Skill.objects.create(
        organization=api_organization,
        owner=api_actor,
        slug="undeployed-skill",
        name="Undeployed Skill",
    )
    base_revision = deployed_application.revisions.get()
    content = {
        **base_revision.content,
        "dependencies": {"agents": [], "skills": [{"skill_id": str(skill.id)}]},
    }
    revision = ApplicationRevision.objects.create(
        organization=api_organization,
        application=deployed_application,
        revision_no=2,
        content=content,
        content_hash=canonical_content_hash(content),
        created_by=api_actor,
    )
    ApplicationDeployment.objects.filter(application=deployed_application).update(
        revision=revision, version=2
    )
    url = (
        f"/api/v1/organizations/{api_organization.id}/applications/"
        f"{deployed_application.id}/runs"
    )

    response = authenticated_client.post(
        url, {"input": {}}, format="json",
        HTTP_IDEMPOTENCY_KEY="undeployed-skill",
    )

    assert response.status_code == 409
    assert response.data["code"] == "deployment_unavailable"
    assert str(skill.id) in response.data["detail"]
    assert Run.objects.count() == 0


@pytest.mark.django_db
def test_start_application_run_applies_governance_to_nested_input(
    authenticated_client, api_organization, deployed_application
):
    from apps.enterprise.models import GovernancePolicy
    policy, _ = GovernancePolicy.objects.get_or_create(
        organization=api_organization
    )
    policy.require_tool_approval = True
    policy.save(update_fields=["require_tool_approval"])
    url = (
        f"/api/v1/organizations/{api_organization.id}/applications/"
        f"{deployed_application.id}/runs"
    )

    response = authenticated_client.post(
        url,
        {"input": {"owner": {"email": "person@example.com"}}},
        format="json",
        HTTP_IDEMPOTENCY_KEY="governed-start",
    )

    assert response.status_code == 202
    run = Run.objects.get(pk=response.data["id"])
    assert run.input["owner"]["email"] == "[REDACTED]"
    assert run.definition_snapshot["governance"]["require_tool_approval"] is True


@pytest.mark.django_db
def test_start_application_run_rejects_changed_idempotent_request(
    authenticated_client, api_organization, deployed_application
):
    url = (
        f"/api/v1/organizations/{api_organization.id}/applications/"
        f"{deployed_application.id}/runs"
    )
    headers = {"HTTP_IDEMPOTENCY_KEY": "start-reused"}
    first = authenticated_client.post(
        url,
        {"input": {"files": ["one.mp4"]}},
        format="json",
        **headers,
    )
    changed = authenticated_client.post(
        url,
        {"input": {"files": ["two.mp4"]}},
        format="json",
        **headers,
    )

    assert first.status_code == 202
    assert changed.status_code == 409
    assert changed.data["code"] == "idempotency_key_reused"
    assert Run.objects.count() == 1


@pytest.mark.django_db
def test_start_application_run_requires_idempotency_key(
    authenticated_client, api_organization, deployed_application
):
    url = (
        f"/api/v1/organizations/{api_organization.id}/applications/"
        f"{deployed_application.id}/runs"
    )

    response = authenticated_client.post(url, {"input": {}}, format="json")

    assert response.status_code == 400
    assert response.data["code"] == "invalid_idempotency_key"


@pytest.mark.django_db
def test_viewer_cannot_start_or_cancel_runs(
    api_organization, deployed_application, api_run
):
    viewer = get_user_model().objects.create_user(username="execution-api-viewer")
    Membership.objects.create(
        organization=api_organization,
        user=viewer,
        role=Membership.Role.VIEWER,
    )
    client = APIClient()
    client.force_authenticate(viewer)
    start_url = (
        f"/api/v1/organizations/{api_organization.id}/applications/"
        f"{deployed_application.id}/runs"
    )

    start = client.post(
        start_url,
        {"input": {}},
        format="json",
        HTTP_IDEMPOTENCY_KEY="viewer-start",
    )
    cancel = client.post(
        _run_url(api_organization, api_run, "/commands"),
        {"type": "cancel", "idempotency_key": "viewer-cancel"},
        format="json",
    )

    assert start.status_code == 403
    assert cancel.status_code == 403


@pytest.mark.django_db
def test_stream_uses_last_event_id_and_sse_headers(
    authenticated_client, api_organization, api_run
):
    response = authenticated_client.get(
        _run_url(api_organization, api_run, "/stream"),
        HTTP_ACCEPT="text/event-stream",
        HTTP_LAST_EVENT_ID="1",
    )

    assert response.status_code == 200
    assert response.streaming is True
    assert response["Content-Type"].startswith("text/event-stream")
    assert response["Cache-Control"] == "no-cache, no-transform"
    assert response["X-Accel-Buffering"] == "no"


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_stream_replays_persisted_events(api_actor, api_organization, api_run):
    stream = stream_run_events(
        user=api_actor,
        organization_id=api_organization.id,
        run_id=api_run.id,
        after=0,
        poll_interval=0.05,
    )

    first_chunk = await asyncio.wait_for(anext(stream), timeout=2)
    await stream.aclose()

    assert first_chunk.startswith(b"id: 1\nevent: run.queued\ndata: ")
    assert f'"run_id":"{api_run.id}"'.encode() in first_chunk
