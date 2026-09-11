"""Idempotently seed the 批量转录 (batch-transcribe) Application + its category."""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from apps.applications.models import Application, ApplicationCategory
from modules.catalog.models import (
    ApplicationDeployment, ApplicationDraft, DeploymentEnvironment,
)
from modules.catalog.services import publish_application, switch_application_deployment

SLUG = 'batch-transcribe'


class Command(BaseCommand):
    help = f'Seed the {SLUG} application row (idempotent).'

    def handle(self, *args, **options):
        User = get_user_model()
        owner = User.objects.first()
        if owner is None:
            self.stderr.write('No user exists yet — register a user, then re-run.')
            return
        membership = owner.organization_memberships.filter(
            is_active=True, organization__is_active=True
        ).select_related('organization').first()
        if membership is None:
            self.stderr.write('The selected user has no active organization.')
            return
        organization = membership.organization

        cat, _ = ApplicationCategory.objects.get_or_create(
            slug='audio',
            defaults={'name': '音频工具', 'order': 30},
        )
        app, created = Application.objects.update_or_create(
            organization=organization,
            slug=SLUG,
            defaults={
                'category': cat,
                'name': '批量转录',
                'description': '基于 Whisper 的批量视频转文字/字幕（.txt/.srt）。',
                'icon': '🎙️',
                'color': '#2e7d32',
                'tags': ['转录', 'Whisper', '字幕'],
                'developer': 'creation_master',
                'is_public': True,
                'kind': Application.Kind.TASK,
                'renderer_key': 'batch-transcribe',
                'executor_key': 'batch-transcribe',
                'created_by': owner,
            },
        )
        content = {
            'executor_kind': 'media',
            'executor_key': 'batch-transcribe',
            'executor_protocol_version': 1,
            'renderer_key': 'batch-transcribe',
            'renderer_schema_version': 1,
            'retry_policy': {'max_attempts': 3, 'retry_safe': True},
            'input_schema': {
                'type': 'object',
                'required': ['folder'],
                'properties': {
                    'folder': {'type': 'string'},
                    'model': {'type': 'string'},
                    'language': {'type': 'string'},
                },
            },
            'output_schema': {'type': 'object'},
            'default_config': {},
        }
        draft, _ = ApplicationDraft.objects.update_or_create(
            application=app,
            defaults={
                'organization': organization,
                'updated_by': owner,
                'content': content,
            },
        )
        revision = publish_application(
            application=app,
            actor=owner,
            expected_draft_version=draft.version,
            release_notes='Built-in batch transcription runtime',
        )
        deployment = ApplicationDeployment.objects.filter(
            application=app,
            environment=DeploymentEnvironment.PRODUCTION,
        ).first()
        switch_application_deployment(
            application=app,
            actor=owner,
            environment=DeploymentEnvironment.PRODUCTION,
            revision_id=revision.id,
            expected_version=deployment.version if deployment else 0,
        )
        self.stdout.write(self.style.SUCCESS(
            f"{'Created' if created else 'Updated'} application {SLUG} (id={app.id})."))
