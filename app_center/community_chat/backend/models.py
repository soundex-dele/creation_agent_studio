import uuid

from django.conf import settings
from django.db import models


class Room(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=10, choices=[('lobby', '大厅'), ('direct', '私聊'), ('group', '群聊')])
    # A fixed lobby key and sorted user pair prevent duplicate rooms under races.
    unique_key = models.CharField(max_length=100, unique=True, null=True, blank=True)
    name = models.CharField(max_length=100, blank=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name='+')
    version = models.PositiveBigIntegerField(default=0)
    closed = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Membership(models.Model):
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='memberships')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='community_memberships')
    last_read_id = models.PositiveBigIntegerField(default=0)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['room', 'user'], name='community_unique_member')]


class Message(models.Model):
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='messages')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    text = models.TextField(blank=True)
    request_key = models.CharField(max_length=160)
    payload_hash = models.CharField(max_length=64)
    revision = models.PositiveBigIntegerField()
    withdrawn = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['room', 'author', 'request_key'], name='community_unique_send')]
        indexes = [models.Index(fields=['room', 'id']), models.Index(fields=['room', 'revision'])]


class Attachment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room = models.ForeignKey(Room, on_delete=models.CASCADE)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    message = models.ForeignKey(Message, null=True, on_delete=models.CASCADE, related_name='attachments')
    name = models.CharField(max_length=255)
    size = models.PositiveBigIntegerField()
    content_type = models.CharField(max_length=100, default='application/octet-stream')
    image = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)


class SocketTicket(models.Model):
    digest = models.CharField(max_length=64, primary_key=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    expires_at = models.DateTimeField()
    consumed = models.BooleanField(default=False)
