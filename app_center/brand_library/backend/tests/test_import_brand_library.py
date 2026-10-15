import io
import json
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.applications.models import Application, ApplicationCategory
from apps.enterprise.models import Membership
from ..models import BrandExample, BrandProduct, BrandProfile


@pytest.fixture
def destination(db):
    user = get_user_model().objects.create_user(username="import-owner")
    org = user.owned_organizations.get()
    category = ApplicationCategory.objects.create(name="Import tests", slug="import-tests")
    app = Application.objects.create(
        organization=org, category=category, name="品牌资料库", slug="brand-library",
        created_by=user, kind="custom", visibility="organization",
    )
    return user, org, app


@pytest.fixture
def bundle(tmp_path):
    files = {
        "import-manifest.json": {"version": 1, "profile": "profile.json", "products": ["product.json"], "examples": ["example.json"]},
        "profile.json": {"name": "智能体AI工坊", "voice": {"keywords": "清晰务实"}},
        "product.json": {"name": "工具", "facts": ["已核实的功能"]},
        "example.json": {"name": "真实范文", "body": "测试用范文正文"},
    }
    for filename, data in files.items():
        (tmp_path / filename).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return tmp_path / "import-manifest.json"


def run_import(destination, bundle, **options):
    user, org, _ = destination
    output = io.StringIO()
    kwargs = {"username": user.username, "organization": str(org.pk), "bundle": bundle, **options}
    call_command("import_brand_library", stdout=output, **kwargs)
    return json.loads(output.getvalue())


def test_import_repeats_without_duplicates_or_timestamp_changes(destination, bundle):
    result = run_import(destination, bundle)
    assert result["status"] == "committed_and_verified"
    assert [entry["action"] for entry in result["entries"]] == ["create"] * 3
    user, org, app = destination
    profile = BrandProfile.objects.get()
    assert (profile.owner, profile.organization, profile.application) == (user, org, app)
    assert BrandProduct.objects.get().profile == profile
    assert BrandExample.objects.get().profile == profile
    updated = profile.updated_at
    repeated = run_import(destination, bundle)
    assert [entry["action"] for entry in repeated["entries"]] == ["skip"] * 3
    assert [entry["id"] for entry in result["entries"]] == [entry["id"] for entry in repeated["entries"]]
    profile.refresh_from_db()
    assert profile.updated_at == updated


def test_dry_run_validates_without_writing(destination, bundle):
    result = run_import(destination, bundle, dry_run=True)
    assert result["status"] == "preview"
    assert [entry["action"] for entry in result["entries"]] == ["create"] * 3
    assert not BrandProfile.objects.exists()
    assert not BrandProduct.objects.exists()
    assert not BrandExample.objects.exists()


def test_conflict_stops_entire_import_and_explicit_update_preserves_extra_items(destination, bundle):
    run_import(destination, bundle)
    user, org, app = destination
    profile = BrandProfile.objects.get()
    extra = BrandProduct.objects.create(profile=profile, owner=user, organization=org, application=app, name="不在导入包中的产品")
    product_file = bundle.parent / "product.json"
    product_file.write_text(json.dumps({"name": "工具", "facts": ["更新后的事实"]}), encoding="utf-8")
    BrandExample.objects.all().delete()
    preview = run_import(destination, bundle, dry_run=True)
    assert preview["conflicts"]
    with pytest.raises(CommandError, match="nothing imported"):
        run_import(destination, bundle)
    assert BrandProduct.objects.get(name="工具").facts == ["已核实的功能"]
    assert not BrandExample.objects.exists()
    result = run_import(destination, bundle, on_conflict="update")
    assert [entry["action"] for entry in result["entries"]] == ["skip", "update", "create"]
    assert BrandProduct.objects.get(name="工具").facts == ["更新后的事实"]
    assert BrandProduct.objects.filter(pk=extra.pk).exists()


def test_database_failure_rolls_back_profile_and_children(destination, bundle, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("simulated write failure")
    monkeypatch.setattr(BrandExample, "save", fail)
    with pytest.raises(RuntimeError, match="simulated write failure"):
        run_import(destination, bundle)
    assert not BrandProfile.objects.exists()
    assert not BrandProduct.objects.exists()


def test_same_name_is_isolated_by_owner_and_organization(destination, bundle):
    run_import(destination, bundle)
    user, org, app = destination
    other = get_user_model().objects.create_user(username="import-other")
    Membership.objects.create(user=other, organization=org, role=Membership.Role.VIEWER)
    run_import((other, org, app), bundle)
    other_org = other.owned_organizations.get()
    other_app = Application.objects.create(
        organization=other_org, category=app.category, name="品牌资料库", slug="brand-library",
        created_by=other, kind="custom", visibility="organization",
    )
    run_import((other, other_org, other_app), bundle)
    assert BrandProfile.objects.count() == 3
    assert BrandProduct.objects.count() == 3
    assert BrandExample.objects.count() == 3
    assert BrandProfile.objects.filter(owner=user, organization=org).count() == 1


@pytest.mark.parametrize("reason", ["inactive_user", "inactive_membership", "inactive_app", "private_app"])
def test_missing_access_never_creates_data(destination, bundle, reason):
    owner, org, app = destination
    user = get_user_model().objects.create_user(username="import-reader")
    membership = Membership.objects.create(user=user, organization=org, role=Membership.Role.VIEWER)
    if reason == "inactive_user":
        user.is_active = False
        user.save(update_fields=["is_active"])
    elif reason == "inactive_membership":
        membership.is_active = False
        membership.save(update_fields=["is_active"])
    elif reason == "inactive_app":
        app.is_active = False
        app.save(update_fields=["is_active"])
    else:
        app.visibility = "private"
        app.save(update_fields=["visibility"])
    with pytest.raises(CommandError):
        run_import((user, org, app), bundle)
    assert not BrandProfile.objects.exists()


@pytest.mark.parametrize("data", [
    {"name": "工具", "owner_id": 999},
    {"name": "工具", "facts": ["x" * 2001]},
])
def test_invalid_child_prevents_partial_import(destination, bundle, data):
    (bundle.parent / "product.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(CommandError):
        run_import(destination, bundle)
    assert not BrandProfile.objects.exists()


def test_bundle_rejects_duplicate_names_and_directory_escape(destination, bundle):
    manifest = json.loads(bundle.read_text())
    manifest["products"] *= 2
    bundle.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(CommandError, match="Duplicate products"):
        run_import(destination, bundle)
    manifest["products"] = ["../outside.json"]
    bundle.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(CommandError, match="inside its directory"):
        run_import(destination, bundle)
    assert not BrandProfile.objects.exists()


def test_ambiguous_membership_requires_explicit_organization(destination, bundle):
    user, org, _ = destination
    other = get_user_model().objects.create_user(username="other-org-owner")
    Membership.objects.create(user=user, organization=other.owned_organizations.get(), role=Membership.Role.VIEWER)
    with pytest.raises(CommandError, match="exactly one"):
        run_import(destination, bundle, organization=None)
    result = run_import(destination, bundle, organization=org.slug)
    assert result["organization_id"] == str(org.pk)


def test_shipped_bundle_is_portable_and_valid(destination, settings):
    bundle_path = Path(settings.BASE_DIR).parent / "docs/brands/agentic-ai-workshop/import-manifest.json"
    result = run_import(destination, bundle_path)
    assert [entry["kind"] for entry in result["entries"]] == ["profile", "products"]
    assert BrandProfile.objects.get().name == "智能体AI工坊"
    assert BrandProduct.objects.get().name == "Agent Studio（当前项目名称）"
