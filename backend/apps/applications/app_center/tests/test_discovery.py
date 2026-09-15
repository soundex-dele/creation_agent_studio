from pathlib import Path

from django.conf import settings

from apps.applications.app_center.discovery import discover_packages


def test_bundled_contacts_package_is_valid():
    packages, errors = discover_packages(settings.APP_CENTER_ROOT, strict=True)

    assert not errors
    contacts = next(package for package in packages if package.manifest.metadata.id == "contacts")
    assert contacts.manifest.spec.database.mode == "django-migrations"
    assert contacts.manifest.spec.backend.django_app.endswith("ContactsConfig")
    assert len(contacts.content_hash) == 64


def test_all_bundled_packages_are_discovered_and_runtime_is_registered():
    packages, _ = discover_packages(settings.APP_CENTER_ROOT, strict=True)

    assert {package.manifest.metadata.id for package in packages} == {
        "batch-transcribe", "case-library", "contacts",
    }
    assert settings.EXECUTION_CHILD_ADAPTERS["media"]["batch-transcribe"] == (
        "app_center.batch_transcribe.runtime.execute_batch_transcribe"
    )


def test_invalid_package_is_quarantined(tmp_path: Path):
    package = tmp_path / "broken_app"
    package.mkdir()
    (package / "application.yaml").write_text("kind: Unknown\n", encoding="utf-8")

    packages, errors = discover_packages(tmp_path, strict=False)

    assert packages == []
    assert len(errors) == 1
    assert "validation error" in str(errors[0])
