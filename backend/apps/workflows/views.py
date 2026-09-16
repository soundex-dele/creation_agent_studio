"""Workflow authoring with durable Run execution only."""
from copy import deepcopy

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Count, F, Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.agents.models import Agent
from apps.agents.runtime import get_agent_definition
from apps.applications.models import Application, Skill
from apps.applications.runtime_skills import resolve_runtime_skills, resolve_skill_adapter
from apps.enterprise.models import Membership
from apps.enterprise.permissions import OrganizationRolePermission, resolve_organization
from modules.catalog.models import ApplicationDeployment, DeploymentEnvironment
from modules.catalog.services import canonical_content_hash
from modules.execution.api.serializers import RunSerializer
from modules.execution.application.errors import IdempotencyKeyReused
from modules.execution.application.start_runs import start_workflow_run
from modules.execution.models import Run, RunEvent

from .models import Workflow
from .serializers import (
    WorkflowDetailSerializer,
    WorkflowListSerializer,
    WorkflowWriteSerializer,
)


def _chat_step_snapshot(step, organization):
    """Freeze an editable chat application into an executable workflow step.

    Chat applications are product-level conversation presets and can be used
    before publishing an Application revision. The durable workflow still
    receives an immutable value snapshot: application content, Agent content,
    and resolved runtime Skills are copied into the root Run definition.
    """

    application = step.application
    draft = getattr(application, "draft", None)
    if draft is None:
        raise ValueError(
            f"步骤“{step.name or application.name}”没有可用的应用草稿。"
        )
    content = deepcopy(draft.content)
    binding = next((
        item for item in content.get("agent_bindings", [])
        if item.get("is_default")
    ), None)
    if binding is None:
        raise ValueError(
            f"步骤“{step.name or application.name}”没有配置默认智能体。"
        )
    agent = Agent.objects.filter(
        Q(organization=organization) | Q(is_public=True),
        pk=binding.get("agent_id"),
        is_active=True,
    ).select_related("draft").first()
    if agent is None:
        raise ValueError(
            f"步骤“{step.name or application.name}”的默认智能体不可用。"
        )
    agent_definition = get_agent_definition(agent)
    if not agent_definition:
        raise ValueError(
            f"步骤“{step.name or application.name}”的默认智能体没有可用草稿或部署。"
        )
    agent_definition = {
        **agent_definition,
        **dict(binding.get("config_overrides") or {}),
    }

    required_skill_ids = {
        str(item.get("skill_id"))
        for item in content.get("skill_bindings", [])
        if item.get("skill_id") and item.get("mode") in ("required", "default")
    }
    skills = list(Skill.objects.filter(
        Q(organization=organization) | Q(visibility=Skill.Visibility.PUBLIC),
        pk__in=required_skill_ids,
        is_active=True,
    ))
    if len(skills) != len(required_skill_ids):
        raise ValueError(
            f"步骤“{step.name or application.name}”包含不可用的 Skill。"
        )
    adapter = resolve_skill_adapter(
        (agent_definition.get("model_config") or {}).get("adapter")
        or settings.AGENT_ENGINE_ADAPTER
    )
    runtime_skills = resolve_runtime_skills(
        [skill.slug for skill in skills], adapter
    )

    # Chat definitions use a product renderer key such as ``agent-chat``.
    # Workflow child Runs execute through the canonical Agent adapter.
    content.update({
        "executor_kind": "agent",
        "executor_key": "agent-completion",
        # These Skills have already been resolved from the active Agent adapter
        # and are supplied through runtime_input below. Leaving catalog
        # bindings here would incorrectly require Skill production revisions.
        "skill_bindings": [],
        "dependencies": {
            "agents": [{
                "agent_id": agent.id,
                "is_default": True,
                "definition": agent_definition,
            }],
            "skills": [],
        },
    })
    return {
        "application_revision_id": None,
        "application_content_hash": canonical_content_hash(draft.content),
        "application_draft_id": str(draft.id),
        "application_draft_version": draft.version,
        "content": content,
        "executor_kind": "agent",
        "executor_key": "agent-completion",
        "deployment_override": {},
        "runtime_input": {"skills": runtime_skills},
    }


def _backfill_manual_conversations(workflow, run, user):
    """Recover chat links for manual Runs created before explicit binding."""

    from apps.conversations.models import Conversation

    summary = dict(run.output_summary or {})
    conversations = dict(summary.get("conversations") or {})
    changed = False
    chat_steps = workflow.steps.select_related("application").filter(
        application__kind=Application.Kind.CHAT,
    )
    for step in chat_steps:
        if step.key in conversations:
            continue
        candidates = Conversation.objects.filter(
            organization=workflow.organization,
            user=user,
            chat_application_id=step.application_id,
        )
        if run.started_at:
            candidates = candidates.filter(created_at__gte=run.started_at)
        if run.finished_at:
            candidates = candidates.filter(created_at__lte=run.finished_at)
        conversation = candidates.order_by("-created_at").first()
        if conversation is not None:
            conversations[step.key] = str(conversation.id)
            changed = True
    if changed:
        summary["conversations"] = conversations
        Run.objects.filter(pk=run.pk).update(output_summary=summary)
        run.output_summary = summary
    return run


def _lock_manual_workflow(workflow):
    """Serialize manual Run creation on every supported database backend."""

    if connection.vendor == "sqlite":
        # select_for_update() is a no-op on SQLite. Acquire its single writer
        # lock before checking for an existing Run so concurrent page mounts
        # wait here instead of both reading an empty result and racing to write.
        Workflow.objects.filter(pk=workflow.pk).update(updated_at=F("updated_at"))
        return
    Workflow.objects.select_for_update().get(pk=workflow.pk)


class WorkflowViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, OrganizationRolePermission]

    def get_queryset(self):
        organization = resolve_organization(self.request)
        return Workflow.objects.filter(organization=organization).filter(
            Q(owner=self.request.user) | Q(is_public=True)
        ).annotate(step_count=Count("steps")).prefetch_related(
            "steps__application__draft",
        )

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return WorkflowWriteSerializer
        if self.action == "list":
            return WorkflowListSerializer
        return WorkflowDetailSerializer

    def perform_create(self, serializer):
        serializer.save(
            owner=self.request.user,
            organization=resolve_organization(self.request),
        )

    def perform_update(self, serializer):
        if serializer.instance.owner_id != self.request.user.id:
            raise PermissionDenied("只有工作流所有者可以编辑。")
        serializer.save()

    def perform_destroy(self, instance):
        membership = self.request.organization_membership
        if (
            instance.owner_id != self.request.user.id
            and membership.role not in (Membership.Role.OWNER, Membership.Role.ADMIN)
        ):
            raise PermissionDenied("无权删除该工作流。")
        instance.delete()

    @action(detail=True, methods=["post"], url_path="manual-session")
    def manual_session(self, request, pk=None):
        workflow = self.get_object()
        if workflow.execution_mode != Workflow.ExecutionMode.MANUAL:
            return Response(
                {"detail": "只有手动工作流可以创建手动执行记录。"},
                status=status.HTTP_409_CONFLICT,
            )

        run_id = request.data.get("run_id")
        action_name = request.data.get("action", "open")
        runs = Run.objects.for_organization(workflow.organization_id).filter(
            owner=request.user,
            executor_kind=Run.ExecutorKind.WORKFLOW,
            executor_key="workflow-manual",
            source_type="workflow",
            source_id=str(workflow.id),
        )

        if run_id:
            run = runs.filter(pk=run_id).first()
            if run is None:
                return Response({"detail": "手动执行记录不存在。"}, status=404)
        elif action_name == "open":
            run = runs.filter(status=Run.Status.RUNNING).order_by("-created_at").first()
        else:
            run = None

        if action_name == "complete":
            if run is None:
                return Response({"detail": "请提供要完成的手动执行记录。"}, status=400)
            if run.status == Run.Status.RUNNING:
                with transaction.atomic():
                    locked = Run.objects.select_for_update().get(pk=run.pk)
                    if locked.status == Run.Status.RUNNING:
                        now = timezone.now()
                        locked.status = Run.Status.SUCCEEDED
                        locked.finished_at = now
                        locked.version += 1
                        locked.next_event_sequence += 1
                        locked.save(update_fields=(
                            "status", "finished_at", "version", "next_event_sequence",
                        ))
                        RunEvent.objects.create(
                            organization=workflow.organization,
                            run=locked,
                            sequence=locked.next_event_sequence,
                            type="run.succeeded",
                            payload={"completed_at": now.isoformat(), "manual": True},
                        )
                run.refresh_from_db()
            return Response(RunSerializer(run).data)

        if action_name == "attach_conversation":
            if run is None:
                return Response({"detail": "请提供手动执行记录。"}, status=400)
            if run.status != Run.Status.RUNNING:
                return Response({"detail": "已结束的手动执行不能添加对话。"}, status=409)
            step_key = str(request.data.get("step_key") or "")
            conversation_id = request.data.get("conversation_id")
            step = workflow.steps.select_related("application").filter(
                key=step_key,
                application__kind=Application.Kind.CHAT,
            ).first()
            if step is None:
                return Response({"detail": "聊天应用步骤不存在。"}, status=400)

            from apps.conversations.models import Conversation
            conversation = Conversation.objects.filter(
                pk=conversation_id,
                organization=workflow.organization,
                user=request.user,
                chat_application_id=step.application_id,
            ).first()
            if conversation is None:
                return Response({"detail": "对话与当前工作流应用不匹配。"}, status=400)

            with transaction.atomic():
                locked = Run.objects.select_for_update().get(pk=run.pk)
                summary = dict(locked.output_summary or {})
                conversations = dict(summary.get("conversations") or {})
                conversations[step.key] = str(conversation.id)
                summary["conversations"] = conversations
                locked.output_summary = summary
                locked.version += 1
                locked.next_event_sequence += 1
                locked.save(update_fields=(
                    "output_summary", "version", "next_event_sequence",
                ))
                RunEvent.objects.create(
                    organization=workflow.organization,
                    run=locked,
                    sequence=locked.next_event_sequence,
                    type="workflow.manual.conversation_attached",
                    payload={
                        "step_key": step.key,
                        "conversation_id": str(conversation.id),
                    },
                )
            run.refresh_from_db()
            return Response(RunSerializer(run).data)

        if action_name != "open":
            return Response({"detail": "不支持的手动执行操作。"}, status=400)

        if run is None:
            steps = list(workflow.steps.select_related("application").order_by("order", "id"))
            if not steps:
                return Response({"detail": "工作流至少需要一个应用。"}, status=400)
            now = timezone.now()
            with transaction.atomic():
                # Serialize page mounts so development double-effects and quick
                # reopen actions reuse the same active manual execution.
                _lock_manual_workflow(workflow)
                run = runs.filter(status=Run.Status.RUNNING).order_by("-created_at").first()
                if run is None:
                    run = Run.objects.create(
                        organization=workflow.organization,
                        owner=request.user,
                        executor_kind=Run.ExecutorKind.WORKFLOW,
                        executor_key="workflow-manual",
                        source_type="workflow",
                        source_id=str(workflow.id),
                        status=Run.Status.RUNNING,
                        max_attempts=1,
                        retry_safe=False,
                        version=1,
                        next_event_sequence=1,
                        started_at=now,
                        definition_snapshot={
                            "workflow_id": str(workflow.id),
                            "workflow_name": workflow.name,
                            "execution_mode": Workflow.ExecutionMode.MANUAL,
                            "workflow_steps": [{
                                "id": str(step.id),
                                "key": step.key,
                                "name": step.name or step.application.name,
                                "application_id": step.application_id,
                            } for step in steps],
                        },
                        input={},
                    )
                    RunEvent.objects.create(
                        organization=workflow.organization,
                        run=run,
                        sequence=1,
                        type="run.started",
                        payload={"started_at": now.isoformat(), "manual": True},
                    )
        run = _backfill_manual_conversations(workflow, run, request.user)
        return Response(RunSerializer(run).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        workflow = self.get_object()
        if workflow.execution_mode != Workflow.ExecutionMode.AUTOMATIC:
            return Response(
                {"detail": "手动工作流需要从应用列表逐个打开执行，不能自动启动。"},
                status=status.HTTP_409_CONFLICT,
            )
        idempotency_key = (request.headers.get("Idempotency-Key") or "").strip()
        if not idempotency_key or len(idempotency_key) > 160:
            return Response(
                {"detail": "Idempotency-Key must contain between 1 and 160 characters."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        steps = list(workflow.steps.select_related(
            "application", "application__draft"
        ).order_by("order", "id"))
        if not steps:
            return Response({"detail": "工作流至少需要一个应用。"}, status=400)
        snapshots = []
        for step in steps:
            if step.application.kind == Application.Kind.CHAT:
                try:
                    runtime = _chat_step_snapshot(step, workflow.organization)
                except ValueError as exc:
                    return Response({"detail": str(exc)}, status=409)
            else:
                deployment = ApplicationDeployment.objects.for_organization(
                    workflow.organization_id
                ).select_related("revision").filter(
                    application=step.application,
                    environment=DeploymentEnvironment.PRODUCTION,
                ).first()
                if deployment is None:
                    return Response(
                        {"detail": f"步骤“{step.name or step.application.name}”没有 production 部署。"},
                        status=409,
                    )
                runtime = {
                    "application_revision_id": str(deployment.revision_id),
                    "application_content_hash": deployment.revision.content_hash,
                    "content": deployment.revision.content,
                    "executor_kind": deployment.revision.content.get("executor_kind"),
                    "executor_key": deployment.revision.content.get("executor_key"),
                    "deployment_override": deployment.config_override,
                    "runtime_input": {},
                }
            content = runtime["content"]
            kind = runtime["executor_kind"]
            key = runtime["executor_key"]
            if key not in settings.EXECUTION_CHILD_ADAPTERS.get(kind, {}):
                return Response(
                    {"detail": f"步骤执行器未注册：{kind}/{key}"},
                    status=422,
                )
            snapshots.append({
                "id": str(step.id),
                "key": step.key,
                "name": step.name or step.application.name,
                "depends_on": step.depends_on,
                "condition": step.condition,
                "max_attempts": step.max_attempts,
                "application_id": step.application_id,
                "application_revision_id": runtime["application_revision_id"],
                "application_content_hash": runtime["application_content_hash"],
                **({
                    "application_draft_id": runtime["application_draft_id"],
                    "application_draft_version": runtime["application_draft_version"],
                } if "application_draft_id" in runtime else {}),
                "executor_kind": kind,
                "executor_key": key,
                "content": content,
                "runtime_input": runtime["runtime_input"],
                "effective_config": {
                    **dict(content.get("default_config") or {}),
                    **dict(runtime["deployment_override"] or {}),
                    **dict(step.config or {}),
                },
            })
        try:
            with transaction.atomic():
                run, replayed = start_workflow_run(
                    organization=workflow.organization,
                    workflow_id=workflow.id,
                    workflow_name=workflow.name,
                    steps=snapshots,
                    actor=request.user,
                    input_data=request.data.get("input") or {},
                    priority=int(request.data.get("priority") or 0),
                    idempotency_key=idempotency_key,
                )
                if not replayed:
                    from apps.conversations.models import Conversation

                    frozen = dict(run.definition_snapshot or {})
                    frozen_steps = list(frozen.get("workflow_steps") or [])
                    for step, frozen_step in zip(steps, frozen_steps):
                        if step.application.kind != Application.Kind.CHAT:
                            continue
                        default_agent = next((
                            item for item in (
                                (frozen_step.get("content") or {})
                                .get("dependencies", {})
                                .get("agents", [])
                            )
                            if item.get("is_default")
                        ), None)
                        conversation = Conversation.objects.create(
                            user=request.user,
                            organization=workflow.organization,
                            title=f"{workflow.name} · {frozen_step['name']}",
                            agent_id=(default_agent or {}).get("agent_id"),
                            chat_application_id=step.application_id,
                            process_id=f"workflow:{frozen_step['key']}"[:64],
                        )
                        frozen_step["conversation_id"] = str(conversation.id)
                    frozen["workflow_steps"] = frozen_steps
                    Run.objects.filter(pk=run.pk).update(definition_snapshot=frozen)
                    run.definition_snapshot = frozen
        except IdempotencyKeyReused as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        body = RunSerializer(run).data
        body["organization_id"] = str(workflow.organization_id)
        response = Response(body, status=status.HTTP_202_ACCEPTED)
        if replayed:
            response["Idempotent-Replay"] = "true"
        return response
