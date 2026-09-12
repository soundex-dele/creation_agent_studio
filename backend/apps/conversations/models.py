"""
Models for conversations app.
"""
import uuid

from django.db import models
from apps.users.models import User


class Conversation(models.Model):
    """对话会话"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='conversations')
    organization = models.ForeignKey(
        'enterprise.Organization', on_delete=models.CASCADE, null=True, blank=True,
        related_name='conversations'
    )
    title = models.CharField(max_length=200, blank=True)
    agent = models.ForeignKey('agents.Agent', on_delete=models.SET_NULL, null=True, blank=True, related_name='conversations')
    chat_application = models.ForeignKey(
        'applications.ChatApplication', on_delete=models.PROTECT,
        null=True, blank=True, related_name='conversations')
    workflow_step_run = models.ForeignKey(
        'workflows.WorkflowStepRun', on_delete=models.CASCADE,
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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        db_table = 'conversations'
        constraints = [models.CheckConstraint(
            check=(models.Q(chat_application__isnull=True) |
                   models.Q(workflow_step_run__isnull=True)),
            name='conversation_has_no_duplicate_chat_context',
        )]

    @property
    def application_id(self):
        if self.chat_application_id:
            return self.chat_application_id
        if self.workflow_step_run_id:
            return self.workflow_step_run.application_id
        return None

    @property
    def application(self):
        if self.chat_application_id:
            return self.chat_application.application
        if self.workflow_step_run_id:
            return self.workflow_step_run.application
        return None

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
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    content = models.TextField()
    metadata = models.JSONField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        db_table = 'messages'

    def __str__(self):
        return f'{self.role}: {self.content[:50]}'


class AgentThread(models.Model):
    """Provider-neutral thread mapped to a product conversation."""

    class Status(models.TextChoices):
        IDLE = 'idle', 'Idle'
        ACTIVE = 'active', 'Active'
        ARCHIVED = 'archived', 'Archived'
        ERROR = 'error', 'Error'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.OneToOneField(
        Conversation, on_delete=models.CASCADE, related_name='agent_thread')
    provider = models.CharField(max_length=32, default='graphflow')
    remote_id = models.CharField(max_length=255, blank=True, default='')
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.IDLE)
    config = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'agent_threads'
        indexes = [models.Index(fields=['provider', 'remote_id'])]


class AgentTurn(models.Model):
    """One user request and the agent work produced for it."""

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        IN_PROGRESS = 'in_progress', 'In progress'
        COMPLETED = 'completed', 'Completed'
        FAILED = 'failed', 'Failed'
        INTERRUPTED = 'interrupted', 'Interrupted'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    thread = models.ForeignKey(
        AgentThread, on_delete=models.CASCADE, related_name='turns')
    remote_id = models.CharField(max_length=255, blank=True, default='')
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING)
    input = models.JSONField(default=list, blank=True)
    usage = models.JSONField(default=dict, blank=True)
    error = models.JSONField(default=dict, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'agent_turns'
        ordering = ['started_at']
        indexes = [models.Index(fields=['thread', 'status'])]


class AgentItem(models.Model):
    """Materialized Codex-style item belonging to a turn."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    turn = models.ForeignKey(
        AgentTurn, on_delete=models.CASCADE, related_name='items')
    remote_id = models.CharField(max_length=255)
    item_type = models.CharField(max_length=64)
    status = models.CharField(max_length=32, blank=True, default='')
    ordinal = models.PositiveIntegerField(default=0)
    content = models.TextField(blank=True, default='')
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'agent_items'
        ordering = ['ordinal', 'created_at']
        constraints = [models.UniqueConstraint(
            fields=['turn', 'remote_id'], name='unique_agent_item_remote_id')]


class AgentServerRequest(models.Model):
    """Pending approval or user-input request initiated by an agent runtime."""

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        RESOLVED = 'resolved', 'Resolved'
        DISMISSED = 'dismissed', 'Dismissed'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    thread = models.ForeignKey(
        AgentThread, on_delete=models.CASCADE, related_name='server_requests')
    turn = models.ForeignKey(
        AgentTurn, on_delete=models.CASCADE, related_name='server_requests',
        null=True, blank=True)
    remote_id = models.CharField(max_length=255, blank=True, default='')
    method = models.CharField(max_length=128)
    params = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING)
    response = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'agent_server_requests'
        ordering = ['created_at']
        indexes = [models.Index(fields=['thread', 'status'])]
        constraints = [models.UniqueConstraint(
            fields=['thread', 'turn', 'remote_id', 'method'],
            name='unique_agent_server_request_remote_id')]
