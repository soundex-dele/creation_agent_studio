from datetime import datetime, timezone as datetime_timezone
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.applications.models import Application, ApplicationCategory
from apps.automations.models import Automation, AutomationInvocation
from apps.automations.management.commands.run_automation_scheduler import Command
from apps.automations.scheduling import preview_schedule
from apps.automations.services import dispatch_automation, rotate_secret
from apps.enterprise.models import Membership
from modules.catalog.models import (
    ApplicationDeployment,
    ApplicationRevision,
)
from modules.execution.models import Run


pytestmark = pytest.mark.django_db


@pytest.fixture
def owner():
    return get_user_model().objects.create_user(username="automation-owner")


@pytest.fixture
def organization(owner):
    return owner.organization_memberships.get().organization


@pytest.fixture
def application(owner, organization):
    category = ApplicationCategory.objects.create(name="Automation", slug="automation")
    app = Application.objects.create(
        category=category,
        name="Production application",
        slug="production-application",
        description="Application used by automation tests",
        created_by=owner,
        organization=organization,
        access_scope=Application.AccessScope.ORGANIZATION,
    )
    revision = ApplicationRevision.objects.create(
        organization=organization,
        application=app,
        revision_no=1,
        content={"executor_kind": "media", "executor_key": "batch-transcribe"},
        content_hash="a" * 64,
        created_by=owner,
    )
    ApplicationDeployment.objects.create(
        organization=organization,
        application=app,
        revision=revision,
        updated_by=owner,
    )
    return app


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def test_schedule_preview_uses_requested_timezone():
    runs = preview_schedule(
        kind="cron",
        expression="0 9 * * *",
        run_at=None,
        timezone_name="Asia/Shanghai",
        count=2,
        after=datetime(2026, 1, 1, tzinfo=datetime_timezone.utc),
    )
    assert [value.hour for value in runs] == [1, 1]
    assert runs[1] > runs[0]


def test_create_webhook_returns_secret_once(owner, organization, application):
    url = f"/api/v1/organizations/{organization.id}/automations"
    response = client_for(owner).post(url, {
        "name": "Inbound content",
        "trigger_type": "webhook",
        "target_type": "application",
        "target_id": str(application.id),
        "default_input": {"channel": "web"},
        "schedule_kind": "",
        "timezone": "Asia/Shanghai",
        "schedule": "",
    }, format="json")
    assert response.status_code == 201
    assert response.data["webhook_secret"]
    detail = client_for(owner).get(f"{url}/{response.data['id']}")
    assert detail.status_code == 200
    assert "webhook_secret" not in detail.data
    assert detail.data["secret_prefix"]


def test_webhook_merges_defaults_and_is_idempotent(
    monkeypatch, owner, organization, application
):
    automation = Automation.objects.create(
        organization=organization,
        created_by=owner,
        name="Webhook",
        trigger_type=Automation.TriggerType.WEBHOOK,
        target_type=Automation.TargetType.APPLICATION,
        target_id=str(application.id),
        application=application,
        default_input={"channel": "default", "audience": "writers"},
        status=Automation.Status.ACTIVE,
        is_active=True,
    )
    secret = rotate_secret(automation)
    captured = {}

    def fake_start(target, invocation, payload):
        captured.update({**target.default_input, **payload})
        return Run.objects.create(
            organization=organization,
            owner=owner,
            executor_kind=Run.ExecutorKind.MEDIA,
            executor_key="batch-transcribe",
            source_type="application",
            source_id=str(application.id),
        )

    monkeypatch.setattr("apps.automations.services._start_target_run", fake_start)
    client = APIClient()
    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {secret}",
        HTTP_IDEMPOTENCY_KEY="delivery-1",
    )
    url = f"/api/v1/hooks/automations/{automation.public_id}"
    first = client.post(url, {"channel": "hook", "topic": "AI"}, format="json")
    second = client.post(url, {"channel": "hook", "topic": "AI"}, format="json")
    conflict = client.post(url, {"topic": "different"}, format="json")
    assert first.status_code == 202
    assert second.status_code == 202
    assert second.data["replayed"] is True
    assert conflict.status_code == 409
    assert captured == {"channel": "hook", "audience": "writers", "topic": "AI"}
    assert AutomationInvocation.objects.count() == 1


def test_capacity_limit_records_skipped_invocation(
    monkeypatch, owner, organization, application
):
    automation = Automation.objects.create(
        organization=organization,
        created_by=owner,
        name="Busy automation",
        trigger_type="webhook",
        target_type="application",
        target_id=str(application.id),
        application=application,
        status="active",
    )
    monkeypatch.setattr("apps.automations.services.pending_run_count", lambda _item: 100)
    invocation, _ = dispatch_automation(
        automation,
        source=AutomationInvocation.Source.WEBHOOK,
        payload={},
        dedup_key="capacity",
    )
    assert invocation.outcome == AutomationInvocation.Outcome.SKIPPED_CAPACITY
    assert invocation.run_id is None


def test_scheduler_catches_up_once_and_advances_to_future(
    monkeypatch, owner, organization, application
):
    automation = Automation.objects.create(
        organization=organization,
        created_by=owner,
        name="Daily automation",
        trigger_type="schedule",
        target_type="application",
        target_id=str(application.id),
        application=application,
        status="active",
        is_active=True,
        schedule_kind="cron",
        schedule="*/5 * * * *",
        timezone="UTC",
        next_run_at=datetime.now(datetime_timezone.utc) - timedelta(hours=2),
    )
    calls = []

    def capture(item, **kwargs):
        calls.append((item.id, kwargs["scheduled_for"]))
        return None, False

    monkeypatch.setattr(
        "apps.automations.management.commands.run_automation_scheduler.dispatch_automation",
        capture,
    )
    Command().dispatch_due()
    automation.refresh_from_db()
    assert len(calls) == 1
    assert automation.next_run_at > datetime.now(datetime_timezone.utc)
    assert automation.last_scheduled_at == calls[0][1]


def test_viewer_can_read_but_not_create(owner, organization, application):
    viewer = get_user_model().objects.create_user(username="automation-viewer")
    Membership.objects.filter(user=viewer).delete()
    Membership.objects.create(
        organization=organization, user=viewer, role=Membership.Role.VIEWER
    )
    url = f"/api/v1/organizations/{organization.id}/automations"
    assert client_for(viewer).get(url).status_code == 200
    denied = client_for(viewer).post(url, {
        "name": "Denied",
        "trigger_type": "webhook",
        "target_type": "application",
        "target_id": str(application.id),
        "default_input": {},
    }, format="json")
    assert denied.status_code == 403
