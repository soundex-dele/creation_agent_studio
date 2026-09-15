"""Provision stable Agent and Skill references for bundled guided chat apps."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from django.conf import settings

from apps.agents.models import Agent, AgentCategory
from apps.applications.models import Skill
from modules.catalog.models import AgentDraft


def provision_chat_skill_definition(
    *,
    organization,
    definition,
    skill_slug: str,
    skill_description: str,
    agent_slug: str,
    agent_name: str,
    agent_description: str,
    agent_icon: str,
    system_prompt: str,
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
    category, _ = AgentCategory.objects.get_or_create(
        slug="design",
        defaults={
            "name": "视觉设计",
            "description": "图文排版和视觉设计",
            "icon": "🎨",
            "order": 3,
        },
    )
    agent, _ = Agent.objects.update_or_create(
        organization=organization,
        slug=agent_slug,
        defaults={
            "name": agent_name,
            "description": agent_description,
            "icon": agent_icon,
            "category": category,
            "created_by": owner,
            "is_public": True,
            "is_active": True,
        },
    )
    agent_content = {
        "system_prompt": system_prompt,
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
