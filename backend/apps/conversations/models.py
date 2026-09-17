"""Models for conversations app."""
import uuid
from pathlib import Path

from django.db import models
from apps.users.models import User
from modules.tenancy.models import TenantOwnedQuerySet


def message_attachment_upload_to(instance, filename):
    """Keep tenant/conversation uploads isolated and filenames unguessable."""

    extension_by_type = {
        'image/jpeg': '.jpg',
        'image/png': '.png',
        'image/webp': '.webp',
    }
    extension = extension_by_type.get(instance.content_type)
    if extension is None:
        extension = Path(filename).suffix.lower()[:10]
    return (
        f'conversations/{instance.organization_id}/'
        f'{instance.conversation_id}/{instance.id}{extension}'
    )


class Conversation(models.Model):
    """对话会话"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='conversations')
    organization = models.ForeignKey(
        'enterprise.Organization', on_delete=models.CASCADE,
        related_name='conversations'
    )
    title = models.CharField(max_length=200, blank=True)
    agent = models.ForeignKey('agents.Agent', on_delete=models.SET_NULL, null=True, blank=True, related_name='conversations')
    chat_application = models.ForeignKey(
        'applications.ChatApplication', on_delete=models.PROTECT,
        null=True, blank=True, related_name='conversations')
    # Workspace (Project) this conversation belongs to. Legacy/global chats keep this null.
    project = models.ForeignKey(
        'projects.Project',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='conversations',
    )
    # Template process id (e.g. "cover", "copy") identifying the flow within the workspace.
    process_id = models.CharField(max_length=64, blank=True, default='')
    working_directory = models.CharField(max_length=1000, blank=True, default='')
    agent_thread_provider = models.CharField(max_length=32, blank=True, default='')
    agent_thread_id = models.CharField(max_length=255, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = TenantOwnedQuerySet.as_manager()

    class Meta:
        ordering = ['-updated_at']
        db_table = 'conversations'
        constraints = [models.CheckConstraint(
            condition=(
                models.Q(agent_thread_provider='', agent_thread_id='')
                | (
                    ~models.Q(agent_thread_provider='')
                    & ~models.Q(agent_thread_id='')
                )
            ),
            name='conversation_agent_thread_consistent',
        )]

    @property
    def application_id(self):
        return self.chat_application_id

    @property
    def application(self):
        return (
            self.chat_application.application
            if self.chat_application_id else None
        )

    def __str__(self):
        return self.title or f'对话 {self.id}'


class ConversationSkillBinding(models.Model):
    class Source(models.TextChoices):
        AGENT_REQUIRED = 'agent_required', '智能体必需'
        AGENT_DEFAULT = 'agent_default', '智能体默认'
        APP_REQUIRED = 'app_required', '应用必需'
        APP_DEFAULT = 'app_default', '应用默认'
        USER = 'user', '用户选择'

    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name='skill_bindings')
    skill = models.ForeignKey(
        'applications.Skill', on_delete=models.PROTECT,
        related_name='conversation_bindings')
    source = models.CharField(max_length=30, choices=Source.choices)
    enabled = models.BooleanField(default=True)
    config = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'conversation_skill_bindings'
        constraints = [models.UniqueConstraint(
            fields=['conversation', 'skill'],
            name='unique_conversation_skill_binding')]


class Message(models.Model):
    """消息"""
    ROLE_CHOICES = [
        ('user', '用户'),
        ('assistant', '助手'),
        ('system', '系统'),
    ]

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='messages')
    run = models.ForeignKey(
        'execution.Run', on_delete=models.PROTECT, null=True, blank=True,
        related_name='projected_messages')
    run_event_sequence = models.PositiveBigIntegerField(null=True, blank=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    content = models.TextField()
    metadata = models.JSONField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        db_table = 'messages'
        constraints = [models.UniqueConstraint(
            fields=['run', 'run_event_sequence'],
            condition=models.Q(run__isnull=False, run_event_sequence__isnull=False),
            name='unique_run_event_message')]

    def __str__(self):
        return f'{self.role}: {self.content[:50]}'


class MessageAttachment(models.Model):
    """A validated image attached to one persisted conversation message."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        'enterprise.Organization',
        on_delete=models.CASCADE,
        related_name='message_attachments',
    )
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name='attachments',
    )
    message = models.ForeignKey(
        Message,
        on_delete=models.CASCADE,
        related_name='attachments',
    )
    file = models.FileField(upload_to=message_attachment_upload_to, max_length=500)
    original_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100)
    byte_size = models.PositiveBigIntegerField()
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    checksum_sha256 = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = TenantOwnedQuerySet.as_manager()

    class Meta:
        ordering = ['created_at', 'id']
        db_table = 'message_attachments'
        indexes = [models.Index(fields=['conversation', 'message'])]

    def __str__(self):
        return self.original_name
