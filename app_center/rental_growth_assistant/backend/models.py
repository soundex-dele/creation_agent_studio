import uuid
from django.conf import settings
from django.db import models
from modules.tenancy.models import TenantOwnedModel


class PrivateRecord(TenantOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    application = models.ForeignKey('applications.Application', on_delete=models.CASCADE)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    status = models.CharField(max_length=30)
    archived = models.BooleanField(default=False)
    revision = models.PositiveIntegerField(default=0)
    data = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ['-updated_at', 'id']
        indexes = [models.Index(fields=['organization', 'application', 'owner'])]


class Property(PrivateRecord):
    pass


class Persona(PrivateRecord):
    pass


class Lead(PrivateRecord):
    pass


class FollowUp(PrivateRecord):
    lead = models.ForeignKey(Lead, on_delete=models.PROTECT, related_name='followups')


class Viewing(PrivateRecord):
    lead = models.ForeignKey(Lead, on_delete=models.PROTECT, related_name='viewings')


class Content(PrivateRecord):
    pass


class ContentVersion(TenantOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    content = models.ForeignKey(Content, on_delete=models.CASCADE, related_name='versions')
    number = models.PositiveIntegerField()
    body = models.JSONField(default=dict)
    snapshot = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-number']
        constraints = [models.UniqueConstraint(fields=['content', 'number'], name='rental_version_number')]


class Publication(PrivateRecord):
    version = models.ForeignKey(ContentVersion, on_delete=models.PROTECT, related_name='publications')


class MetricObservation(TenantOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    publication = models.ForeignKey(Publication, on_delete=models.CASCADE, related_name='metrics')
    data = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']


class Preferences(TenantOwnedModel):
    application = models.ForeignKey('applications.Application', on_delete=models.CASCADE)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    data = models.JSONField(default=dict)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['organization', 'application', 'owner'], name='rental_preferences_owner')]


class AITask(TenantOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    application = models.ForeignKey('applications.Application', on_delete=models.CASCADE)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    run = models.OneToOneField('execution.Run', null=True, on_delete=models.SET_NULL)
    kind = models.CharField(max_length=30)
    request_key = models.CharField(max_length=160)
    request_hash = models.CharField(max_length=64)
    snapshot = models.JSONField(default=dict)
    result = models.JSONField(default=dict)
    status = models.CharField(max_length=30, default='queued')
    error = models.TextField(blank=True)
    cancel_requested = models.BooleanField(default=False)
    applied = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', 'id']
        constraints = [models.UniqueConstraint(fields=['organization', 'application', 'owner', 'request_key'], name='rental_task_request')]


RESOURCES = {'properties': Property, 'personas': Persona, 'leads': Lead, 'followups': FollowUp,
             'viewings': Viewing, 'contents': Content, 'publications': Publication}
