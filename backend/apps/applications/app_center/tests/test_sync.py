import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

from apps.agents.models import Agent
from apps.applications.models import Application, Skill


CHAT_SKILL_APPS = {
    "wechat-html-optimizer": {
        "agent_slug": "wechat-html-optimizer-assistant",
        "skill_slug": "optimize-wechat-html",
        "system_prompt_fragment": "公众号 HTML 优化助手",
    },
    "article-html-illustrator": {
        "agent_slug": "article-html-illustrator-assistant",
        "skill_slug": "baoyu-article-html-illustrator",
        "system_prompt_fragment": "文章 HTML 配图助手",
    },
    "html-cover-generator": {
        "agent_slug": "html-cover-designer-assistant",
        "skill_slug": "baoyu-html-cover",
        "system_prompt_fragment": "HTML 封面设计助手",
    },
}


@pytest.mark.django_db
def test_sync_installs_all_packages_and_only_deploys_development():
    owner = get_user_model().objects.create_user(username="app-center-sync-owner")
    organization = owner.owned_organizations.get()

    call_command("sync_app_center", organization_id=str(organization.id))
    call_command("sync_app_center", organization_id=str(organization.id))

    applications = Application.objects.filter(organization=organization)
    assert set(applications.values_list("slug", flat=True)) >= {
        "article-html-illustrator", "batch-transcribe", "case-library", "contacts",
        "creation-master", "html-cover-generator", "wechat-html-optimizer",
    }
    for application in applications.filter(
        slug__in=(
            "article-html-illustrator", "batch-transcribe", "case-library", "contacts",
            "creation-master", "html-cover-generator", "wechat-html-optimizer",
        )
    ):
        assert application.revisions.count() == 1
        assert application.deployments.filter(environment="development").count() == 1
        assert not application.deployments.filter(environment="production").exists()

    for application_slug, expected in CHAT_SKILL_APPS.items():
        application = applications.get(slug=application_slug)
        agent = Agent.objects.get(
            organization=organization,
            slug=expected["agent_slug"],
        )
        skill = Skill.objects.get(
            organization=organization,
            slug=expected["skill_slug"],
        )
        definition = application.draft.content

        assert application.kind == Application.Kind.CHAT
        assert application.chat_application.application_id == application.id
        assert definition["kind"] == "chat"
        assert definition["renderer_key"] == "chat"
        assert definition["guided_prompts"][0]["action"] == "preview"
        assert definition["agent_bindings"] == [{
            "agent_id": agent.id,
            "label": agent.name,
            "is_default": True,
            "config_overrides": {},
            "order": 0,
        }]
        assert definition["skill_bindings"] == [{
            "skill_id": str(skill.id),
            "mode": "required",
            "config": {},
            "order": 0,
        }]
        assert expected["system_prompt_fragment"] in agent.draft.content["system_prompt"]
        assert "pending-" not in str(definition)
