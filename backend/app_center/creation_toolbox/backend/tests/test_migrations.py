import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from apps.applications.models import Application, ApplicationCategory
from apps.enterprise.models import Membership, Organization
from django.contrib.auth import get_user_model

from ..models import (
    Copywriting,
    CreationProject,
    CreationWorkspace,
    MediaAsset,
    Recording,
    Script,
)


@pytest.mark.django_db(transaction=True)
def test_full_lifecycle_migration_preserves_existing_creation_data(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    owner = get_user_model().objects.create_user(username="toolbox-migration-owner")
    organization = Organization.objects.create(
        name="Migration Organization", slug="toolbox-migration", owner=owner
    )
    Membership.objects.create(
        organization=organization, user=owner, role=Membership.Role.OWNER
    )
    category = ApplicationCategory.objects.create(
        name="Migration Creative", slug="toolbox-migration-creative"
    )
    application = Application.objects.create(
        organization=organization,
        category=category,
        name="迁移创作工具箱",
        slug="creation-toolbox-migration",
        description="migration test",
        created_by=owner,
        kind=Application.Kind.CUSTOM,
    )
    workspace = CreationWorkspace.objects.create(
        organization=organization, application=application
    )
    project = CreationProject.objects.create(
        organization=organization,
        workspace=workspace,
        name="既有工程",
        created_by=owner,
    )
    Copywriting.objects.create(
        organization=organization,
        workspace=workspace,
        project=project,
        title="既有文案",
        content="原样保留",
        style=Copywriting.Style.INFORMATIVE,
        created_by=owner,
    )
    Script.objects.create(
        organization=organization,
        workspace=workspace,
        project=project,
        title="既有脚本",
        created_by=owner,
    )
    MediaAsset.objects.create(
        organization=organization,
        project=project,
        name="existing.txt",
        file=SimpleUploadedFile("existing.txt", b"asset"),
        kind=MediaAsset.Kind.DOCUMENT,
        size=5,
        created_by=owner,
    )
    Recording.objects.create(
        organization=organization,
        workspace=workspace,
        project=project,
        name="既有录音",
        audio=SimpleUploadedFile("existing.webm", b"audio"),
        created_by=owner,
    )

    executor = MigrationExecutor(connection)
    executor.migrate([("creation_toolbox", "0001_initial_compacted")])
    executor = MigrationExecutor(connection)
    executor.migrate([("creation_toolbox", "0004_creationproject_work_type")])
    apps = executor.loader.project_state(
        [("creation_toolbox", "0004_creationproject_work_type")]
    ).apps

    MigratedProject = apps.get_model("creation_toolbox", "CreationProject")
    migrated = MigratedProject.objects.get(name="既有工程")
    assert migrated.stage == "planning"
    assert migrated.work_type == "short_video"
    assert apps.get_model("creation_toolbox", "Copywriting").objects.filter(
        title="既有文案", content="原样保留"
    ).exists()
    assert apps.get_model("creation_toolbox", "Script").objects.filter(
        title="既有脚本"
    ).exists()
    assert apps.get_model("creation_toolbox", "MediaAsset").objects.filter(
        name="existing.txt"
    ).exists()
    assert apps.get_model("creation_toolbox", "Recording").objects.filter(
        name="既有录音"
    ).exists()
