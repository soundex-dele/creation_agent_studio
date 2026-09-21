from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from rest_framework.test import APIClient

from apps.applications.models import Application, Skill
from modules.catalog.guided_prompts import compose_guided_prompt


@pytest.mark.django_db
@pytest.mark.parametrize(("application_slug", "skill_slug"), [
    ("write-image-text-copy", "write-image-text-copy"),
    ("write-short-video-copy", "write-short-video-copy"),
    ("markdown-to-html", "baoyu-markdown-to-html"),
])
def test_skill_app_sync_exposes_guided_runtime_without_duplicate_revisions(
    application_slug, skill_slug, settings, tmp_path,
):
    settings.CODEX_SKILLS_DIRECTORY = str(tmp_path / "skills")
    owner = get_user_model().objects.create_user(username="guided-skill-owner")
    organization = owner.owned_organizations.get()

    for _ in range(2):
        call_command(
            "sync_app_center",
            package_id=application_slug,
            organization_id=str(organization.id),
        )

    application = Application.objects.get(
        organization=organization, slug=application_slug,
    )
    assert application.revisions.count() == 1
    assert application.deployments.count() == 1
    assert application.deployments.get().revision_id == application.revisions.get().id
    skill = Skill.objects.get(organization=organization, slug=skill_slug)
    assert Path(skill.source_uri) == tmp_path / "skills" / skill_slug / "SKILL.md"
    assert Path(skill.artifact_key) == tmp_path / "skills" / skill_slug

    client = APIClient()
    client.force_authenticate(owner)
    response = client.get(
        f"/api/v1/apps/{application_slug}/",
        HTTP_X_ORGANIZATION_ID=str(organization.id),
    )
    assert response.status_code == 200, response.data
    runtime = response.data
    assert runtime["kind"] == "chat"
    assert runtime["renderer_key"] == "chat"
    assert runtime["skill_bindings"][0]["skill_slug"] == skill_slug
    assert runtime["skill_bindings"][0]["mode"] == "required"
    assert runtime["agent_bindings"][0]["agent_slug"] == "content-creation-expert"
    prompt = next(
        prompt for prompt in runtime["guided_prompts"]
        if prompt["key"] == runtime["default_config"]["guided_entry_prompt_key"]
    )
    assert prompt["action"] == "preview"
    assert any(q["key"] == "source" and q["required"] for q in prompt["questions"])
    preview = compose_guided_prompt(
        prompt, {"source": "# 创作主题\n\n示例素材。"}, application_id=application.id,
    )
    assert "# 创作主题" in preview["prompt"]
    for question in prompt["questions"]:
        assert "{" + question["key"] + "}" in prompt["prompt_template"]
        assert "{" + question["key"] + "}" not in preview["prompt"]
        if question["type"] == "single_choice":
            assert question["default_value"] in {
                option["value"] for option in question["options"]
            }
