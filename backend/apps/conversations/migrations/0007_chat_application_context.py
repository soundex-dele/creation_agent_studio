import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.utils.text import slugify


def preserve_chat_context_and_memberships(apps, schema_editor):
    Conversation = apps.get_model('conversations', 'Conversation')
    ChatApplication = apps.get_model('applications', 'ChatApplication')
    Organization = apps.get_model('enterprise', 'Organization')
    Membership = apps.get_model('enterprise', 'Membership')
    QuotaPolicy = apps.get_model('enterprise', 'QuotaPolicy')
    GovernancePolicy = apps.get_model('enterprise', 'GovernancePolicy')
    User = apps.get_model('users', 'User')

    chat_application_ids = set(
        ChatApplication.objects.values_list('application_id', flat=True))
    for conversation in Conversation.objects.filter(
            application_id__in=chat_application_ids).iterator():
        Conversation.objects.filter(pk=conversation.pk).update(
            chat_application_id=conversation.application_id)

    for user in User.objects.all().iterator():
        if Membership.objects.filter(user_id=user.id, is_active=True).exists():
            continue
        organization = Organization.objects.filter(
            owner_id=user.id).order_by('created_at').first()
        if organization is None:
            base = slugify(user.username)[:70] or f'user-{user.pk}'
            organization, _ = Organization.objects.get_or_create(
                slug=f'{base}-{user.pk}',
                defaults={
                    'name': f'{user.username} Workspace',
                    'owner_id': user.id,
                },
            )
        Membership.objects.get_or_create(
            organization_id=organization.id,
            user_id=user.id,
            defaults={'role': 'owner', 'is_active': True},
        )
        QuotaPolicy.objects.get_or_create(organization_id=organization.id)
        GovernancePolicy.objects.get_or_create(organization_id=organization.id)


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ('applications', '0006_chat_application_subtype'),
        ('conversations', '0006_require_organization_and_message_run'),
        ('enterprise', '0005_external_identity'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='conversation',
            name='chat_application',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='conversations',
                to='applications.chatapplication',
            ),
        ),
        migrations.RunPython(
            preserve_chat_context_and_memberships,
            migrations.RunPython.noop,
        ),
        migrations.RemoveField(
            model_name='conversation',
            name='application',
        ),
    ]
