from pathlib import Path

from django.conf import settings

from apps.applications.app_center.discovery import (
    discover_django_apps,
    discover_executor_adapters,
    discover_packages,
)


def test_bundled_creation_toolbox_package_is_valid():
    packages, errors = discover_packages(settings.APP_CENTER_ROOT, strict=True)

    assert not errors
    toolbox = next(package for package in packages if package.manifest.metadata.id == "creation-toolbox")
    assert toolbox.manifest.spec.database.mode == "django-migrations"
    assert toolbox.manifest.spec.backend.django_app.endswith("CreationToolboxConfig")
    assert len(toolbox.content_hash) == 64


def test_all_bundled_packages_are_discovered_and_runtime_is_registered():
    packages, _ = discover_packages(settings.APP_CENTER_ROOT, strict=True)
    package_ids = {package.manifest.metadata.id for package in packages}

    assert {
        "article-html-illustrator", "case-library",
        "gzh-design", "html-cover-generator", "wechat-html-optimizer",
        "wechat-viral-article", "tool-share-topic-expert",
    } <= package_ids
    chat_packages = {
        package.manifest.metadata.id: package
        for package in packages
        if package.manifest.metadata.id in {
            "article-html-illustrator", "gzh-design", "html-cover-generator",
            "wechat-html-optimizer", "wechat-viral-article",
            "tool-share-topic-expert",
        }
    }
    for package in chat_packages.values():
        assert package.manifest.spec.application_kind == "chat"
        assert package.manifest.spec.launch_mode == "chat"
        assert package.manifest.spec.definition["renderer_key"] == "chat"
        assert package.manifest.spec.backend.definition_factory
        assert package.manifest.spec.backend.executor_entrypoint is None

    creation_master_manifest = settings.APP_CENTER_ROOT / "creation_master" / "application.yaml"
    if creation_master_manifest.is_file():
        assert "creation-master" in package_ids
        creation_master = next(
            package for package in packages
            if package.manifest.metadata.id == "creation-master"
        )
        assert {frontend.type for frontend in creation_master.manifest.spec.frontends} == {
            "react", "qt",
        }
        assert settings.EXECUTION_CHILD_ADAPTERS["media"]["creation-master"] == (
            "app_center.creation_master.backend.runtime.execute_creation_master"
        )
    else:
        assert "creation-master" not in package_ids
        assert "creation-master" not in settings.EXECUTION_CHILD_ADAPTERS["media"]

def test_retired_applications_are_not_discovered_or_registered():
    packages, _ = discover_packages(settings.APP_CENTER_ROOT, strict=True)
    package_ids = {package.manifest.metadata.id for package in packages}
    adapters = discover_executor_adapters(settings.APP_CENTER_ROOT)

    assert package_ids.isdisjoint({"batch-transcribe", "newmedia-workbench", "contacts"})
    assert "batch-transcribe" not in adapters.get("media", {})
    assert "app_center.contacts.backend.apps.ContactsConfig" not in discover_django_apps(
        settings.APP_CENTER_ROOT,
    )


def test_invalid_package_is_quarantined(tmp_path: Path):
    package = tmp_path / "broken_app"
    package.mkdir()
    (package / "application.yaml").write_text("kind: Unknown\n", encoding="utf-8")

    packages, errors = discover_packages(tmp_path, strict=False)

    assert packages == []
    assert len(errors) == 1
    assert "validation error" in str(errors[0])


def test_directory_without_manifest_is_skipped(tmp_path: Path):
    (tmp_path / "not_an_application").mkdir()

    packages, errors = discover_packages(tmp_path, strict=True)

    assert packages == []
    assert errors == []
