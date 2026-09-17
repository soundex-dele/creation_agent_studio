import hashlib
import math
import os
import re
import ipaddress
import json
import socket
import urllib.error
import urllib.parse
import urllib.request
import uuid
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import Throttled

from .models import QuotaPolicy, RunTrace, UsageRecord


def enforce_quota(organization):
    if organization is None:
        return
    quota, _ = QuotaPolicy.objects.get_or_create(organization=organization)
    now = timezone.now()
    totals = UsageRecord.objects.filter(
        organization=organization,
        created_at__year=now.year,
        created_at__month=now.month,
    ).aggregate(tokens=Sum('total_tokens'), cost=Sum('cost'))
    from modules.execution.models import Run
    running = Run.objects.for_organization(organization.id).filter(
        status__in=[Run.Status.QUEUED, Run.Status.RUNNING,
                    Run.Status.WAITING_INPUT, Run.Status.WAITING_CHILDREN,
                    Run.Status.CANCELLING],
    ).count()
    if quota.hard_limit and (totals['tokens'] or 0) >= quota.monthly_token_limit:
        raise Throttled(detail='Monthly token quota exceeded.')
    if quota.hard_limit and Decimal(totals['cost'] or 0) >= quota.monthly_cost_limit:
        raise Throttled(detail='Monthly cost quota exceeded.')
    if running >= quota.max_concurrent_runs:
        raise Throttled(detail='Concurrent run quota exceeded.')


def record_usage(*, organization, user, resource_type, resource_id='', usage=None,
                 provider='', model='', cost=0, latency_ms=0, status='success',
                 metadata=None):
    if organization is None:
        return None
    usage = usage or {}
    return UsageRecord.objects.create(
        organization=organization,
        user=user,
        resource_type=resource_type,
        resource_id=str(resource_id or ''),
        provider=provider,
        model=model,
        prompt_tokens=int(usage.get('prompt_tokens', 0) or 0),
        completion_tokens=int(usage.get('completion_tokens', 0) or 0),
        total_tokens=int(usage.get('total_tokens', 0) or 0),
        cost=cost,
        latency_ms=max(0, int(latency_ms)),
        status=status,
        metadata=metadata or {},
    )


def resolve_secret(reference):
    """Resolve environment-backed secrets without ever returning them via API."""
    if reference.backend == 'environment':
        value = os.environ.get(reference.reference, '')
        if not value:
            raise RuntimeError(f'Secret environment variable is not configured: {reference.reference}')
        return value
    raise RuntimeError(
        f'Secret backend {reference.backend!r} requires an external secrets adapter.')


def _validated_connector_url(connector):
    """Validate connector egress against SSRF and organization policy."""
    parsed = urllib.parse.urlparse(connector.endpoint)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        raise ValueError('Connector endpoint must be an HTTP(S) URL.')
    policy = getattr(connector.organization, 'governance_policy', None)
    allowlist = policy.network_allowlist if policy else []
    hostname = parsed.hostname.lower().rstrip('.')
    if allowlist and not any(
            hostname == str(item).lower().rstrip('.') or
            hostname.endswith('.' + str(item).lower().lstrip('*.').rstrip('.'))
            for item in allowlist):
        from rest_framework.exceptions import PermissionDenied
        raise PermissionDenied('Connector host is not in the network allowlist.')
    try:
        addresses = {result[4][0] for result in socket.getaddrinfo(hostname, parsed.port or 443)}
    except socket.gaierror as exc:
        raise ValueError('Connector hostname cannot be resolved.') from exc
    for value in addresses:
        address = ipaddress.ip_address(value)
        if (address.is_private or address.is_loopback or address.is_link_local or
                address.is_multicast or address.is_reserved or address.is_unspecified):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('Connector endpoints may not target private networks.')
    return connector.endpoint


def invoke_connector(connector, payload):
    """Invoke a generic webhook connector without exposing referenced secrets."""
    if not connector.is_active:
        raise ValueError('Connector is disabled.')
    url = _validated_connector_url(connector)
    headers = {'Content-Type': 'application/json', 'User-Agent': 'Creation-Agent-Studio/1.0'}
    if connector.secret_ref:
        reference = connector.organization.secret_references.filter(
            name=connector.secret_ref).first()
        if reference is None:
            raise ValueError('Connector secret reference does not exist.')
        secret = resolve_secret(reference)
        auth_scheme = str(connector.config.get('auth_scheme') or 'Bearer')
        headers['Authorization'] = f'{auth_scheme} {secret}'
    headers.update({str(key): str(value) for key, value in
                    (connector.config.get('headers') or {}).items()
                    if str(key).lower() not in ('host', 'content-length', 'authorization')})
    method = str(connector.config.get('method') or 'POST').upper()
    if method not in ('POST', 'PUT', 'PATCH'):
        raise ValueError('Connector method must be POST, PUT or PATCH.')
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode('utf-8'), headers=headers, method=method)
    try:
        with urllib.request.urlopen(
                request, timeout=min(30, max(1, int(connector.config.get('timeout', 10))))) as response:
            body = response.read(1024 * 1024)
            content_type = response.headers.get_content_type()
            value = json.loads(body) if body and content_type == 'application/json' \
                else body.decode('utf-8', errors='replace')
            return {'status_code': response.status, 'data': value}
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f'Connector returned HTTP {exc.code}.') from exc


def resolve_provider(organization, model=''):
    providers = organization.providers.filter(is_active=True).order_by('-routing_weight', 'id')
    if model:
        preferred = [provider for provider in providers
                     if not provider.available_models or model in provider.available_models]
        provider = preferred[0] if preferred else None
    else:
        provider = providers.first()
    if provider is None:
        return None
    secret = organization.secret_references.filter(name=provider.secret_ref).first() \
        if provider.secret_ref else None
    return {
        'provider': provider,
        'api_key': resolve_secret(secret) if secret else '',
        'model': model or (provider.available_models[0]
                           if provider.available_models else ''),
    }


def evaluate_value(actual, expected, evaluator):
    kind = evaluator.get('type', 'exact') if isinstance(evaluator, dict) else str(evaluator)
    if kind == 'contains':
        passed = str(expected) in str(actual)
    elif kind == 'regex':
        passed = re.search(str(expected), str(actual)) is not None
    elif kind == 'json_equal':
        passed = actual == expected
    else:
        passed = str(actual).strip() == str(expected).strip()
    return {'type': kind, 'passed': passed, 'score': 1.0 if passed else 0.0}


@transaction.atomic
def start_evaluation(suite, actor, target_version="", environment="staging"):
    """Create a durable Evaluation Run pinned to an immutable target revision."""

    from django.conf import settings

    from apps.agents.models import Agent
    from apps.applications.models import Application
    from modules.catalog.models import (
        AgentRevision,
        ApplicationRevision,
        DeploymentEnvironment,
    )
    from modules.execution.application.errors import DeploymentUnavailable
    from modules.execution.application.runs import create_run
    from modules.execution.application.start_runs import freeze_skill_revisions
    from modules.execution.models import Run

    target_type = str(suite.target_type or "").lower()
    if environment not in DeploymentEnvironment.values:
        raise ValueError("environment must be development, staging, or production")
    revision_id = None
    if target_version:
        try:
            revision_id = uuid.UUID(str(target_version))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("target_version must be a Revision UUID") from exc
    try:
        target_id = int(suite.target_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("Evaluation target_id must identify an Agent or Application") from exc
    if target_type == "agent":
        identity = Agent.objects.filter(
            pk=target_id,
            organization_id=suite.organization_id,
            is_active=True,
        ).first()
        revisions = AgentRevision.objects.filter(
            agent=identity, organization_id=suite.organization_id
        ) if identity else AgentRevision.objects.none()
        revision = (
            revisions.filter(pk=revision_id).first()
            if revision_id
            else revisions.order_by("-revision_no").first()
        )
        executor_kind = Run.ExecutorKind.AGENT
        executor_key = "agent-completion"
        definition_snapshot = {
            "agent_id": str(identity.id) if identity else "",
            "agent_revision_id": str(revision.id) if revision else "",
            "agent_revision_no": revision.revision_no if revision else 0,
            "agent_content_hash": revision.content_hash if revision else "",
            "agent_definition": revision.content if revision else {},
            "effective_config": (
                dict((revision.content or {}).get("model_config") or {})
                if revision else {}
            ),
            "governance": execution_governance_snapshot(suite.organization),
        }
        max_attempts, retry_safe = 3, True
    elif target_type == "application":
        identity = Application.objects.filter(
            pk=target_id,
            organization_id=suite.organization_id,
            is_active=True,
        ).first()
        revisions = ApplicationRevision.objects.filter(
            application=identity, organization_id=suite.organization_id
        ) if identity else ApplicationRevision.objects.none()
        revision = (
            revisions.filter(pk=revision_id).first()
            if revision_id
            else revisions.order_by("-revision_no").first()
        )
        content = revision.content if revision else {}
        executor_kind = content.get("executor_kind", "")
        executor_key = content.get("executor_key", "")
        retry_policy = content.get("retry_policy") or {}
        max_attempts = int(retry_policy.get("max_attempts", 3))
        retry_safe = bool(retry_policy.get("retry_safe", True))
        definition_snapshot = {
            "application_id": str(identity.id) if identity else "",
            "application_revision_id": str(revision.id) if revision else "",
            "application_revision_no": revision.revision_no if revision else 0,
            "application_content_hash": revision.content_hash if revision else "",
            "content": content,
            "effective_config": dict(content.get("default_config") or {}),
            "governance": execution_governance_snapshot(suite.organization),
        }
    else:
        raise ValueError("Evaluation target_type must be agent or application")

    if revision is None:
        raise ValueError("Evaluation target revision does not exist")
    if executor_key not in getattr(settings, "EXECUTION_CHILD_ADAPTERS", {}).get(
        executor_kind, {}
    ):
        raise ValueError(
            f"Evaluation target executor is not registered: {executor_kind}/{executor_key}"
        )
    try:
        definition_snapshot["skill_revisions"] = freeze_skill_revisions(
            organization_id=suite.organization_id,
            environment=environment,
            content=revision.content,
        )
    except DeploymentUnavailable as exc:
        raise ValueError(str(exc)) from exc
    cases = [
        {
            "id": str(case.id),
            "name": case.name,
            "input": case.input,
            "expected": case.expected,
            "tags": case.tags,
        }
        for case in suite.cases.order_by("id")
    ]
    if not cases:
        raise ValueError("Evaluation suite must contain at least one case")

    evaluation = suite.runs.create(
        created_by=actor,
        status="queued",
        target_version=str(revision.id),
    )
    run = create_run(
        organization=suite.organization,
        owner=actor,
        executor_kind=Run.ExecutorKind.EVALUATION,
        executor_key="evaluation-suite",
        source_type="evaluation",
        source_id=evaluation.id,
        definition_snapshot={
            "evaluation_run_id": str(evaluation.id),
            "suite_id": str(suite.id),
            "target_type": target_type,
            "target_id": str(suite.target_id),
            "target_version": str(revision.id),
            "target_environment": environment,
            "evaluators": suite.evaluators,
            "quality_gate": suite.quality_gate,
            "cases": cases,
            "target": {
                "executor_kind": executor_kind,
                "executor_key": executor_key,
                "max_attempts": max_attempts,
                "retry_safe": retry_safe,
                "definition_snapshot": definition_snapshot,
            },
        },
        input_data={},
        max_attempts=3,
        retry_safe=True,
    )
    evaluation.execution_run = run
    evaluation.save(update_fields=["execution_run"])
    return evaluation


_PII_PATTERNS = [
    re.compile(r'\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b'),
    re.compile(r'\b1[3-9]\d{9}\b'),
    re.compile(r'\b\d{17}[\dXx]\b'),
]


def _apply_content_guardrails(policy, content):
    if isinstance(content, dict):
        return {key: _apply_content_guardrails(policy, value)
                for key, value in content.items()}
    if isinstance(content, list):
        return [_apply_content_guardrails(policy, value) for value in content]
    if not isinstance(content, str):
        return content
    lowered = content.lower()
    matched = [term for term in policy.blocked_terms
               if str(term).lower() in lowered]
    if matched:
        from rest_framework.exceptions import PermissionDenied
        raise PermissionDenied(f'Input blocked by governance policy: {matched[0]}')
    if policy.redact_pii:
        for pattern in _PII_PATTERNS:
            content = pattern.sub('[REDACTED]', content)
    return content


def apply_input_guardrails(organization, content):
    if organization is None:
        return content
    from .models import GovernancePolicy
    policy, _ = GovernancePolicy.objects.get_or_create(organization=organization)
    return _apply_content_guardrails(policy, content)


def apply_output_guardrails(organization, content):
    return apply_input_guardrails(organization, content)


def enforce_model_policy(organization, model):
    if organization is None or not model:
        return model
    from .models import GovernancePolicy
    policy, _ = GovernancePolicy.objects.get_or_create(organization=organization)
    if policy.allowed_models and model not in {str(value) for value in policy.allowed_models}:
        from rest_framework.exceptions import PermissionDenied
        raise PermissionDenied(f'Model is not allowlisted: {model}')
    return model


def execution_governance_snapshot(organization):
    """Freeze runtime-relevant governance values into a Run definition."""
    if organization is None:
        return {}
    from .models import GovernancePolicy
    policy, _ = GovernancePolicy.objects.get_or_create(organization=organization)
    return {
        'require_tool_approval': policy.require_tool_approval,
        'allowed_models': list(policy.allowed_models),
        'allowed_tool_patterns': list(policy.allowed_tool_patterns),
        'blocked_tool_patterns': list(policy.blocked_tool_patterns),
        'network_allowlist': list(policy.network_allowlist),
        'export_enabled': policy.export_enabled,
    }


def tenant_working_directory(organization):
    from django.conf import settings
    if organization is None:
        return ''
    root = settings.AGENT_WORKSPACE_ROOT.resolve()
    target = (root / str(organization.id)).resolve()
    if root not in target.parents:
        raise RuntimeError('Invalid tenant workspace path.')
    target.mkdir(parents=True, exist_ok=True)
    return str(target)


def enforce_skill_policy(organization, skills):
    if organization is None:
        return skills
    from .models import GovernancePolicy
    policy, _ = GovernancePolicy.objects.get_or_create(organization=organization)
    blocked = [re.compile(pattern) for pattern in policy.blocked_tool_patterns]
    allowed = [re.compile(pattern) for pattern in policy.allowed_tool_patterns]
    for skill in skills:
        if any(pattern.search(skill) for pattern in blocked):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied(f'Skill blocked by governance policy: {skill}')
        if allowed and not any(pattern.search(skill) for pattern in allowed):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied(f'Skill is not allowlisted: {skill}')
    return skills


def dispatch_automation(trigger, user, payload=None, scheduled_for=None):
    from .models import RunTrace
    payload = {**dict(trigger.input_mapping or {}), **dict(payload or {})}
    occurrence = scheduled_for or timezone.now()
    occurrence_key = occurrence.replace(second=0, microsecond=0).isoformat()
    trace = RunTrace.objects.create(
        organization=trigger.organization, user=user, kind='automation',
        resource_id=str(trigger.id), status=RunTrace.Status.RUNNING,
        input=payload, started_at=timezone.now())
    try:
        if trigger.target_type == 'agent':
            from apps.agents.models import Agent
            from modules.execution.application.start_runs import start_agent_run
            agent = Agent.objects.get(id=trigger.target_id,
                                      organization=trigger.organization)
            run, _ = start_agent_run(
                organization_id=trigger.organization_id,
                agent_id=agent.id,
                actor=user,
                environment='production',
                input_data=payload,
                idempotency_key=f'automation:{trigger.id}:{occurrence_key}',
            )
            trace.status = RunTrace.Status.QUEUED
            trace.output = {'run_id': str(run.id)}
        elif trigger.target_type == 'application':
            from apps.applications.models import Application
            from modules.execution.application.start_runs import start_application_run
            application = Application.objects.get(
                id=trigger.target_id, organization=trigger.organization)
            run, _ = start_application_run(
                organization_id=trigger.organization_id,
                application_id=application.id,
                actor=user,
                environment='production',
                input_data=payload,
                priority=0,
                idempotency_key=f'automation:{trigger.id}:{occurrence_key}',
            )
            trace.status = RunTrace.Status.QUEUED
            trace.output = {'run_id': str(run.id)}
        elif trigger.target_type == 'workflow':
            from apps.projects.services.workspace_paths import workflow_working_directory
            from apps.workflows.models import Workflow
            from apps.workflows.views import build_workflow_step_snapshots
            from modules.execution.application.start_runs import start_workflow_run
            from modules.execution.models import Run

            workflow = Workflow.objects.get(
                id=trigger.target_id,
                organization=trigger.organization,
                execution_mode=Workflow.ExecutionMode.AUTOMATIC,
            )
            _steps, snapshots = build_workflow_step_snapshots(workflow)
            run, _ = start_workflow_run(
                organization=trigger.organization,
                workflow_id=workflow.id,
                workflow_name=workflow.name,
                steps=snapshots,
                actor=user,
                input_data=payload,
                priority=0,
                idempotency_key=f'automation:{trigger.id}:{occurrence_key}',
                output_mapping=workflow.output_mapping,
            )
            run_input = dict(run.input or {})
            run_input['working_directory'] = workflow_working_directory(
                user, trigger.organization, run.id
            )
            Run.objects.filter(pk=run.pk).update(input=run_input)
            trace.status = RunTrace.Status.QUEUED
            trace.output = {'run_id': str(run.id)}
        else:
            raise ValueError('Unsupported automation target type.')
    except Exception as exc:
        trace.status = RunTrace.Status.FAILED
        trace.error = str(exc)
    trace.finished_at = timezone.now() if trace.status != RunTrace.Status.QUEUED else None
    trace.save(update_fields=['status', 'output', 'error', 'finished_at'])
    trigger.last_triggered_at = timezone.now()
    trigger.save(update_fields=['last_triggered_at', 'updated_at'])
    return trace


def cron_matches(expression, moment):
    """Match the common five-field cron subset (*, */n, integer, list)."""
    parts = str(expression).split()
    if len(parts) != 5:
        return False
    values = [moment.minute, moment.hour, moment.day, moment.month,
              (moment.weekday() + 1) % 7]

    def matches(part, value):
        if part == '*':
            return True
        if part.startswith('*/'):
            try:
                return value % int(part[2:]) == 0
            except (ValueError, ZeroDivisionError):
                return False
        try:
            return value in {int(item) for item in part.split(',')}
        except ValueError:
            return False
    return all(matches(part, value) for part, value in zip(parts, values))
