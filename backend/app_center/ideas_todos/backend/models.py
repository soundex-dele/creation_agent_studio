import uuid

from django.conf import settings
from django.db import models

from modules.tenancy.models import TenantOwnedModel


class PersonalEntry(TenantOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    application = models.ForeignKey("applications.Application", on_delete=models.CASCADE)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Idea(PersonalEntry):
    body = models.TextField(blank=True)
    tags = models.JSONField(default=list, blank=True)
    is_pinned = models.BooleanField(default=False)

    class Meta:
        db_table = "ideas_todos_ideas"
        ordering = ["-is_pinned", "-updated_at", "id"]
        indexes = [models.Index(fields=["organization", "application", "owner"], name="it_idea_scope")]


class Todo(PersonalEntry):
    class Priority(models.IntegerChoices):
        LOW = 1, "低"
        MEDIUM = 2, "中"
        HIGH = 3, "高"

    description = models.TextField(blank=True)
    priority = models.PositiveSmallIntegerField(choices=Priority.choices, default=Priority.MEDIUM)
    due_date = models.DateField(null=True, blank=True)
    is_completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "ideas_todos_todos"
        indexes = [models.Index(fields=["organization", "application", "owner", "is_completed"], name="it_todo_scope")]
