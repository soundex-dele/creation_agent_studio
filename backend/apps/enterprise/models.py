"""Enterprise control-plane models.

The control plane intentionally stays in the Django modular monolith. Heavy
agent/application execution belongs to workers while these records provide a
durable source of truth for tenancy, policy, governance and observability.
"""
import uuid

from django.conf import settings
from django.db import models


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class OrganizationQuerySet(models.QuerySet):
    def visible_to(self, user):
        if user.is_superuser:
            return self
        return self.filter(
            memberships__user=user,
            memberships__is_active=True,
        ).distinct()


class Organization(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=160)
    slug = models.SlugField(max_length=100, unique=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                              related_name='owned_organizations')
    is_active = models.BooleanField(default=True)
    settings = models.JSONField(default=dict, blank=True)

    objects = OrganizationQuerySet.as_manager()

    class Meta:
        db_table = 'organizations'

    def __str__(self):
        return self.name


class Membership(TimeStampedModel):
    class Role(models.TextChoices):
        OWNER = 'owner', 'Owner'
        ADMIN = 'admin', 'Administrator'
        DEVELOPER = 'developer', 'Developer'
        OPERATOR = 'operator', 'Operator'
        AUDITOR = 'auditor', 'Auditor'
        VIEWER = 'viewer', 'Viewer'

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE,
                                     related_name='memberships')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name='organization_memberships')
    role = models.CharField(max_length=20, choices=Role.choices,
                            default=Role.VIEWER)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'organization_memberships'
        constraints = [models.UniqueConstraint(
            fields=['organization', 'user'], name='unique_org_membership')]


class AuditLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name='audit_logs')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                             on_delete=models.SET_NULL, related_name='audit_logs')
    action = models.CharField(max_length=120, db_index=True)
    resource_type = models.CharField(max_length=120, blank=True, db_index=True)
    resource_id = models.CharField(max_length=160, blank=True)
    request_id = models.CharField(max_length=64, blank=True, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'audit_logs'
        ordering = ['-created_at']


class QuotaPolicy(TimeStampedModel):
    organization = models.OneToOneField(Organization, on_delete=models.CASCADE,
                                        related_name='quota_policy')
    monthly_token_limit = models.BigIntegerField(default=10_000_000)
    monthly_cost_limit = models.DecimalField(max_digits=14, decimal_places=4,
                                             default=1000)
    max_concurrent_runs = models.PositiveIntegerField(default=20)
    requests_per_minute = models.PositiveIntegerField(default=120)
    storage_bytes_limit = models.BigIntegerField(default=100 * 1024 ** 3)
    hard_limit = models.BooleanField(default=True)

    class Meta:
        db_table = 'quota_policies'


class UsageRecord(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE,
                                     related_name='usage_records')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True,
                            on_delete=models.SET_NULL, related_name='usage_records')
    resource_type = models.CharField(max_length=50, db_index=True)
    resource_id = models.CharField(max_length=160, blank=True)
    provider = models.CharField(max_length=80, blank=True)
    model = models.CharField(max_length=160, blank=True)
    prompt_tokens = models.PositiveIntegerField(default=0)
    completion_tokens = models.PositiveIntegerField(default=0)
    total_tokens = models.PositiveIntegerField(default=0)
    cost = models.DecimalField(max_digits=14, decimal_places=6, default=0)
    latency_ms = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=30, default='success')
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'usage_records'
        ordering = ['-created_at']


class ProviderConfig(TimeStampedModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE,
                                     related_name='providers')
    name = models.CharField(max_length=100)
    provider_type = models.CharField(max_length=50, default='openai_compatible')
    base_url = models.URLField(max_length=500)
    secret_ref = models.CharField(max_length=200, blank=True)
    available_models = models.JSONField(default=list, blank=True)
    routing_weight = models.PositiveIntegerField(default=100)
    timeout_seconds = models.PositiveIntegerField(default=120)
    max_retries = models.PositiveIntegerField(default=2)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'provider_configs'
        constraints = [models.UniqueConstraint(
            fields=['organization', 'name'], name='unique_org_provider')]


class SecretReference(TimeStampedModel):
    """Metadata-only reference to an external Vault/KMS secret."""
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE,
                                     related_name='secret_references')
    name = models.CharField(max_length=100)
    backend = models.CharField(max_length=30, default='environment')
    reference = models.CharField(max_length=500)
    description = models.TextField(blank=True)
    rotated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'secret_references'
        constraints = [models.UniqueConstraint(
            fields=['organization', 'name'], name='unique_org_secret_ref')]


class IdentityProvider(TimeStampedModel):
    class Protocol(models.TextChoices):
        OIDC = 'oidc', 'OpenID Connect'
        SAML = 'saml', 'SAML 2.0'

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE,
                                     related_name='identity_providers')
    name = models.CharField(max_length=100)
    protocol = models.CharField(max_length=20, choices=Protocol.choices)
    issuer = models.CharField(max_length=500)
    client_id = models.CharField(max_length=300, blank=True)
    secret_ref = models.CharField(max_length=200, blank=True)
    metadata_url = models.URLField(max_length=1000, blank=True)
    domains = models.JSONField(default=list, blank=True)
    claim_mapping = models.JSONField(default=dict, blank=True)
    enforce_sso = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'identity_providers'
        constraints = [models.UniqueConstraint(
            fields=['organization', 'name'], name='unique_org_identity_provider')]


class ExternalIdentity(TimeStampedModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE,
                                     related_name='external_identities')
    provider = models.ForeignKey(IdentityProvider, on_delete=models.CASCADE,
                                 related_name='identities')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name='external_identities')
    subject = models.CharField(max_length=500)
    claims = models.JSONField(default=dict, blank=True)
    last_login_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'external_identities'
        constraints = [models.UniqueConstraint(
            fields=['provider', 'subject'], name='unique_provider_subject')]


class GovernancePolicy(TimeStampedModel):
    organization = models.OneToOneField(Organization, on_delete=models.CASCADE,
                                        related_name='governance_policy')
    retention_days = models.PositiveIntegerField(default=365)
    redact_pii = models.BooleanField(default=True)
    allowed_models = models.JSONField(default=list, blank=True)
    blocked_terms = models.JSONField(default=list, blank=True)
    allowed_tool_patterns = models.JSONField(default=list, blank=True)
    blocked_tool_patterns = models.JSONField(default=list, blank=True)
    require_tool_approval = models.BooleanField(default=True)
    network_allowlist = models.JSONField(default=list, blank=True)
    export_enabled = models.BooleanField(default=False)

    class Meta:
        db_table = 'governance_policies'


class RunTrace(models.Model):
    class Status(models.TextChoices):
        QUEUED = 'queued', 'Queued'
        RUNNING = 'running', 'Running'
        WAITING = 'waiting', 'Waiting for input'
        SUCCEEDED = 'succeeded', 'Succeeded'
        FAILED = 'failed', 'Failed'
        CANCELLED = 'cancelled', 'Cancelled'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE,
                                     related_name='run_traces')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True,
                            on_delete=models.SET_NULL, related_name='run_traces')
    kind = models.CharField(max_length=50, db_index=True)
    resource_id = models.CharField(max_length=160, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices,
                              default=Status.QUEUED, db_index=True)
    request_id = models.CharField(max_length=64, blank=True, db_index=True)
    input = models.JSONField(default=dict, blank=True)
    output = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'run_traces'
        ordering = ['-created_at']


class TraceSpan(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    trace = models.ForeignKey(RunTrace, on_delete=models.CASCADE, related_name='spans')
    parent_span_id = models.UUIDField(null=True, blank=True)
    name = models.CharField(max_length=160)
    kind = models.CharField(max_length=50, default='internal')
    status = models.CharField(max_length=20, default='running')
    attributes = models.JSONField(default=dict, blank=True)
    input = models.JSONField(default=dict, blank=True)
    output = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'trace_spans'
        ordering = ['started_at']


class KnowledgeBase(TimeStampedModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE,
                                     related_name='knowledge_bases')
    name = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    embedding_provider = models.CharField(max_length=100, blank=True)
    embedding_model = models.CharField(max_length=160, blank=True)
    chunk_size = models.PositiveIntegerField(default=800)
    chunk_overlap = models.PositiveIntegerField(default=100)
    access_policy = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'knowledge_bases'
        constraints = [models.UniqueConstraint(
            fields=['organization', 'name'], name='unique_org_knowledge_base')]


class KnowledgeDocument(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        INDEXING = 'indexing', 'Indexing'
        READY = 'ready', 'Ready'
        FAILED = 'failed', 'Failed'

    knowledge_base = models.ForeignKey(KnowledgeBase, on_delete=models.CASCADE,
                                       related_name='documents')
    title = models.CharField(max_length=300)
    source_type = models.CharField(max_length=30, default='text')
    source_uri = models.CharField(max_length=1000, blank=True)
    content = models.TextField(blank=True)
    checksum = models.CharField(max_length=64, blank=True, db_index=True)
    status = models.CharField(max_length=20, choices=Status.choices,
                              default=Status.PENDING)
    metadata = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True)

    class Meta:
        db_table = 'knowledge_documents'


class KnowledgeChunk(models.Model):
    document = models.ForeignKey(KnowledgeDocument, on_delete=models.CASCADE,
                                 related_name='chunks')
    position = models.PositiveIntegerField()
    content = models.TextField()
    token_count = models.PositiveIntegerField(default=0)
    embedding = models.JSONField(default=list, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'knowledge_chunks'
        ordering = ['position']
        constraints = [models.UniqueConstraint(
            fields=['document', 'position'], name='unique_document_chunk_position')]


class EvaluationSuite(TimeStampedModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE,
                                     related_name='evaluation_suites')
    name = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    target_type = models.CharField(max_length=30, default='agent')
    target_id = models.CharField(max_length=160, blank=True)
    evaluators = models.JSONField(default=list, blank=True)
    quality_gate = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'evaluation_suites'


class EvaluationCase(TimeStampedModel):
    suite = models.ForeignKey(EvaluationSuite, on_delete=models.CASCADE,
                              related_name='cases')
    name = models.CharField(max_length=160)
    input = models.JSONField(default=dict)
    expected = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(default=list, blank=True)

    class Meta:
        db_table = 'evaluation_cases'


class EvaluationRun(models.Model):
    suite = models.ForeignKey(EvaluationSuite, on_delete=models.CASCADE,
                              related_name='runs')
    status = models.CharField(max_length=20, default='pending')
    target_version = models.CharField(max_length=100, blank=True)
    score = models.DecimalField(max_digits=8, decimal_places=4, null=True)
    passed = models.BooleanField(null=True)
    results = models.JSONField(default=list, blank=True)
    error = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True,
                                   on_delete=models.SET_NULL)
    execution_run = models.OneToOneField(
        'execution.Run', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='evaluation_record')
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'evaluation_runs'
        ordering = ['-created_at']


class Connector(TimeStampedModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE,
                                     related_name='connectors')
    name = models.CharField(max_length=160)
    connector_type = models.CharField(max_length=80)
    endpoint = models.CharField(max_length=1000, blank=True)
    secret_ref = models.CharField(max_length=200, blank=True)
    config = models.JSONField(default=dict, blank=True)
    scopes = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'connectors'


class AutomationTrigger(TimeStampedModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE,
                                     related_name='automation_triggers')
    name = models.CharField(max_length=160)
    trigger_type = models.CharField(max_length=30, default='webhook')
    target_type = models.CharField(max_length=30)
    target_id = models.CharField(max_length=160)
    schedule = models.CharField(max_length=120, blank=True)
    event_name = models.CharField(max_length=160, blank=True)
    input_mapping = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    last_triggered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'automation_triggers'
