from django.db.models import Q

from apps.agents.models import Agent
from apps.applications.models import Skill
from apps.enterprise.models import EvaluationRun, EvaluationSuite
from modules.catalog.errors import InvalidApplicationDefinition, QualityGateNotPassed


class DjangoCatalogDomainPort:
    def enforce_production_quality_gate(
        self, *, organization_id, target_type, target_id, revision_id
    ):
        suites = EvaluationSuite.objects.filter(
            organization_id=organization_id,
            target_type=target_type,
            target_id=str(target_id),
        ).exclude(quality_gate={})
        failed = []
        for suite in suites:
            latest = EvaluationRun.objects.filter(
                suite=suite,
                target_version=str(revision_id),
                status="completed",
            ).order_by("-created_at").first()
            if latest is None or latest.passed is not True:
                failed.append(suite.name)
        if failed:
            raise QualityGateNotPassed(
                "Production deployment requires passing evaluations: "
                + ", ".join(failed)
            )

    def validate_chat_references(self, application, definition):
        agent_ids = {binding.agent_id for binding in definition.agent_bindings}
        allowed_agents = set(Agent.objects.filter(
            Q(organization=application.organization) | Q(is_public=True),
            id__in=agent_ids,
            is_active=True,
        ).values_list("id", flat=True))
        if agent_ids != allowed_agents:
            raise InvalidApplicationDefinition(
                "Chat definition references unavailable agents.",
                errors=[{
                    "field": "agent_bindings",
                    "code": "invalid_reference",
                    "message": "Agent is unavailable in this organization.",
                }],
            )
        skill_ids = {binding.skill_id for binding in definition.skill_bindings}
        allowed_skills = {str(value) for value in Skill.objects.filter(
            Q(organization=application.organization) |
            Q(visibility=Skill.Visibility.PUBLIC),
            id__in=skill_ids,
            is_active=True,
        ).values_list("id", flat=True)}
        if skill_ids != allowed_skills:
            raise InvalidApplicationDefinition(
                "Chat definition references unavailable skills.",
                errors=[{
                    "field": "skill_bindings",
                    "code": "invalid_reference",
                    "message": "Skill is unavailable in this organization.",
                }],
            )
