from datetime import timedelta

from django.conf import settings
from django.core import signing
from django.http import FileResponse, StreamingHttpResponse
from django.urls import reverse
from django.utils import timezone
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
from modules.tenancy.permissions import HasPathOrganizationRole

from .base import ProblemDetailsAPIView
from .pagination import RunArtifactCursorPagination, RunAttemptCursorPagination
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


class OrganizationRunView(ProblemDetailsAPIView):
    permission_classes = (IsAuthenticated, HasPathOrganizationRole)

    def get(self, request, organization_id, run_id):
        run = (
            Run.objects.for_organization(organization_id)
            .select_related("current_attempt")
            .filter(pk=run_id)
            .first()
        )
        if run is None:
            return _problem(
                request,
                status_code=status.HTTP_404_NOT_FOUND,
                code="run_not_found",
                title="Run not found",
                detail="The requested run does not exist or is not accessible.",
            )
        return Response(RunSerializer(run).data)


class OrganizationRunsView(ProblemDetailsAPIView):
    """Canonical Run history for every executor kind."""

    permission_classes = (IsAuthenticated, HasPathOrganizationRole)
    allowed_source_types = {
        "application", "agent", "conversation", "workflow", "evaluation"
    }

    def get(self, request, organization_id):
        runs = Run.objects.for_organization(organization_id).select_related(
            "current_attempt"
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
                        "workflow, or evaluation."
                    ),
                )
            runs = runs.filter(source_type=source_type)
        return Response(RunSerializer(runs[:100], many=True).data)


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
        if run is None:
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
        if not Run.objects.for_organization(organization_id).filter(pk=run_id).exists():
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

    def get(self, request, organization_id, run_id):
        if not Run.objects.for_organization(organization_id).filter(pk=run_id).exists():
            return _problem(
                request,
                status_code=status.HTTP_404_NOT_FOUND,
                code="run_not_found",
                title="Run not found",
                detail="The requested run does not exist or is not accessible.",
            )
        artifacts = RunArtifact.objects.for_organization(organization_id).filter(
            run_id=run_id
        )
        paginator = RunArtifactCursorPagination()
        page = paginator.paginate_queryset(artifacts, request, view=self)
        return paginator.get_paginated_response(
            RunArtifactSerializer(page, many=True).data
        )


class OrganizationRunArtifactAccessView(ProblemDetailsAPIView):
    permission_classes = (IsAuthenticated, HasPathOrganizationRole)

    def get(self, request, organization_id, run_id, artifact_id):
        artifact = RunArtifact.objects.for_organization(organization_id).filter(
            pk=artifact_id,
            run_id=run_id,
        ).first()
        if artifact is None:
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
        if snapshot is None:
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
        if run is None:
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

    def post(self, request, organization_id, run_id):
        serializer = SubmitRunCommandSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if not Run.objects.for_organization(organization_id).filter(pk=run_id).exists():
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
                environment=serializer.validated_data["environment"],
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
                environment=serializer.validated_data["environment"],
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
