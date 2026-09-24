import shutil
from pathlib import Path
import pytest
import yaml
from django.contrib.auth import get_user_model
from django.core.management import call_command
from rest_framework.test import APIClient
from apps.applications.models import Application, ApplicationCategory
from apps.enterprise.models import Membership
from modules.catalog.models import ApplicationDraft
from ..models import BrandProfile, BrandProduct, BrandExample


@pytest.fixture
def ctx(db, settings):
    settings.ROOT_URLCONF = "app_center.brand_library.backend.tests.urls"
    owner = get_user_model().objects.create_user(username="brand-owner")
    user = get_user_model().objects.create_user(username="brand-user")
    other = get_user_model().objects.create_user(username="brand-other")
    org = owner.owned_organizations.get()
    for member in (user, other):
        Membership.objects.create(organization=org, user=member, role=Membership.Role.VIEWER)
    category = ApplicationCategory.objects.create(name="Brand tests", slug="brand-tests")
    app = Application.objects.create(organization=org, category=category, name="品牌资料库", slug="brand-library",
                                     created_by=owner, kind="custom", visibility="organization")
    client = APIClient()
    client.force_authenticate(user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    root = f"/api/v1/organizations/{org.id}/applications/{app.id}/brand-library/profiles"
    return dict(owner=owner, user=user, other=other, org=org, app=app, client=client, root=root)


def create(ctx, suffix="", **data):
    response = ctx["client"].post(ctx["root"] + suffix, {"name": "测试品牌", **data}, format="json")
    assert response.status_code == 201, response.data
    return response.data


def chat(ctx, definition=None):
    if definition is None:
        definition = {"default_config": {"brand_reference": {"enabled": True, "fields": {"tone": "voice.keywords", "audience": "positioning.audience"}}},
                      "guided_prompts": [{"key": "write", "prompt_template": "主题：{source}\n语气：{tone}\n受众：{audience}", "questions": [
                          {"key": "source", "label": "主题", "type": "text", "required": True},
                          {"key": "tone", "label": "语气", "type": "single_choice", "default_value": "normal", "options": [{"value": "normal", "label": "普通"}]},
                          {"key": "audience", "label": "受众", "type": "text", "default_value": "普通读者"}]}]}
    app = Application.objects.create(organization=ctx["org"], category=ctx["app"].category, name="写作", slug="brand-writer", created_by=ctx["owner"], kind="chat", visibility="organization")
    ApplicationDraft.objects.create(organization=ctx["org"], application=app, updated_by=ctx["owner"], content={"kind": "chat", **definition})
    return f"/api/v1/apps/{app.slug}/compose-prompt/"


def compose(ctx, url, profile, modules=None, **extra):
    data = {"prompt_id": "write", "answers": {"source": "新品"}, "brand_reference": {
        "profile_id": profile["id"], "modules": modules or ["positioning", "voice"], "product_ids": [], "example_ids": [],
    }}
    reference = extra.pop("reference", {})
    data["brand_reference"].update(reference)
    data.update(extra)
    return ctx["client"].post(url, data, format="json")


def test_crud_validation_and_server_owned_scope(ctx):
    client, root = ctx["client"], ctx["root"]
    for name in ("", " ", "x" * 201):
        assert client.post(root, {"name": name}, format="json").status_code == 400
    assert client.post(root, {"name": "n", "voice": {"unknown": "x"}}, format="json").status_code == 400
    assert client.post(root, {"name": "n", "visual": {"style": "x" * 4001}}, format="json").status_code == 400
    profile = create(ctx, owner=ctx["other"].id, application=999, organization="fake", positioning={"audience": "创业者"})
    record = BrandProfile.objects.get(pk=profile["id"])
    assert record.owner == ctx["user"] and record.application == ctx["app"] and record.organization == ctx["org"]
    detail = f"{root}/{profile['id']}"
    assert client.patch(detail, {"name": "修改", "voice": {"keywords": "克制"}}, format="json").status_code == 200
    assert client.get(detail).data["positioning"]["audience"] == "创业者"
    for kind, values in (("products", {"facts": ["100 克"], "source": "包装"}), ("examples", {"body": "范文正文", "source_url": "https://example.com"})):
        child = create(ctx, f"/{profile['id']}/{kind}", **values)
        child_url = f"{detail}/{kind}/{child['id']}"
        assert client.get(child_url).status_code == 200
        assert client.patch(child_url, {"name": "子项修改"}, format="json").status_code == 200
        assert client.get(f"{detail}/{kind}").data["count"] == 1
        assert client.delete(child_url).status_code == 204
        assert client.get(child_url).status_code == 404
    assert client.delete(detail).status_code == 204
    assert client.get(detail).status_code == 404


def test_search_pagination_and_private_access(ctx):
    item = create(ctx, name="目标品牌")
    create(ctx, f"/{item['id']}/products", facts=["秘密事实"])
    for i in range(20):
        create(ctx, name=f"其他品牌{i}")
    client, root = ctx["client"], ctx["root"]
    assert len(client.get(root).data["results"]) == 20
    assert len(client.get(root, {"page": 2}).data["results"]) == 1
    assert client.get(root, {"search": "目标"}).data["count"] == 1
    choices = f"/api/v1/organizations/{ctx['org'].id}/brand-library/profiles"
    assert client.get(choices).data["count"] == 21
    for other in (ctx["other"], ctx["owner"]):
        client.force_authenticate(other)
        assert client.get(root).data["count"] == 0
        assert client.get(choices).data["count"] == 0
        for suffix in (f"/{item['id']}", f"/{item['id']}/products"):
            assert client.get(root + suffix).status_code == 404
        assert client.patch(f"{root}/{item['id']}", {"name": "steal"}, format="json").status_code == 404
    assert APIClient().get(root).status_code in (401, 403)


def test_application_and_organization_access(ctx):
    profile = create(ctx)
    client, app = ctx["client"], ctx["app"]
    other_org = ctx["user"].owned_organizations.get()
    wrong = ctx["root"].replace(str(ctx["org"].id), str(other_org.id))
    assert client.get(wrong).status_code == 404
    app.is_active = False
    app.save(update_fields=["is_active"])
    assert client.get(ctx["root"]).status_code == 404
    app.is_active = True
    app.visibility = Application.Visibility.RESTRICTED
    app.save(update_fields=["is_active", "visibility"])
    assert client.get(f"{ctx['root']}/{profile['id']}").status_code == 404


def test_compose_inherits_without_mutating_default_or_explicit_answers(ctx):
    profile = create(ctx, voice={"keywords": "温暖克制"}, positioning={"audience": "创作者"}, visual={"style": "不应引用的视觉"})
    url = chat(ctx)
    response = compose(ctx, url, profile)
    assert response.status_code == 200, response.data
    assert "语气：使用品牌资料：温暖克制" in response.data["prompt"]
    assert "受众：使用品牌资料：创作者" in response.data["prompt"]
    assert "不应引用的视觉" not in response.data["prompt"]
    assert set(response.data["brand_reference"]["inherited_fields"]) == {"tone", "audience"}
    explicit = compose(ctx, url, profile, explicit_fields=["tone"], answers={"source": "新品", "tone": "normal"})
    assert "语气：普通" in explicit.data["prompt"]
    plain = ctx["client"].post(url, {"prompt_id": "write", "answers": {"source": "新品"}}, format="json")
    assert plain.data["prompt"] == "主题：新品\n语气：普通\n受众：普通读者"
    assert "brand_reference" not in plain.data
    assert ApplicationDraft.objects.get(application__slug="brand-writer").content["guided_prompts"][0]["questions"][1]["type"] == "single_choice"


def test_selected_items_only_and_invalid_references(ctx):
    profile = create(ctx, voice={"keywords": "自然"})
    product = create(ctx, f"/{profile['id']}/products", facts=["已核实的产品事实"])
    sample = create(ctx, f"/{profile['id']}/examples", body="优秀范文正文")
    create(ctx, f"/{profile['id']}/examples", body="不要引用此篇")
    another = create(ctx)
    foreign = create(ctx, f"/{another['id']}/products")
    url = chat(ctx)
    result = compose(ctx, url, profile, ["products", "examples"], reference={"product_ids": [product["id"]], "example_ids": [sample["id"]]})
    assert result.status_code == 200, result.data
    assert "已核实的产品事实" in result.data["prompt"] and "优秀范文正文" in result.data["prompt"]
    assert "不要引用此篇" not in result.data["prompt"]
    assert "不作为产品事实" in result.data["prompt"] and "保留原文" in result.data["prompt"]
    assert compose(ctx, url, profile, ["products"], reference={"product_ids": [foreign["id"]]}).status_code == 400
    assert compose(ctx, url, profile, ["voice"], reference={"product_ids": [product["id"]]}).status_code == 400
    assert compose(ctx, url, profile, reference={"modules": []}).status_code == 400
    assert compose(ctx, url, profile, ["visual"]).status_code == 400
    BrandExample.objects.filter(pk=sample["id"]).update(body="长" * 24000)
    assert compose(ctx, url, profile, ["examples"], reference={"example_ids": [sample["id"]]}).status_code == 400
    ctx["client"].force_authenticate(ctx["other"])
    assert compose(ctx, url, profile).status_code == 404
    ctx["client"].force_authenticate(ctx["user"])
    snapshot = result.data["prompt"]
    ctx["client"].delete(f"{ctx['root']}/{profile['id']}")
    assert not BrandProduct.objects.filter(pk=product["id"]).exists()
    assert compose(ctx, url, profile).status_code == 404
    assert "已核实的产品事实" in snapshot


@pytest.mark.parametrize("package,modules", [
    ("write_image_text_copy", ["positioning", "voice"]), ("write_short_video_copy", ["positioning", "voice"]),
    ("wechat_viral_article", ["positioning", "voice"]), ("wechat_viral_topics", ["positioning", "voice"]),
    ("html_cover_generator", ["positioning", "visual"]), ("article_html_illustrator", ["positioning", "visual"]),
    ("gzh_design", ["visual"]), ("markdown_to_html", ["visual"]), ("wechat_html_optimizer", ["visual"]), ("html_to_paged_cards", ["visual"]),
])
def test_real_application_composition(ctx, settings, package, modules):
    definition = yaml.safe_load((Path(settings.APP_CENTER_ROOT) / package / "application.yaml").read_text(encoding="utf-8"))["spec"]["definition"]
    config = definition["default_config"]["brand_reference"]
    assert config["default_modules"] == modules
    prompt = definition["guided_prompts"][0]
    assert set(config["fields"]) <= {q["key"] for q in prompt["questions"]}
    answers = {q["key"]: q.get("default_value") or (q["options"][0]["value"] if q.get("options") else "测试素材") for q in prompt["questions"]}
    profile = create(ctx, positioning={"audience": "创作者"}, voice={"keywords": "自然"}, visual={"primary_color": "#123456", "style": "简洁", "body_font": "宋体"})
    url = chat(ctx, definition)
    result = compose(ctx, url, profile, modules, prompt_id=prompt["key"], answers=answers)
    assert result.status_code == 200, result.data
    assert "本次品牌资料：测试品牌" in result.data["prompt"]


@pytest.mark.django_db
def test_install_is_idempotent(tmp_path, settings):
    shutil.copytree(settings.APP_CENTER_ROOT / "brand_library", tmp_path / "brand_library")
    settings.APP_CENTER_ROOT = tmp_path
    owner = get_user_model().objects.create_user(username="brand-install")
    org = owner.owned_organizations.get()
    for _ in range(2):
        call_command("sync_app_center", package_id="brand-library", organization_id=str(org.id))
    application = Application.objects.get(organization=org, slug="brand-library")
    assert application.is_active and application.draft.content["renderer_key"] == "brand-library"
    assert application.revisions.count() == 1 and application.deployments.count() == 1
