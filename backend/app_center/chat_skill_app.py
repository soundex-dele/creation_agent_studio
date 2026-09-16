"""Provision Skill references for bundled guided chat apps."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from django.conf import settings

from apps.agents.models import Agent
from apps.applications.models import Skill


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
    agent = Agent.objects.filter(
        organization=organization,
        slug="general",
        is_active=True,
    ).first() or Agent.objects.filter(
        slug="general",
        is_public=True,
        is_active=True,
    ).order_by("id").first()
    if agent is None:
        raise RuntimeError("The default general assistant is not available.")

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
