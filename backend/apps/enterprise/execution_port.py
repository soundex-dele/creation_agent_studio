from django.db.models import Q

from apps.agents.models import Agent
from apps.applications.models import Application
from apps.enterprise.models import Organization
from apps.enterprise.services import (
    apply_input_guardrails,
    apply_output_guardrails,
    enforce_model_policy,
    enforce_member_token_quota,
    enforce_quota,
    enforce_skill_policy,
    execution_governance_snapshot,
    record_usage,
)


class DjangoExecutionDomainPort:
    """Product-domain operations consumed by the durable execution core."""

    def application_for_update(self, organization_id, application_id):
        return (
            Application.objects.for_organization(organization_id)
            .select_for_update()
            .filter(pk=application_id, is_active=True)
            .first()
        )

    def agent_for_update(self, organization_id, agent_id):
        return Agent.objects.select_for_update().filter(
            Q(organization_id=organization_id) | Q(organization__isnull=True),
            pk=agent_id,
            is_active=True,
        ).first()

    def organization(self, organization_id):
        return Organization.objects.get(pk=organization_id)

    def active_organization_ids(self):
        return Organization.objects.filter(is_active=True).values_list("id", flat=True)

    enforce_quota = staticmethod(enforce_quota)
    enforce_member_token_quota = staticmethod(enforce_member_token_quota)
    enforce_model_policy = staticmethod(enforce_model_policy)
    enforce_skill_policy = staticmethod(enforce_skill_policy)
    governance_snapshot = staticmethod(execution_governance_snapshot)
    apply_input_guardrails = staticmethod(apply_input_guardrails)
    apply_output_guardrails = staticmethod(apply_output_guardrails)
    record_usage = staticmethod(record_usage)
