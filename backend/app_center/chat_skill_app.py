"""Provision Skill references for bundled guided chat apps."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from django.conf import settings

from apps.agents.models import Agent, AgentCategory
from apps.applications.models import Skill
from modules.catalog.models import AgentDraft


CONTENT_CREATION_AGENT_SLUG = "content-creation-expert"
CONTENT_CREATION_SYSTEM_PROMPT = """你是内容创作专家，负责内容策划、写作、编辑、视觉表达与公众号排版。

执行应用任务时，必须使用应用绑定的必需 Skill，并严格遵循该 Skill 的工作流、校验步骤、输出格式和安全边界。用户通过应用表单确认的设置视为已确认，不重复询问；只有 Skill 明确要求确认或缺少无法合理推断的必需信息时，才提出最少量问题。不得虚构事实、数据或校验结果。交付时优先给出可直接使用的产物，并清楚说明文件路径、关键决策和仍需人工确认的事项。"""


def provision_content_creation_agent(organization):
    owner = organization.owner
    category = AgentCategory.objects.filter(slug="content-creation").first()
    if category is None:
        category = AgentCategory.objects.filter(name="内容创作").first()
    if category is None:
        category = AgentCategory.objects.create(
            slug="content-creation",
            name="内容创作",
            description="写作、编辑、视觉设计与内容排版",
            icon="✍️",
            order=1,
        )
    agent, _ = Agent.objects.update_or_create(
        organization=organization,
        slug=CONTENT_CREATION_AGENT_SLUG,
        defaults={
            "name": "内容创作专家",
            "description": "使用专业 Skill 完成写作、编辑、视觉设计与公众号排版。",
            "icon": "✍️",
            "category": category,
            "created_by": owner,
            "is_public": True,
            "is_active": True,
        },
    )
    agent_content = {
        "system_prompt": CONTENT_CREATION_SYSTEM_PROMPT,
        "model_config": {},
        "tool_config": [],
        "knowledge_config": [],
        "guardrail_config": {},
        "workflow_config": {},
        "skill_bindings": [],
    }
    draft, created = AgentDraft.objects.get_or_create(
        organization=organization,
        agent=agent,
        defaults={"updated_by": owner, "content": agent_content},
    )
    if not created and draft.content != agent_content:
        draft.content = agent_content
        draft.version += 1
        draft.updated_by = owner
        draft.save(update_fields=("content", "version", "updated_by", "updated_at"))
    return agent


def provision_chat_skill_definition(
    *,
    organization,
    definition,
    skill_slug: str,
    skill_description: str,
):
    owner = organization.owner
    skill_root = Path(settings.CODEX_SKILLS_DIRECTORY).expanduser().resolve(strict=False)
    skill_dir = skill_root / skill_slug
    skill_file = skill_dir / "SKILL.md"
    skill, _ = Skill.objects.update_or_create(
        organization=organization,
        slug=skill_slug,
        defaults={
            "name": skill_slug,
            "description": skill_description,
            "visibility": Skill.Visibility.ORGANIZATION,
            "owner": owner,
            "source_type": Skill.SourceType.BUNDLED,
            "source_uri": str(skill_file),
            "artifact_key": str(skill_dir),
            "manifest": {"entrypoint": "SKILL.md"},
            "is_active": True,
        },
    )
    agent = provision_content_creation_agent(organization)

    resolved = deepcopy(definition)
    resolved["agent_bindings"] = [{
        "agent_id": agent.id,
        "label": agent.name,
        "is_default": True,
        "config_overrides": {},
        "order": 0,
    }]
    resolved["skill_bindings"] = [{
        "skill_id": str(skill.id),
        "mode": "required",
        "config": {},
        "order": 0,
    }]
    return resolved
