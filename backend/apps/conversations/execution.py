"""Shared durable conversation execution for web and messaging channels."""
import logging
import time
from django.conf import settings
from django.core.files.storage import default_storage
from django.db import OperationalError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError
from apps.agents.models import Agent
from apps.agents.runtime import get_agent_definition
from apps.applications.models import Application, Skill
from apps.applications.runtime_skills import resolve_runtime_skills, resolve_skill_adapter
from apps.applications.serializers import application_definition
from apps.projects.services.workspace_paths import conversation_working_directory
from modules.execution.application.start_runs import (
    CREATE_AGENT_RUN_OPERATION, CREATE_SUPERVISOR_RUN_OPERATION,
    start_agent_run, start_supervisor_run,
)
from modules.execution.models import IdempotencyRecord, Run
from core.resource_access import accessible_resources, can_access_resource
from .models import Conversation, ConversationSkillBinding, Message
from .services import persist_message_attachments

GENERAL_AGENT_SLUG = "general"
AGENT_SELECTION_UNSET = object()
logger = logging.getLogger(__name__)


class ConversationRunActive(Exception):
    pass


def resolve_agent(agent_id, organization, user, *, use_default=False):
    visible = accessible_resources(
        Agent.objects.filter(
            Q(organization=organization) | Q(organization__isnull=True),
            is_active=True,
        ),
        user,
        operation="run",
    )
    if agent_id is None:
        if use_default:
            return get_object_or_404(visible, slug=GENERAL_AGENT_SLUG)
        return None
    selected = visible.filter(pk=agent_id).first()
    if selected is None:
        raise ValidationError({"agent_id": "该智能体不存在或当前用户无权使用。"})
    return selected


def ensure_supervisor_access(agent, user):
    if not agent or agent.kind != Agent.Kind.SUPERVISOR:
        return
    if not hasattr(agent, 'supervisor_profile'):
        raise ValidationError({'agent_id': 'AI 分身配置不完整。'})
    if not can_access_resource(agent, user, operation="run"):
        raise ValidationError({'agent_id': '当前账号无权运行该 AI 分身。'})


def resolve_conversation_agent(conversation, requested_agent_id):
    """Resolve the runtime Agent and the optional persisted composer selection."""

    if requested_agent_id is AGENT_SELECTION_UNSET:
        if conversation.agent_id:
            selected = accessible_resources(
                Agent.objects.filter(
                    Q(organization=conversation.organization)
                    | Q(organization__isnull=True),
                    pk=conversation.agent_id,
                    is_active=True,
                ),
                conversation.user,
                operation="run",
            ).first()
            if selected is None:
                raise ValidationError({
                    "agent_id": "该智能体不存在或当前用户无权使用。",
                })
            return selected, conversation.agent
        return resolve_agent(
            None, conversation.organization, conversation.user, use_default=True), None
    if conversation.agent_locked:
        requested_id = None if requested_agent_id is None else int(requested_agent_id)
        if requested_id != conversation.agent_id:
            raise ValidationError({"agent_id": "该辅导会话已固定老师，请新建会话后更换。"})
    if requested_agent_id is None:
        return (
            resolve_agent(
                None, conversation.organization, conversation.user, use_default=True),
            None,
        )
    selected = accessible_resources(
        Agent.objects.filter(
            Q(organization=conversation.organization) | Q(organization__isnull=True),
            is_active=True,
            pk=requested_agent_id,
        ),
        conversation.user,
        operation="run",
    ).first()
    if selected is None:
        raise ValidationError({"agent_id": "该智能体不存在或当前用户无权使用。"})
    if conversation.application_id:
        allowed = {
            item.get("agent_id")
            for item in application_definition(conversation.application).get(
                "agent_bindings", []
            )
        }
        if selected.id not in allowed:
            raise ValidationError({"agent_id": "该智能体不属于当前聊天应用。"})
    return selected, selected


def validate_requested_skill_names(conversation, requested_skill_names):
    """Validate one-turn Skill names against an application's selection policy."""

    requested = {str(value) for value in requested_skill_names}
    if not requested:
        return
    if conversation.application_id:
        definition = application_definition(conversation.application)
        profile = definition.get("chat_profile") or {}
        if not profile.get("allow_skill_selection", True):
            raise ValidationError({"skill_names": "当前聊天应用不允许选择 Skill。"})
        if not profile.get("allow_extra_skills", False):
            allowed_ids = {
                item.get("skill_id")
                for item in definition.get("skill_bindings", [])
                if item.get("skill_id")
            }
            allowed = set(Skill.objects.filter(
                id__in=allowed_ids,
                is_active=True,
            ).values_list("slug", flat=True))
            if not requested.issubset(allowed):
                raise ValidationError({"skill_names": "包含应用未授权的 Skill。"})


def application_agent_overrides(conversation, agent):
    if not conversation.application_id:
        return {}
    definition = application_definition(conversation.application)
    binding = next((
        item for item in definition.get("agent_bindings", [])
        if item.get("agent_id") == agent.id
    ), None)
    return dict((binding or {}).get("config_overrides") or {})


def create_conversation_run(
    actor,
    conversation,
    message,
    idempotency_key,
    requested_agent_id=AGENT_SELECTION_UNSET,
    requested_skill_names=(),
    image_specs=(),
    request_id="",
    max_retries=6,
    permission_mode="default",
    collaboration_mode="default",
):
    for retry_no in range(max_retries):
        saved_storage_names = []
        try:
            return _create_run_once(
                actor,
                conversation,
                message,
                idempotency_key,
                requested_agent_id=requested_agent_id,
                requested_skill_names=requested_skill_names,
                image_specs=image_specs,
                saved_storage_names=saved_storage_names,
                request_id=request_id,
                permission_mode=permission_mode,
                collaboration_mode=collaboration_mode,
            )
        except OperationalError as exc:
            for storage_name in saved_storage_names:
                default_storage.delete(storage_name)
            is_busy = "locked" in str(exc).lower() or "busy" in str(exc).lower()
            if not is_busy or retry_no + 1 >= max_retries:
                raise
            time.sleep(0.02 * (2**retry_no))
        except Exception:
            for storage_name in saved_storage_names:
                default_storage.delete(storage_name)
            raise

    raise RuntimeError("Unable to create conversation run after retries")

@transaction.atomic
def _create_run_once(
    actor,
    conversation,
    message,
    idempotency_key,
    requested_agent_id=AGENT_SELECTION_UNSET,
    requested_skill_names=(),
    image_specs=(),
    saved_storage_names=None,
    request_id="",
    permission_mode="default",
    collaboration_mode="default",
):
    if saved_storage_names is None:
        saved_storage_names = []
    conversation = Conversation.objects.select_for_update().get(
        pk=conversation.pk,
        organization_id=conversation.organization_id,
        user_id=actor.id,
    )
    organization = conversation.organization
    if conversation.application_id and not accessible_resources(
        Application.objects.filter(
            Q(organization=organization) | Q(organization__isnull=True),
            pk=conversation.application_id,
            is_active=True,
        ),
        actor,
        operation="run",
    ).exists():
        raise ValidationError({"application_id": "当前用户已无权使用该应用。"})
    agent, selected_agent = resolve_conversation_agent(
        conversation, requested_agent_id)
    selection_changed = conversation.agent_id != getattr(
        selected_agent, "id", None)
    ensure_supervisor_access(agent, actor)
    operation = (
        CREATE_SUPERVISOR_RUN_OPERATION
        if agent.kind == Agent.Kind.SUPERVISOR
        else CREATE_AGENT_RUN_OPERATION
    )
    is_idempotent_replay = IdempotencyRecord.objects.for_organization(
        organization.id
    ).filter(
        actor=actor,
        operation=operation,
        key=idempotency_key,
    ).exists()
    if not is_idempotent_replay and Run.objects.for_organization(
        organization.id
    ).filter(
        Q(source_type="conversation", source_id=str(conversation.id))
        | Q(
            source_type="supervisor",
            definition_snapshot__conversation_id=str(conversation.id),
        )
        | Q(
            source_type="supervisor_task",
            definition_snapshot__conversation_id=str(conversation.id),
        ),
        status__in=(
            Run.Status.QUEUED,
            Run.Status.RUNNING,
            Run.Status.WAITING_INPUT,
            Run.Status.WAITING_CHILDREN,
            Run.Status.CANCELLING,
        ),
    ).exists():
        raise ConversationRunActive("当前对话仍在执行，请等待本轮完成后再发送。")
    history = list(
        conversation.messages.order_by("created_at", "id").values("role", "content")
    )[-99:]
    history.append({"role": "user", "content": message})
    working_directory = conversation_working_directory(conversation)
    validate_requested_skill_names(conversation, requested_skill_names)
    if agent.kind == Agent.Kind.SUPERVISOR:
        if collaboration_mode == "plan" or permission_mode == "allow_all":
            raise ValidationError({"collaboration_mode": "该执行设置仅支持 Codex 智能体。"})
        if image_specs:
            raise ValidationError({
                "images": "主管智能体（GraphFlow）暂不支持图片，请仅发送文本。",
            })
        run, replayed = start_supervisor_run(
            organization_id=organization.id,
            supervisor_id=agent.id,
            actor=actor,
            goal=message,
            context={
                "messages": history[:-1],
                "working_directory": working_directory,
            },
            conversation_id=conversation.id,
            idempotency_key=idempotency_key,
        )
        if not replayed:
            if not conversation.title:
                conversation.title = message[:50]
            conversation.save(update_fields=["title", "updated_at"])
            Message.objects.create(
                conversation=conversation,
                run=run,
                role="user",
                content=message,
                metadata={"supervisor": True},
            )
        return run, replayed

    definition = get_agent_definition(agent)
    definition_overrides = application_agent_overrides(conversation, agent)
    effective_definition = {**definition, **definition_overrides}
    adapter = resolve_skill_adapter(
        (effective_definition.get("model_config") or {}).get("adapter")
        or settings.AGENT_ENGINE_ADAPTER
    )
    if permission_mode == "allow_all":
        from apps.enterprise.services import execution_governance_snapshot
        if execution_governance_snapshot(organization).get("require_tool_approval"):
            raise ValidationError({"permission_mode": "组织要求工具审批，无法开启完全控制。"})
    if adapter != "codex" and (collaboration_mode == "plan" or permission_mode == "allow_all"):
        raise ValidationError({"collaboration_mode": "该执行设置仅支持 Codex 智能体。"})
    if image_specs and adapter != "codex":
        raise ValidationError({
            "images": "当前 GraphFlow 智能体不支持图片，请改用 Codex 智能体。",
        })
    effective_skill_names = [
        binding.skill.slug
        for binding in conversation.skill_bindings.select_related("skill").filter(
            enabled=True,
            skill__is_active=True,
        ).exclude(source__in=(
            ConversationSkillBinding.Source.AGENT_REQUIRED,
            ConversationSkillBinding.Source.AGENT_DEFAULT,
        ))
    ]
    effective_skill_names.extend(requested_skill_names)
    try:
        skill_inputs = resolve_runtime_skills(effective_skill_names, adapter)
    except ValueError as exc:
        raise ValidationError({"skill_names": str(exc)}) from exc
    runtime_attachments = []
    if not is_idempotent_replay:
        user_message = Message.objects.create(
            conversation=conversation,
            role="user",
            content=message,
            metadata={
                "run_request_id": request_id,
                "composer": {
                    "permission_mode": permission_mode,
                    "collaboration_mode": collaboration_mode,
                    "agent_id": getattr(selected_agent, "id", None),
                    "skill_names": sorted(
                        str(value) for value in requested_skill_names),
                    "skills": [item["name"] for item in skill_inputs],
                },
            },
        )
        runtime_attachments = persist_message_attachments(
            message=user_message,
            conversation=conversation,
            specs=image_specs,
            saved_storage_names=saved_storage_names,
        )

    run, replayed = start_agent_run(
        organization_id=organization.id,
        agent_id=agent.id,
        actor=actor,
        input_data={
            "permission_mode": permission_mode,
            "collaboration_mode": collaboration_mode,
            "message": message,
            "messages": history,
            "working_directory": working_directory,
            "skills": skill_inputs,
            "attachments": runtime_attachments,
            # Agent selection changes the instructions, not the conversation
            # identity. Supplying the persisted thread makes Codex use
            # thread/resume with the newly selected Agent's system prompt.
            "agent_thread": {
                "provider": conversation.agent_thread_provider,
                "id": conversation.agent_thread_id,
            } if conversation.agent_thread_id else {},
        },
        idempotency_key=idempotency_key,
        idempotency_input_data={
            "permission_mode": permission_mode,
            "collaboration_mode": collaboration_mode,
            "message": message,
            "skill_names": sorted(
                str(value) for value in requested_skill_names),
            "images": [
                {
                    "name": spec["original_name"],
                    "content_type": spec["content_type"],
                    "byte_size": spec["byte_size"],
                    "checksum_sha256": spec["checksum_sha256"],
                }
                for spec in image_specs
            ],
        },
        source_type="conversation",
        source_id=conversation.id,
        allow_draft=True,
        definition_overrides=(
            {"system_prompt": ""}
            if selected_agent is None
            else definition_overrides or None
        ),
    )
    if not replayed:
        update_fields = ["title", "updated_at"]
        if selection_changed:
            conversation.agent = selected_agent
            update_fields.append("agent")
        if not conversation.title:
            conversation.title = (
                message[:50]
                or (
                    str(image_specs[0]["original_name"])[:50]
                    if image_specs else "新对话"
                )
            )
        conversation.save(update_fields=update_fields)
    return run, replayed
