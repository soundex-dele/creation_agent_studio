import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from modules.tenancy.models import TenantOwnedModel


class StableDefinition(TenantOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
    )
    name = models.CharField(max_length=160)
    slug = models.SlugField(max_length=120)
    description = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class DefinitionDraft(TenantOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    content = models.JSONField(default=dict)
    version = models.PositiveBigIntegerField(default=1)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class ImmutableRevision(TenantOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    revision_no = models.PositiveIntegerField()
    schema_version = models.PositiveIntegerField(default=1)
    content = models.JSONField(default=dict)
    content_hash = models.CharField(max_length=64, db_index=True)
    release_notes = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Published revisions are immutable")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Published revisions are immutable")


class Agent(StableDefinition):
    class Meta:
        db_table = "v2_agents"
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "slug"),
                name="v2_unique_agent_slug",
            )
        ]


class AgentDraft(DefinitionDraft):
    agent = models.OneToOneField(Agent, on_delete=models.CASCADE, related_name="draft")

    class Meta:
        db_table = "v2_agent_drafts"


class AgentRevision(ImmutableRevision):
    agent = models.ForeignKey(Agent, on_delete=models.PROTECT, related_name="revisions")

    class Meta:
        db_table = "v2_agent_revisions"
        ordering = ("agent_id", "revision_no")
        constraints = [
            models.UniqueConstraint(
                fields=("agent", "revision_no"),
                name="v2_unique_agent_revision_number",
            ),
            models.UniqueConstraint(
                fields=("agent", "content_hash"),
                name="v2_unique_agent_revision_content",
            ),
        ]


class Skill(StableDefinition):
    class Meta:
        db_table = "v2_skills"
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "slug"),
                name="v2_unique_skill_slug",
            )
        ]


class SkillDraft(DefinitionDraft):
    skill = models.OneToOneField(Skill, on_delete=models.CASCADE, related_name="draft")

    class Meta:
        db_table = "v2_skill_drafts"


class SkillRevision(ImmutableRevision):
    skill = models.ForeignKey(Skill, on_delete=models.PROTECT, related_name="revisions")

    class Meta:
        db_table = "v2_skill_revisions"
        ordering = ("skill_id", "revision_no")
        constraints = [
            models.UniqueConstraint(
                fields=("skill", "revision_no"),
                name="v2_unique_skill_revision_number",
            ),
            models.UniqueConstraint(
                fields=("skill", "content_hash"),
                name="v2_unique_skill_revision_content",
            ),
        ]


class Application(StableDefinition):
    class Meta:
        db_table = "v2_applications"
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "slug"),
                name="v2_unique_application_slug",
            )
        ]


class ApplicationDraft(DefinitionDraft):
    application = models.OneToOneField(
        Application,
        on_delete=models.CASCADE,
        related_name="draft",
    )

    class Meta:
        db_table = "v2_application_drafts"


class ApplicationRevision(ImmutableRevision):
    application = models.ForeignKey(
        Application,
        on_delete=models.PROTECT,
        related_name="revisions",
    )

    class Meta:
        db_table = "v2_application_revisions"
        ordering = ("application_id", "revision_no")
        constraints = [
            models.UniqueConstraint(
                fields=("application", "revision_no"),
                name="v2_unique_application_revision_number",
            ),
            models.UniqueConstraint(
                fields=("application", "content_hash"),
                name="v2_unique_application_revision_content",
            ),
        ]


class DeploymentEnvironment(models.TextChoices):
    DEVELOPMENT = "development", "Development"
    STAGING = "staging", "Staging"
    PRODUCTION = "production", "Production"


class AgentDeployment(TenantOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name="deployments")
    environment = models.CharField(max_length=20, choices=DeploymentEnvironment.choices)
    revision = models.ForeignKey(AgentRevision, on_delete=models.PROTECT, related_name="deployments")
    previous_revision = models.ForeignKey(
        AgentRevision,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="previous_deployments",
    )
    config_override = models.JSONField(default=dict, blank=True)
    version = models.PositiveBigIntegerField(default=1)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "v2_agent_deployments"
        constraints = [
            models.UniqueConstraint(
                fields=("agent", "environment"),
                name="v2_unique_agent_deployment_environment",
            )
        ]


class ApplicationDeployment(TenantOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    application = models.ForeignKey(
        Application,
        on_delete=models.CASCADE,
        related_name="deployments",
    )
    environment = models.CharField(max_length=20, choices=DeploymentEnvironment.choices)
    revision = models.ForeignKey(
        ApplicationRevision,
        on_delete=models.PROTECT,
        related_name="deployments",
    )
    previous_revision = models.ForeignKey(
        ApplicationRevision,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="previous_deployments",
    )
    config_override = models.JSONField(default=dict, blank=True)
    version = models.PositiveBigIntegerField(default=1)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "v2_application_deployments"
        constraints = [
            models.UniqueConstraint(
                fields=("application", "environment"),
                name="v2_unique_application_deployment_environment",
            )
        ]
