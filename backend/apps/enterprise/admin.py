from django.contrib import admin

from .models import (
    AuditLog, Connector, EvaluationCase, EvaluationRun,
    EvaluationSuite, KnowledgeBase, KnowledgeChunk, KnowledgeDocument,
    ExternalIdentity, GovernancePolicy, IdentityProvider, Membership, Organization, ProviderConfig, QuotaPolicy, RunTrace,
    SecretReference, TraceSpan, UsageRecord,
)

for model in (
    Organization, Membership, AuditLog, QuotaPolicy, UsageRecord, ProviderConfig,
    SecretReference, RunTrace, TraceSpan, KnowledgeBase, KnowledgeDocument,
    KnowledgeChunk, EvaluationSuite, EvaluationCase, EvaluationRun, Connector,
    IdentityProvider, ExternalIdentity, GovernancePolicy,
):
    admin.site.register(model)
