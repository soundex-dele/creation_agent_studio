from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command

from apps.agents.models import Agent
from apps.applications.models import Application, Skill
from modules.catalog.models import AgentDraft


CHAT_SKILL_APPS = {
    "gzh-design": {
        "skill_slug": "gzh-design",
    },
    "wechat-html-optimizer": {
        "skill_slug": "optimize-wechat-html",
    },
    "article-html-illustrator": {
        "skill_slug": "baoyu-article-html-illustrator",
    },
    "html-cover-generator": {
        "skill_slug": "baoyu-html-cover",
    },
    "wechat-viral-article": {
        "skill_slug": "wechat-viral-article",
    },
    "wechat-viral-topics": {
        "skill_slug": "wechat-viral-article",
    },
    "tool-share-topic-expert": {
        "skill_slug": "tool-share-topic-planner",
        "agent_config_overrides": {"model_config": {"adapter": "codex"}},
    },
}


@pytest.mark.django_db
def test_sync_installs_all_packages_and_activates_deployments():
    owner = get_user_model().objects.create_user(username="app-center-sync-owner")
    organization = owner.owned_organizations.get()

    call_command("sync_app_center", organization_id=str(organization.id))
    call_command("sync_app_center", organization_id=str(organization.id))

    applications = Application.objects.filter(organization=organization)
    content_agent = Agent.objects.get(
        organization=organization,
        slug="content-creation-expert",
    )
    assert set(applications.values_list("slug", flat=True)) >= {
        "article-html-illustrator", "case-library",
        "creation-master", "gzh-design", "html-cover-generator",
        "wechat-html-optimizer", "wechat-viral-article",
        "wechat-viral-topics", "tool-share-topic-expert",
    }
    for application in applications.filter(
        slug__in=(
            "article-html-illustrator", "case-library",
            "creation-master", "gzh-design", "html-cover-generator",
            "wechat-html-optimizer", "wechat-viral-article",
            "wechat-viral-topics", "tool-share-topic-expert",
        )
    ):
        assert application.revisions.count() == 1
        assert application.deployments.count() == 1

    assert not applications.filter(slug="newmedia-workbench").exists()
    assert not applications.filter(slug="batch-transcribe").exists()
    assert not applications.filter(slug="contacts").exists()

    for application_slug, expected in CHAT_SKILL_APPS.items():
        application = applications.get(slug=application_slug)
        skill = Skill.objects.get(
            organization=organization,
            slug=expected["skill_slug"],
        )
        definition = application.draft.content
        agent = Agent.objects.get(
            id=definition["agent_bindings"][0]["agent_id"],
            slug="content-creation-expert",
        )
        assert agent == content_agent

        assert application.kind == Application.Kind.CHAT
        assert application.chat_application.application_id == application.id
        assert definition["kind"] == "chat"
        assert definition["renderer_key"] == "chat"
        assert definition["guided_prompts"][0]["action"] == "preview"
        assert definition["agent_bindings"] == [{
            "agent_id": agent.id,
            "label": agent.name,
            "is_default": True,
            "config_overrides": expected.get("agent_config_overrides", {}),
            "order": 0,
        }]
        assert definition["skill_bindings"] == [{
            "skill_id": str(skill.id),
            "mode": "required",
            "config": {},
            "order": 0,
        }]
        assert "pending-" not in str(definition)

        if application_slug == "tool-share-topic-expert":
            assert Path(skill.source_uri) == (
                Path(settings.CODEX_SKILLS_DIRECTORY).expanduser().resolve()
                / "tool-share-topic-planner"
                / "SKILL.md"
            )

    agent_draft = AgentDraft.objects.get(agent=content_agent)
    assert "必须使用应用绑定的必需 Skill" in agent_draft.content["system_prompt"]
    assert Agent.objects.filter(
        organization=organization,
        slug="content-creation-expert",
    ).count() == 1
    assert not Agent.objects.filter(
        organization=organization,
        slug="tool-share-topic-expert",
    ).exists()

    assert not Agent.objects.filter(
        organization=organization,
        slug__in=(
            "wechat-html-optimizer-assistant",
            "article-html-illustrator-assistant",
            "html-cover-designer-assistant",
        ),
    ).exists()
