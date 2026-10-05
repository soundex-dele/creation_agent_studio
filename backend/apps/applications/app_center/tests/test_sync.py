from copy import deepcopy
from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command

from apps.agents.models import Agent
from apps.applications.models import Application, ApplicationAccessGrant, Skill
from apps.applications.app_center.discovery import discover_packages
from apps.enterprise.models import Membership
from core.resource_access import accessible_resources
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
        assert application.visibility == Application.Visibility.ORGANIZATION
        assert application.is_public and application.is_active
        assert application.created_by == owner

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


@pytest.mark.django_db
@pytest.mark.parametrize("visibility", Application.Visibility.values)
def test_sync_preserves_access_and_disabled_state_across_package_updates(monkeypatch, visibility):
    owner = get_user_model().objects.create_user(username="sync-permissions-owner")
    organization = owner.owned_organizations.get()
    creator = get_user_model().objects.create_user(username="sync-permissions-creator")
    member = get_user_model().objects.create_user(username="sync-permissions-member")
    for user in (creator, member):
        Membership.objects.create(organization=organization, user=user, role=Membership.Role.DEVELOPER)
    packages, _ = discover_packages(settings.APP_CENTER_ROOT, strict=True)
    package = deepcopy(next(p for p in packages if p.manifest.metadata.id == "kitchen-assistant"))
    monkeypatch.setattr(
        "apps.applications.management.commands.sync_app_center.discover_packages",
        lambda *args, **kwargs: ([package], []),
    )
    call_command("sync_app_center", organization_id=str(organization.id))
    application = Application.objects.get(organization=organization, slug="kitchen-assistant")
    assert application.visibility == Application.Visibility.ORGANIZATION
    assert application.is_active and application.is_public
    assert application.created_by == owner
    application.visibility = visibility
    application.is_active = False
    application.is_public = False
    application.created_by = creator
    application.name = "旧应用名称"
    application.save()
    grant = ApplicationAccessGrant.objects.create(
        application=application, user=member, role=ApplicationAccessGrant.Role.VIEWER,
    )
    grants_before = list(application.access_grants.values())
    access_before = {
        (user.pk, operation): accessible_resources(
            Application.objects.filter(pk=application.pk), user, operation=operation,
        ).exists()
        for user in (creator, member) for operation in ("discover", "run", "edit")
    }
    old_revision_id = application.deployments.get().revision_id
    # Publish a changed definition, then repeat sync to cover both update paths.
    package.manifest.spec.definition["default_config"]["sync_test_version"] = 2
    for _ in range(2):
        call_command("sync_app_center", organization_id=str(organization.id))
        application.refresh_from_db()
        assert application.visibility == visibility
        assert not application.is_active and not application.is_public
        assert application.created_by == creator
        assert list(application.access_grants.values()) == grants_before
        grant.refresh_from_db()
        assert grant.role == ApplicationAccessGrant.Role.VIEWER
        for (user_id, operation), expected in access_before.items():
            user = creator if user_id == creator.pk else member
            assert accessible_resources(
                Application.objects.filter(pk=application.pk), user, operation=operation,
            ).exists() == expected
        assert application.name == package.manifest.metadata.name
        assert application.draft.content == package.manifest.spec.definition
        assert application.deployments.get().revision_id != old_revision_id
