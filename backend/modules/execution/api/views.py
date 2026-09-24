from datetime import timedelta

from django.conf import settings
from django.core import signing
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.http import FileResponse, StreamingHttpResponse
from django.urls import reverse
from django.utils import timezone
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from modules.execution.application.commands import submit_run_command
from modules.execution.application.errors import (
    CommandNotAllowed,
    ConcurrentRunUpdate,
    DeploymentUnavailable,
    IdempotencyKeyReused,
    InvalidExecutionDefinition,
)
from modules.execution.application.start_runs import start_agent_run, start_application_run
from modules.execution.infrastructure.artifacts import (
    ArtifactObjectUnavailable,
    UnsafeArtifactObjectKey,
    artifact_token,
    decode_artifact_token,
    delete_artifact_object,
    external_artifact_access_url,
    open_artifact,
)
from modules.execution.models import (
    Run,
    RunArtifact,
    RunAttempt,
    RunEvent,
    RunEventSnapshot,
)
from apps.enterprise.models import Membership
from apps.projects.services.workspace_paths import (
    open_workspace_directory,
    workflow_working_directory,
)
from modules.tenancy.permissions import HasPathOrganizationRole

from .base import ProblemDetailsAPIView
from .pagination import RunArtifactCursorPagination, RunAttemptCursorPagination
from .permissions import TERMINAL_RUN_STATUSES, can_delete_run
from .renderers import EventStreamRenderer
from .serializers import (
    RunCommandSerializer,
    RunArtifactSerializer,
    RunAttemptSerializer,
    RunEventSerializer,
    RunEventSnapshotSerializer,
    RunSerializer,
    StartApplicationRunSerializer,
    StartAgentRunSerializer,
    SubmitRunCommandSerializer,
)
from .streaming import stream_run_events


def _run_serializer_context(request, runs):
    """Bulk-load conversation labels and owning applications for task history."""
    from apps.conversations.models import Conversation

    conversation_ids = {
        value
        for value in (RunSerializer._conversation_id(run) for run in runs)
        if value
    }
    organization_ids = {run.organization_id for run in runs}
    metadata = {
        str(item["id"]): {
            "title": item["title"],
            "chat_application_id": item["chat_application_id"],
        }
        for item in Conversation.objects.filter(
            id__in=conversation_ids,
            organization_id__in=organization_ids,
        ).values("id", "title", "chat_application_id")
    }
    return {"request": request, "run_conversation_metadata": metadata}


def _problem(request, *, status_code, code, title, detail):
    return Response(
        {
            "type": f"urn:agent-studio:problem:{code}",
            "code": code,
            "title": title,
            "status": status_code,
            "detail": detail,
            "request_id": getattr(request, "request_id", ""),
        },
        status=status_code,
        content_type="application/problem+json",
    )


def _parse_non_negative_int(request, name, default):
    raw = request.query_params.get(name)
    if raw in (None, ""):
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def _compacted_problem(request, snapshot):
    snapshot_url = reverse(
        "execution-v1:run-event-snapshot",
        kwargs={
            "organization_id": snapshot.organization_id,
            "run_id": snapshot.run_id,
        },
    )
    response = _problem(
        request,
        status_code=status.HTTP_410_GONE,
        code="event_history_compacted",
        title="Event history compacted",
        detail="The requested cursor predates the retained Run event history.",
    )
    response.data.update(
        {
            "snapshot_url": request.build_absolute_uri(snapshot_url),
            "snapshot_through_sequence": snapshot.through_sequence,
            "resume_after": snapshot.through_sequence,
        }
    )
    return response


def _workflow_conversation_ids(run_ids):
    """Collect conversations owned by one workflow Run tree."""

    conversation_ids = set()

    def add(value):
        try:
            conversation_ids.add(int(value))
        except (TypeError, ValueError):
            return

    runs = Run.objects.filter(id__in=run_ids).only(
        "definition_snapshot", "output_summary"
    )
    for item in runs:
        definition = dict(item.definition_snapshot or {})
        add(definition.get("conversation_id"))
        for step in definition.get("workflow_steps") or []:
            if isinstance(step, dict):
                add(step.get("conversation_id"))
        summary = dict(item.output_summary or {})
        conversations = summary.get("conversations") or {}
        if isinstance(conversations, dict):
            for conversation_id in conversations.values():
                add(conversation_id)
        for conversation_id in item.projected_messages.values_list(
            "conversation_id", flat=True
        ).distinct():
            add(conversation_id)
    return conversation_ids


def _run_tree_ids(organization_id, root_id):
    values = [root_id]
    frontier = [root_id]
    while frontier:
        frontier = list(
            Run.objects.for_organization(organization_id)
            .filter(parent_id__in=frontier)
            .values_list("id", flat=True)
        )
        values.extend(frontier)
    return values


def _can_access_run(request, run):
    root = run
    while root.parent_id:
        root = Run.objects.get(pk=root.parent_id)
    if root.executor_key == "ai-drawing":
        if root.owner_id != request.user.id:
            return False
        from django.http import Http404
        from rest_framework.exceptions import APIException
        from app_center.ai_drawing.backend.access import application_for
        try:
            application_for(request.user, root.organization_id, root.source_id)
        except (Http404, APIException, ValueError):
            return False
        return True
    if root.executor_key == "meeting-assistant":
        if root.owner_id != request.user.id:
            return False
        from django.http import Http404
        from rest_framework.exceptions import APIException
        from app_center.meeting_assistant.backend.access import recording_for
        try:
            recording_for(request.user, root.organization_id, root.source_id,
                          (root.input or {}).get("record_id"))
        except (Http404, APIException, ValueError):
            return False
        return True
    if (root.input or {}).get("document_id"):
        if root.owner_id != request.user.id:
            return False
        from django.apps import apps
        from django.http import Http404
        from rest_framework.exceptions import APIException
        if not apps.is_installed("app_center.documents.backend"):
            return False
        from app_center.documents.backend.models import Document
        from app_center.documents.backend.access import document_for
        doc = Document.objects.filter(pk=root.input["document_id"]).first()
        if doc is None:
            return False
        try:
            document_for(request.user, root.organization_id, doc.application_id, doc.pk)
        except (Http404, APIException):
            return False
        return True
    if root.source_type != "supervisor":
        return True
    if request.user.is_superuser or root.owner_id == request.user.id:
        return True
    from apps.agents.models import Agent
    from core.resource_access import can_access_resource

    supervisor = Agent.objects.select_related("supervisor_profile").filter(
        pk=root.source_id,
        organization_id=root.organization_id,
        kind=Agent.Kind.SUPERVISOR,
    ).first()
    if supervisor is None:
        return False
    return can_access_resource(supervisor, request.user, operation="run")


class OrganizationRunView(ProblemDetailsAPIView):
    permission_classes = (IsAuthenticated, HasPathOrganizationRole)

    def get(self, request, organization_id, run_id):
        run = (
            Run.objects.for_organization(organization_id)
            .select_related("current_attempt")
            .filter(pk=run_id)
            .first()
        )
        if run is None or not _can_access_run(request, run):
            return _problem(
                request,
                status_code=status.HTTP_404_NOT_FOUND,
                code="run_not_found",
                title="Run not found",
                detail="The requested run does not exist or is not accessible.",
            )
        body = RunSerializer(run, context={"request": request}).data
        if run.source_type == "workflow":
            body["workflow_conversations"] = {
                child.node_key: str(conversation_id)
                for child in run.child_runs.only(
                    "node_key", "definition_snapshot"
                )
                if child.node_key
                for conversation_id in [
                    (child.definition_snapshot or {}).get("conversation_id")
                ]
                if conversation_id
            }
        return Response(body)

    def delete(self, request, organization_id, run_id):
        run = Run.objects.for_organization(organization_id).filter(pk=run_id).first()
        if run is None or (run.executor_key == "ai-drawing" and not _can_access_run(request, run)):
            return _problem(
                request,
                status_code=status.HTTP_404_NOT_FOUND,
                code="run_not_found",
                title="Run not found",
                detail="The requested run does not exist or is not accessible.",
            )
        if not can_delete_run(run, request):
            return _problem(
                request,
                status_code=status.HTTP_403_FORBIDDEN,
                code="run_delete_forbidden",
                title="Run deletion forbidden",
                detail="无权删除该执行记录。",
            )

        if run.status not in TERMINAL_RUN_STATUSES:
            if run.executor_key == "workflow-manual":
                with transaction.atomic():
                    locked = Run.objects.select_for_update().get(pk=run.pk)
                    if locked.status not in TERMINAL_RUN_STATUSES:
                        now = timezone.now()
                        locked.status = Run.Status.CANCELLED
                        locked.finished_at = now
                        locked.version += 1
                        locked.next_event_sequence += 1
                        locked.save(update_fields=(
                            "status", "finished_at", "version", "next_event_sequence",
                        ))
                        RunEvent.objects.create(
                            organization_id=locked.organization_id,
                            run=locked,
                            sequence=locked.next_event_sequence,
                            type="run.cancelled",
                            payload={"reason": "delete_requested", "manual": True},
                        )
                run.refresh_from_db()
            elif run.status != Run.Status.CANCELLING:
                try:
                    submit_run_command(
                        run_id=run.id,
                        organization_id=organization_id,
                        actor=request.user,
                        command_type="cancel",
                        idempotency_key=f"delete-run:{run.id}:{run.version}",
                        payload={"reason": "delete_requested"},
                    )
                except (CommandNotAllowed, ConcurrentRunUpdate):
                    # A terminal transition may win the race after the initial
                    # read. The next delete poll will either remove it or retry
                    # cancellation against the new version.
                    pass
                run.refresh_from_db()

        run_ids = [run.id]
        frontier = [run.id]
        while frontier:
            frontier = list(
                Run.objects.for_organization(organization_id)
                .filter(parent_id__in=frontier)
                .values_list("id", flat=True)
            )
            run_ids.extend(frontier)
        active_statuses = set(Run.Status.values) - set(TERMINAL_RUN_STATUSES)
        if Run.objects.filter(id__in=run_ids, status__in=active_statuses).exists():
            return Response(
                {
                    "deletion_pending": True,
                    "detail": "正在取消工作流，取消完成后将自动删除。",
                    "status": run.status,
                },
                status=status.HTTP_202_ACCEPTED,
            )
        object_keys = list(
            RunArtifact.objects.filter(run_id__in=run_ids)
            .values_list("object_key", flat=True)
        )
        try:
            with transaction.atomic():
                # Suspended workflow attempts protect their checkpoint artifact.
                # Both rows belong to the Run tree being deleted, so release
                # the pointer before Django collects the cascading deletes.
                RunAttempt.objects.filter(
                    run_id__in=run_ids,
                    checkpoint_artifact_id__isnull=False,
                ).update(checkpoint_artifact=None)
                if run.source_type == "workflow":
                    from apps.conversations.models import Conversation

                    conversation_ids = _workflow_conversation_ids(run_ids)
                    if conversation_ids:
                        Conversation.objects.filter(
                            id__in=conversation_ids,
                            organization_id=organization_id,
                            user_id=run.owner_id,
                        ).delete()
                run.delete()
        except ProtectedError:
            return _problem(
                request,
                status_code=status.HTTP_409_CONFLICT,
                code="run_is_referenced",
                title="Run is referenced",
                detail="该执行记录仍存在无法自动清理的关联数据，暂时无法删除。",
            )
        for object_key in filter(None, object_keys):
            try:
                delete_artifact_object(object_key)
            except (OSError, UnsafeArtifactObjectKey):
                continue
        return Response(status=status.HTTP_204_NO_CONTENT)


class OrganizationRunWorkspaceView(ProblemDetailsAPIView):
    """Open the shared directory owned by a workflow Run."""

    permission_classes = (IsAuthenticated, HasPathOrganizationRole)

    def post(self, request, organization_id, run_id):
        if not settings.LOCAL_FILE_MANAGER_ENABLED:
            return _problem(
                request,
                status_code=status.HTTP_409_CONFLICT,
                code="local_file_manager_disabled",
                title="Local file manager disabled",
                detail="当前部署不支持打开本机目录。",
            )
        run = (
            Run.objects.for_organization(organization_id)
            .select_related("owner", "organization")
            .filter(pk=run_id, owner=request.user)
            .first()
        )
        if run is None:
            return _problem(
                request,
                status_code=status.HTTP_404_NOT_FOUND,
                code="run_not_found",
                title="Run not found",
                detail="工作流执行记录不存在或无权访问。",
            )
        if run.source_type != "workflow":
            return _problem(
                request,
                status_code=status.HTTP_409_CONFLICT,
                code="run_has_no_workflow_workspace",
                title="Run has no workflow workspace",
                detail="该执行记录没有工作流共享目录。",
            )
        try:
            directory = workflow_working_directory(
                run.owner, run.organization, run.id,
                working_directory=(run.input or {}).get("working_directory"),
            )
            open_workspace_directory(directory)
        except (FileNotFoundError, OSError, RuntimeError):
            return _problem(
                request,
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                code="workflow_workspace_open_failed",
                title="Workflow workspace open failed",
                detail="无法打开当前工作流目录。",
            )
        return Response({"working_directory": directory})


class OrganizationRunsView(ProblemDetailsAPIView):
    """Canonical Run history for every executor kind."""

    permission_classes = (IsAuthenticated, HasPathOrganizationRole)
    allowed_source_types = {
        "application", "agent", "conversation", "workflow", "evaluation", "supervisor"
    }

    def get(self, request, organization_id):
        runs = Run.objects.for_organization(organization_id).select_related(
            "current_attempt", "automation_invocation__automation",
        ).order_by("-created_at")
        source_type = request.query_params.get("source_type")
        if source_type:
            if source_type not in self.allowed_source_types:
                return _problem(
                    request,
                    status_code=status.HTTP_400_BAD_REQUEST,
                    code="invalid_run_source_type",
                    title="Invalid Run source type",
                    detail=(
                        "source_type must be application, agent, conversation, "
                        "workflow, evaluation, or supervisor."
                    ),
                )
            runs = runs.filter(source_type=source_type)
        collapse_conversations = (
            request.query_params.get("collapse_conversations") == "true"
        )
        visible = []
        seen_conversation_ids = set()
        scan_limit = 2000 if collapse_conversations else 200
        for run in runs[:scan_limit]:
            if not _can_access_run(request, run):
                continue
            conversation_id = RunSerializer._conversation_id(run)
            if collapse_conversations and conversation_id:
                if conversation_id in seen_conversation_ids:
                    continue
                seen_conversation_ids.add(conversation_id)
            visible.append(run)
            if len(visible) == 100:
                break
        return Response(RunSerializer(
            visible, many=True, context=_run_serializer_context(request, visible)
        ).data)


class OrganizationRunEventsView(ProblemDetailsAPIView):
    permission_classes = (IsAuthenticated, HasPathOrganizationRole)
    max_limit = 500

    def get(self, request, organization_id, run_id):
        after = _parse_non_negative_int(request, "after", 0)
        limit = _parse_non_negative_int(request, "limit", 100)
        if after is None or limit is None or not 1 <= limit <= self.max_limit:
            return _problem(
                request,
                status_code=status.HTTP_400_BAD_REQUEST,
                code="invalid_event_cursor",
                title="Invalid event cursor",
                detail=f"after must be non-negative and limit must be between 1 and {self.max_limit}.",
            )

        run = Run.objects.for_organization(organization_id).filter(pk=run_id).first()
        if run is None or not _can_access_run(request, run):
            return _problem(
                request,
                status_code=status.HTTP_404_NOT_FOUND,
                code="run_not_found",
                title="Run not found",
                detail="The requested run does not exist or is not accessible.",
            )

        snapshot = RunEventSnapshot.objects.for_organization(
            organization_id
        ).filter(run=run).first()
        if snapshot is not None and after < snapshot.through_sequence:
            return _compacted_problem(request, snapshot)

        events = list(
            RunEvent.objects.for_organization(organization_id)
            .filter(run=run, sequence__gt=after)
            .order_by("sequence")[: limit + 1]
        )
        has_more = len(events) > limit
        page = events[:limit]
        next_after = page[-1].sequence if page else after
        high_water = (
            Run.objects.for_organization(organization_id)
            .filter(pk=run_id)
            .values_list("next_event_sequence", flat=True)
            .get()
        )
        return Response(
            {
                "results": RunEventSerializer(page, many=True).data,
                "next_after": next_after,
                "high_water": high_water,
                "has_more": has_more,
            }
        )


class OrganizationRunAttemptsView(ProblemDetailsAPIView):
    permission_classes = (IsAuthenticated, HasPathOrganizationRole)

    def get(self, request, organization_id, run_id):
        run = Run.objects.for_organization(organization_id).filter(pk=run_id).first()
        if run is None or not _can_access_run(request, run):
            return _problem(
                request,
                status_code=status.HTTP_404_NOT_FOUND,
                code="run_not_found",
                title="Run not found",
                detail="The requested run does not exist or is not accessible.",
            )
        attempts = RunAttempt.objects.filter(
            run_id=run_id,
            run__organization_id=organization_id,
        )
        paginator = RunAttemptCursorPagination()
        page = paginator.paginate_queryset(attempts, request, view=self)
        return paginator.get_paginated_response(
            RunAttemptSerializer(page, many=True).data
        )


class OrganizationRunArtifactsView(ProblemDetailsAPIView):
    permission_classes = (IsAuthenticated, HasPathOrganizationRole)

    @swagger_auto_schema(manual_parameters=[openapi.Parameter(
        'include_descendants',
        openapi.IN_QUERY,
        description='Include artifacts produced by descendant Runs.',
        type=openapi.TYPE_BOOLEAN,
        required=False,
    )], responses={200: RunArtifactSerializer(many=True)})
    def get(self, request, organization_id, run_id):
        run = Run.objects.for_organization(organization_id).filter(pk=run_id).first()
        if run is None or not _can_access_run(request, run):
            return _problem(
                request,
                status_code=status.HTTP_404_NOT_FOUND,
                code="run_not_found",
                title="Run not found",
                detail="The requested run does not exist or is not accessible.",
            )
        run_ids = (
            _run_tree_ids(organization_id, run_id)
            if request.query_params.get("include_descendants") == "true"
            else [run_id]
        )
        artifacts = RunArtifact.objects.for_organization(organization_id).filter(
            run_id__in=run_ids
        )
        paginator = RunArtifactCursorPagination()
        page = paginator.paginate_queryset(artifacts, request, view=self)
        return paginator.get_paginated_response(
            RunArtifactSerializer(page, many=True).data
        )


class OrganizationRunChildrenView(ProblemDetailsAPIView):
    permission_classes = (IsAuthenticated, HasPathOrganizationRole)

    @swagger_auto_schema(responses={200: RunSerializer(many=True)})
    def get(self, request, organization_id, run_id):
        root = Run.objects.for_organization(organization_id).filter(pk=run_id).first()
        if root is None or not _can_access_run(request, root):
            return _problem(
                request,
                status_code=status.HTTP_404_NOT_FOUND,
                code="run_not_found",
                title="Run not found",
                detail="The requested run does not exist or is not accessible.",
            )
        children = list(Run.objects.for_organization(organization_id).filter(
            parent_id__in=_run_tree_ids(organization_id, root.id)
        ).select_related("current_attempt").order_by("created_at", "id"))
        return Response(RunSerializer(
            children,
            many=True,
            context=_run_serializer_context(request, children),
        ).data)


class OrganizationRunArtifactAccessView(ProblemDetailsAPIView):
    permission_classes = (IsAuthenticated, HasPathOrganizationRole)

    def get(self, request, organization_id, run_id, artifact_id):
        artifact = RunArtifact.objects.for_organization(organization_id).filter(
            pk=artifact_id,
            run_id=run_id,
        ).first()
        if artifact is None or not _can_access_run(request, artifact.run):
            return _problem(
                request,
                status_code=status.HTTP_404_NOT_FOUND,
                code="run_artifact_not_found",
                title="Run artifact not found",
                detail="The requested artifact does not exist or is not accessible.",
            )
        ttl_seconds = int(getattr(settings, "ARTIFACT_ACCESS_TTL_SECONDS", 300))
        expires_at = timezone.now() + timedelta(seconds=ttl_seconds)
        access_url = external_artifact_access_url(
            request=request,
            artifact=artifact,
            expires_at=expires_at,
        )
        if access_url is None:
            content_url = reverse(
                "execution-v1:run-artifact-content",
                kwargs={
                    "organization_id": organization_id,
                    "run_id": run_id,
                    "artifact_id": artifact_id,
                },
            )
            access_url = request.build_absolute_uri(
                f"{content_url}?token={artifact_token(artifact)}"
            )
        return Response(
            {
                "artifact_id": str(artifact.id),
                "url": access_url,
                "expires_at": expires_at,
            }
        )


class RunArtifactContentView(ProblemDetailsAPIView):
    permission_classes = (AllowAny,)

    def get(self, request, organization_id, run_id, artifact_id):
        token = request.query_params.get("token", "")
        try:
            claims = decode_artifact_token(token)
        except signing.BadSignature:
            return _problem(
                request,
                status_code=status.HTTP_403_FORBIDDEN,
                code="invalid_artifact_access_token",
                title="Invalid artifact access token",
                detail="The artifact access URL is invalid or has expired.",
            )
        expected = {
            "organization_id": str(organization_id),
            "run_id": str(run_id),
            "artifact_id": str(artifact_id),
        }
        if any(str(claims.get(key)) != value for key, value in expected.items()):
            return _problem(
                request,
                status_code=status.HTTP_403_FORBIDDEN,
                code="invalid_artifact_access_token",
                title="Invalid artifact access token",
                detail="The artifact access URL does not match this artifact.",
            )
        artifact = RunArtifact.objects.for_organization(organization_id).filter(
            pk=artifact_id,
            run_id=run_id,
            content_hash=claims.get("content_hash"),
        ).first()
        if artifact is None:
            return _problem(
                request,
                status_code=status.HTTP_404_NOT_FOUND,
                code="run_artifact_not_found",
                title="Run artifact not found",
                detail="The requested artifact is no longer available.",
            )
        try:
            content = open_artifact(artifact)
        except UnsafeArtifactObjectKey:
            return _problem(
                request,
                status_code=status.HTTP_403_FORBIDDEN,
                code="unsafe_artifact_object_key",
                title="Unsafe artifact object key",
                detail="The artifact storage key is outside the configured root.",
            )
        except ArtifactObjectUnavailable:
            return _problem(
                request,
                status_code=status.HTTP_404_NOT_FOUND,
                code="artifact_object_unavailable",
                title="Artifact object unavailable",
                detail="The artifact metadata exists but its object is unavailable.",
            )
        filename = str(artifact.metadata.get("filename") or artifact.id)
        return FileResponse(
            content,
            as_attachment=True,
            filename=filename,
            content_type=artifact.mime_type,
        )


class OrganizationRunEventSnapshotView(ProblemDetailsAPIView):
    permission_classes = (IsAuthenticated, HasPathOrganizationRole)

    def get(self, request, organization_id, run_id):
        snapshot = RunEventSnapshot.objects.for_organization(
            organization_id
        ).filter(run_id=run_id).first()
        if snapshot is None or not _can_access_run(request, snapshot.run):
            return _problem(
                request,
                status_code=status.HTTP_404_NOT_FOUND,
                code="run_event_snapshot_not_found",
                title="Run event snapshot not found",
                detail="No compacted event snapshot is available for this Run.",
            )
        return Response(RunEventSnapshotSerializer(snapshot).data)


class OrganizationRunStreamView(ProblemDetailsAPIView):
    permission_classes = (IsAuthenticated, HasPathOrganizationRole)
    renderer_classes = (EventStreamRenderer,)

    def get(self, request, organization_id, run_id):
        run = Run.objects.for_organization(organization_id).filter(pk=run_id).first()
        if run is None or not _can_access_run(request, run):
            return _problem(
                request,
                status_code=status.HTTP_404_NOT_FOUND,
                code="run_not_found",
                title="Run not found",
                detail="The requested run does not exist or is not accessible.",
            )

        raw_after = request.query_params.get("after")
        if raw_after in (None, ""):
            raw_after = request.headers.get("Last-Event-ID")
        try:
            after = int(raw_after) if raw_after not in (None, "") else 0
        except (TypeError, ValueError):
            after = -1
        if after < 0:
            return _problem(
                request,
                status_code=status.HTTP_400_BAD_REQUEST,
                code="invalid_event_cursor",
                title="Invalid event cursor",
                detail="after or Last-Event-ID must be a non-negative integer.",
            )

        snapshot = RunEventSnapshot.objects.for_organization(
            organization_id
        ).filter(run=run).first()
        if snapshot is not None and after < snapshot.through_sequence:
            return _compacted_problem(request, snapshot)

        response = StreamingHttpResponse(
            stream_run_events(
                user=request.user,
                organization_id=organization_id,
                run_id=run_id,
                after=after,
            ),
            content_type="text/event-stream",
        )
        response["Cache-Control"] = "no-cache, no-transform"
        response["X-Accel-Buffering"] = "no"
        return response


class OrganizationRunCommandsView(ProblemDetailsAPIView):
    permission_classes = (IsAuthenticated, HasPathOrganizationRole)
    minimum_role = Membership.Role.OPERATOR

    @swagger_auto_schema(
        request_body=SubmitRunCommandSerializer,
        responses={202: RunCommandSerializer},
    )
    def post(self, request, organization_id, run_id):
        serializer = SubmitRunCommandSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        run = Run.objects.for_organization(organization_id).filter(pk=run_id).first()
        if run is None or not _can_access_run(request, run):
            return _problem(
                request,
                status_code=status.HTTP_404_NOT_FOUND,
                code="run_not_found",
                title="Run not found",
                detail="The requested run does not exist or is not accessible.",
            )

        try:
            command, replayed = submit_run_command(
                run_id=run_id,
                organization_id=organization_id,
                actor=request.user,
                command_type=serializer.validated_data["type"],
                idempotency_key=serializer.validated_data["idempotency_key"],
                input_request_id=serializer.validated_data.get("input_request_id"),
                expected_run_version=serializer.validated_data.get(
                    "expected_run_version"
                ),
                payload=serializer.validated_data.get("payload", {}),
            )
        except IdempotencyKeyReused as exc:
            return _problem(
                request,
                status_code=status.HTTP_409_CONFLICT,
                code=exc.code,
                title="Idempotency key reused",
                detail=str(exc),
            )
        except (ConcurrentRunUpdate, CommandNotAllowed) as exc:
            return _problem(
                request,
                status_code=status.HTTP_409_CONFLICT,
                code=exc.code,
                title="Run command rejected",
                detail=str(exc),
            )

        response = Response(
            RunCommandSerializer(command).data,
            status=status.HTTP_202_ACCEPTED,
        )
        if replayed:
            response["Idempotent-Replay"] = "true"
        return response


class OrganizationApplicationRunsView(ProblemDetailsAPIView):
    permission_classes = (IsAuthenticated, HasPathOrganizationRole)
    minimum_role = Membership.Role.OPERATOR

    def post(self, request, organization_id, application_id):
        serializer = StartApplicationRunSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        idempotency_key = (request.headers.get("Idempotency-Key") or "").strip()
        if not idempotency_key or len(idempotency_key) > 160:
            return _problem(
                request,
                status_code=status.HTTP_400_BAD_REQUEST,
                code="invalid_idempotency_key",
                title="Invalid idempotency key",
                detail="Idempotency-Key must contain between 1 and 160 characters.",
            )
        try:
            run, replayed = start_application_run(
                organization_id=organization_id,
                application_id=application_id,
                actor=request.user,
                input_data=serializer.validated_data["input"],
                priority=serializer.validated_data["priority"],
                idempotency_key=idempotency_key,
            )
        except IdempotencyKeyReused as exc:
            return _problem(
                request,
                status_code=status.HTTP_409_CONFLICT,
                code=exc.code,
                title="Idempotency key reused",
                detail=str(exc),
            )
        except DeploymentUnavailable as exc:
            return _problem(
                request,
                status_code=status.HTTP_409_CONFLICT,
                code=exc.code,
                title="Deployment unavailable",
                detail=str(exc),
            )
        except InvalidExecutionDefinition as exc:
            return _problem(
                request,
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                code=exc.code,
                title="Invalid execution definition",
                detail=str(exc),
            )

        detail_url = reverse(
            "execution-v1:run-detail",
            kwargs={"organization_id": organization_id, "run_id": run.id},
        )
        stream_url = reverse(
            "execution-v1:run-stream",
            kwargs={"organization_id": organization_id, "run_id": run.id},
        )
        body = RunSerializer(run).data
        body["stream_url"] = request.build_absolute_uri(stream_url)
        response = Response(body, status=status.HTTP_202_ACCEPTED)
        response["Location"] = request.build_absolute_uri(detail_url)
        if replayed:
            response["Idempotent-Replay"] = "true"
        return response


class OrganizationAgentRunsView(ProblemDetailsAPIView):
    permission_classes = (IsAuthenticated, HasPathOrganizationRole)
    minimum_role = Membership.Role.OPERATOR

    def post(self, request, organization_id, agent_id):
        serializer = StartAgentRunSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        idempotency_key = (request.headers.get("Idempotency-Key") or "").strip()
        if not idempotency_key or len(idempotency_key) > 160:
            return _problem(
                request,
                status_code=status.HTTP_400_BAD_REQUEST,
                code="invalid_idempotency_key",
                title="Invalid idempotency key",
                detail="Idempotency-Key must contain between 1 and 160 characters.",
            )
        try:
            run, replayed = start_agent_run(
                organization_id=organization_id,
                agent_id=agent_id,
                actor=request.user,
                input_data=serializer.validated_data["input"],
                priority=serializer.validated_data["priority"],
                idempotency_key=idempotency_key,
            )
        except IdempotencyKeyReused as exc:
            return _problem(request, status_code=409, code=exc.code,
                            title="Idempotency key reused", detail=str(exc))
        except DeploymentUnavailable as exc:
            return _problem(request, status_code=409, code=exc.code,
                            title="Deployment unavailable", detail=str(exc))
        except InvalidExecutionDefinition as exc:
            return _problem(request, status_code=422, code=exc.code,
                            title="Invalid execution definition", detail=str(exc))
        body = RunSerializer(run).data
        body["stream_url"] = request.build_absolute_uri(reverse(
            "execution-v1:run-stream",
            kwargs={"organization_id": organization_id, "run_id": run.id},
        ))
        response = Response(body, status=status.HTTP_202_ACCEPTED)
        if replayed:
            response["Idempotent-Replay"] = "true"
        return response
