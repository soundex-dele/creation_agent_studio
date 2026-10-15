import uuid
from django.conf import settings
from django.db import models
from modules.tenancy.models import TenantOwnedModel


class PrivateRecord(TenantOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    application = models.ForeignKey('applications.Application', on_delete=models.CASCADE, related_name='+')
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+')
    title = models.CharField(max_length=200)
    status = models.CharField(max_length=24, default='draft')
    revision = models.PositiveIntegerField(default=0)
    archived = models.BooleanField(default=False)
    data = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ['-updated_at', 'id']
        indexes = [models.Index(fields=['organization', 'application', 'owner'])]


class Case(PrivateRecord):
    source_snapshot = models.JSONField(default=dict)


class Topic(PrivateRecord):
    case = models.ForeignKey(Case, on_delete=models.PROTECT, related_name='topics')
    materials = models.ManyToManyField(Case, through='TopicMaterial', related_name='referencing_topics')


class TopicMaterial(TenantOwnedModel):
    topic = models.ForeignKey(Topic, on_delete=models.CASCADE)
    material = models.ForeignKey(Case, on_delete=models.PROTECT)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['topic', 'material'], name='promotion_topic_material')]


class Channel(PrivateRecord):
    topic = models.ForeignKey(Topic, on_delete=models.PROTECT, related_name='channels')
    platform = models.CharField(max_length=20)
    confirmed_version = models.ForeignKey('Version', null=True, blank=True, on_delete=models.PROTECT, related_name='+')

    class Meta(PrivateRecord.Meta):
        constraints = [models.UniqueConstraint(fields=['topic', 'platform'], name='promotion_topic_platform')]


class Version(TenantOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name='versions')
    number = models.PositiveIntegerField()
    body = models.JSONField(default=dict)
    snapshot = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-number']
        constraints = [models.UniqueConstraint(fields=['channel', 'number'], name='promotion_version_number')]


class Feedback(PrivateRecord):
    channel = models.ForeignKey(Channel, null=True, blank=True, on_delete=models.PROTECT, related_name='feedback')


class AITask(PrivateRecord):
    run = models.OneToOneField('execution.Run', null=True, on_delete=models.SET_NULL, related_name='promotion_task')
    kind = models.CharField(max_length=20)
    request_key = models.CharField(max_length=160)
    request_hash = models.CharField(max_length=64)
    snapshot = models.JSONField(default=dict)
    result = models.JSONField(default=dict)
    error = models.TextField(blank=True)
    applied = models.BooleanField(default=False)

    class Meta(PrivateRecord.Meta):
        constraints = [models.UniqueConstraint(fields=['organization', 'application', 'owner', 'request_key'], name='promotion_task_request')]


class Workspace(TenantOwnedModel):
    application = models.ForeignKey('applications.Application', on_delete=models.CASCADE)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['organization', 'application', 'owner'], name='promotion_workspace_owner')]


class Handoff(PrivateRecord):
    source_type = models.CharField(max_length=20, default='version', choices=[
        ('version', '文案版本'), ('topic', '选题'), ('materials', '素材探索'),
    ])
    version = models.ForeignKey(Version, null=True, blank=True, on_delete=models.PROTECT)
    topic = models.ForeignKey(Topic, null=True, blank=True, on_delete=models.PROTECT)
    platform = models.CharField(max_length=20, default='')
    snapshot = models.JSONField(default=dict)
    target_application = models.ForeignKey('applications.Application', on_delete=models.PROTECT, related_name='+')
    draft = models.JSONField(default=dict)
    conversation = models.ForeignKey('conversations.Conversation', null=True, on_delete=models.SET_NULL)

    class Meta(PrivateRecord.Meta):
        constraints = [models.CheckConstraint(
            condition=(models.Q(source_type='version', version__isnull=False, topic__isnull=True)
                       | models.Q(source_type='topic', version__isnull=True, topic__isnull=False)
                       | models.Q(source_type='materials', version__isnull=True, topic__isnull=True)),
            name='promotion_handoff_source',
        )]


RESOURCES = {'cases': Case, 'topics': Topic, 'channels': Channel, 'feedback': Feedback}
