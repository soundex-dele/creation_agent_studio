import hashlib
import json
import time
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, OperationalError, transaction
from django.db.models import Q
from django.utils import timezone
from jsonschema import SchemaError, ValidationError as JsonSchemaValidationError
from jsonschema.validators import validator_for

from apps.agents.models import Agent
from apps.enterprise.services import enforce_quota
from modules.catalog.models import (
    AgentDeployment,
    Application,
    ApplicationDeployment,
)
from modules.execution.models import IdempotencyRecord, Run

from .errors import (
    DeploymentUnavailable,
    IdempotencyKeyReused,
    InvalidExecutionDefinition,
)
from .runs import create_run


CREATE_APPLICATION_RUN_OPERATION = "application.run.create"
CREATE_AGENT_RUN_OPERATION = "agent.run.create"
CREATE_WORKFLOW_RUN_OPERATION = "workflow.run.create"


def _fingerprint(*, application_id, environment, input_data, priority):
    document = {
        "application_id": str(application_id),
        "environment": environment,
        "input": input_data,
        "priority": priority,
    }
    encoded = json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_replay(*, organization_id, actor_id, operation, key, fingerprint):
    record = IdempotencyRecord.objects.for_organization(organization_id).filter(
        actor_id=actor_id,
        operation=operation,
        key=key,
    ).first()
    if record is None:
        return None
    if record.request_fingerprint != fingerprint:
        raise IdempotencyKeyReused(
            "The idempotency key was already used with a different request"
        )
    run_id = record.response_body.get("run_id")
    if record.status != IdempotencyRecord.Status.COMPLETED or not run_id:
        return None
    return Run.objects.for_organization(organization_id).get(pk=run_id)


def _definition_values(revision):
    content = revision.content
    if not isinstance(content, dict):
        raise InvalidExecutionDefinition("Application Revision content must be an object")
    executor_kind = content.get("executor_kind")
    if executor_kind not in Run.ExecutorKind.values:
        raise InvalidExecutionDefinition(
            "Application Revision must declare a supported executor_kind"
        )
    executor_key = content.get("executor_key")
    if not isinstance(executor_key, str) or not executor_key.strip():
        raise InvalidExecutionDefinition(
            "Application Revision must declare a non-empty executor_key"
        )
    registered = getattr(settings, "EXECUTION_CHILD_ADAPTERS", {}).get(
        executor_kind, {}
    )
    if executor_key not in registered:
        raise InvalidExecutionDefinition(
            f"Executor {executor_kind}/{executor_key} is not registered"
        )
    retry_policy = content.get("retry_policy") or {}
    if not isinstance(retry_policy, dict):
        raise InvalidExecutionDefinition("retry_policy must be an object")
    try:
        max_attempts = int(retry_policy.get("max_attempts", 3))
    except (TypeError, ValueError) as exc:
        raise InvalidExecutionDefinition("max_attempts must be an integer") from exc
    if not 1 <= max_attempts <= 100:
        raise InvalidExecutionDefinition("max_attempts must be between 1 and 100")
    retry_safe = retry_policy.get("retry_safe", True)
    if not isinstance(retry_safe, bool):
        raise InvalidExecutionDefinition("retry_safe must be a boolean")
    return executor_kind, executor_key, max_attempts, retry_safe


def _validate_input(content, input_data):
    schema = content.get("input_schema") or {}
    if not isinstance(schema, dict):
        raise InvalidExecutionDefinition("input_schema must be an object")
    try:
        validator_type = validator_for(schema)
        validator_type.check_schema(schema)
        validator_type(schema).validate(input_data)
    except (SchemaError, JsonSchemaValidationError) as exc:
        raise InvalidExecutionDefinition(f"Run input does not satisfy input_schema: {exc.message}") from exc


def _effective_config(content, config_override):
    defaults = content.get("default_config") or {}
    if not isinstance(defaults, dict) or not isinstance(config_override, dict):
        raise InvalidExecutionDefinition("default_config and config_override must be objects")
    return {**defaults, **config_override}


def _start_once(
    *,
    organization_id,
    application_id,
    actor,
    environment,
    input_data,
    priority,
    idempotency_key,
    fingerprint,
):
    replay = _load_replay(
        organization_id=organization_id,
        actor_id=actor.id,
        operation=CREATE_APPLICATION_RUN_OPERATION,
        key=idempotency_key,
        fingerprint=fingerprint,
    )
    if replay is not None:
        return replay, True

    with transaction.atomic():
        application = (
            Application.objects.for_organization(organization_id)
            .select_for_update()
            .filter(pk=application_id, is_active=True)
            .first()
        )
        if application is None:
            raise DeploymentUnavailable("Application is not available")
        enforce_quota(application.organization)
        deployment = (
            ApplicationDeployment.objects.for_organization(organization_id)
            .select_related("revision")
            .filter(application=application, environment=environment)
            .first()
        )
        if deployment is None:
            raise DeploymentUnavailable(
                f"Application has no {environment} deployment"
            )
        revision = deployment.revision
        if (
            revision.organization_id != application.organization_id
            or revision.application_id != application.id
        ):
            raise InvalidExecutionDefinition(
                "Deployment revision crosses an application or organization boundary"
            )

        replay = _load_replay(
            organization_id=organization_id,
            actor_id=actor.id,
            operation=CREATE_APPLICATION_RUN_OPERATION,
            key=idempotency_key,
            fingerprint=fingerprint,
        )
        if replay is not None:
            return replay, True

        executor_kind, executor_key, max_attempts, retry_safe = _definition_values(revision)
        _validate_input(revision.content, input_data)
        effective_config = _effective_config(
            revision.content, deployment.config_override
        )
        record = IdempotencyRecord.objects.create(
            organization_id=organization_id,
            actor=actor,
            operation=CREATE_APPLICATION_RUN_OPERATION,
            key=idempotency_key,
            request_fingerprint=fingerprint,
            expires_at=timezone.now() + timedelta(hours=24),
        )
        run = create_run(
            organization=application.organization,
            owner=actor,
            executor_kind=executor_kind,
            executor_key=executor_key,
            source_type="application",
            source_id=application.id,
            definition_snapshot={
                "application_id": str(application.id),
                "application_revision_id": str(revision.id),
                "application_revision_no": revision.revision_no,
                "application_content_hash": revision.content_hash,
                "application_schema_version": revision.schema_version,
                "deployment_id": str(deployment.id),
                "deployment_environment": deployment.environment,
                "deployment_version": deployment.version,
                "config_override": deployment.config_override,
                "effective_config": effective_config,
                "content": revision.content,
            },
            input_data=input_data,
            priority=priority,
            max_attempts=max_attempts,
            retry_safe=retry_safe,
        )
        record.status = IdempotencyRecord.Status.COMPLETED
        record.response_status = 202
        record.response_body = {"run_id": str(run.id)}
        record.save(update_fields=("status", "response_status", "response_body"))
    return run, False


def start_application_run(
    *,
    organization_id,
    application_id,
    actor,
    environment,
    input_data,
    priority,
    idempotency_key,
    max_retries=4,
):
    if not idempotency_key or len(idempotency_key) > 160:
        raise ValueError("Idempotency-Key must contain between 1 and 160 characters")
    fingerprint = _fingerprint(
        application_id=application_id,
        environment=environment,
        input_data=input_data,
        priority=priority,
    )
    for retry_no in range(max_retries):
        try:
            return _start_once(
                organization_id=organization_id,
                application_id=application_id,
                actor=actor,
                environment=environment,
                input_data=input_data,
                priority=priority,
                idempotency_key=idempotency_key,
                fingerprint=fingerprint,
            )
        except OperationalError as exc:
            is_busy = "locked" in str(exc).lower() or "busy" in str(exc).lower()
            if not is_busy or retry_no + 1 >= max_retries:
                raise
        except IntegrityError:
            if retry_no + 1 >= max_retries:
                raise
        time.sleep(0.01 * (2**retry_no))

    raise RuntimeError("Unable to create run after retries")


def start_agent_run(
    *,
    organization_id,
    agent_id,
    actor,
    environment,
    input_data,
    idempotency_key,
    source_type="agent",
    source_id="",
    priority=0,
):
    """Create the sole durable execution representation for an Agent call."""
    if not idempotency_key or len(idempotency_key) > 160:
        raise ValueError("Idempotency-Key must contain between 1 and 160 characters")
    fingerprint = hashlib.sha256(json.dumps({
        "agent_id": str(agent_id),
        "environment": environment,
        "input": input_data,
        "source_type": source_type,
        "source_id": str(source_id),
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    replay = _load_replay(
        organization_id=organization_id,
        actor_id=actor.id,
        operation=CREATE_AGENT_RUN_OPERATION,
        key=idempotency_key,
        fingerprint=fingerprint,
    )
    if replay is not None:
        return replay, True
    with transaction.atomic():
        agent = Agent.objects.select_for_update().filter(
            Q(organization_id=organization_id) | Q(organization__isnull=True, is_public=True),
            pk=agent_id,
            is_active=True,
        ).first()
        if agent is None:
            raise DeploymentUnavailable("Agent is not available")
        deployment = None
        if agent.organization_id is not None:
            deployment = AgentDeployment.objects.for_organization(organization_id).select_related(
                "revision"
            ).filter(agent=agent, environment=environment).first()
        if agent.organization_id is not None and deployment is None:
            raise DeploymentUnavailable(f"Agent has no {environment} deployment")
        registered = getattr(settings, "EXECUTION_CHILD_ADAPTERS", {}).get("agent", {})
        executor_key = "agent-completion"
        if executor_key not in registered:
            raise InvalidExecutionDefinition("Agent executor is not registered")
        from apps.enterprise.models import Organization
        run_organization = Organization.objects.get(pk=organization_id)
        enforce_quota(run_organization)
        agent_definition = (
            deployment.revision.content if deployment is not None else {
                "system_prompt": agent.system_prompt,
                "model_config": agent.model_config,
                "tool_config": agent.tool_config,
                "skill_config": agent.skill_config,
                "knowledge_config": agent.knowledge_config,
                "guardrail_config": agent.guardrail_config,
                "workflow_config": agent.workflow_config,
            }
        )
        record = IdempotencyRecord.objects.create(
            organization_id=organization_id,
            actor=actor,
            operation=CREATE_AGENT_RUN_OPERATION,
            key=idempotency_key,
            request_fingerprint=fingerprint,
            expires_at=timezone.now() + timedelta(hours=24),
        )
        run = create_run(
            organization=run_organization,
            owner=actor,
            executor_kind=Run.ExecutorKind.AGENT,
            executor_key=executor_key,
            source_type=source_type,
            source_id=source_id or agent.id,
            definition_snapshot={
                "agent_id": str(agent.id),
                "agent_revision_id": str(deployment.revision_id) if deployment else None,
                "agent_revision_no": deployment.revision.revision_no if deployment else None,
                "agent_content_hash": deployment.revision.content_hash if deployment else "",
                "deployment_id": str(deployment.id) if deployment else None,
                "deployment_environment": deployment.environment if deployment else "global",
                "deployment_version": deployment.version if deployment else 0,
                "agent_definition": agent_definition,
                "effective_config": {
                    **dict(agent_definition.get("model_config") or {}),
                    **(dict(deployment.config_override or {}) if deployment else {}),
                },
            },
            input_data=input_data,
            priority=priority,
            max_attempts=3,
            retry_safe=True,
        )
        record.status = IdempotencyRecord.Status.COMPLETED
        record.response_status = 202
        record.response_body = {"run_id": str(run.id)}
        record.save(update_fields=("status", "response_status", "response_body"))
    return run, False


def start_workflow_run(
    *, organization, workflow_id, workflow_name, steps, actor,
    input_data, priority, idempotency_key,
):
    """Create the canonical durable representation of a Workflow execution."""
    if not idempotency_key or len(idempotency_key) > 160:
        raise ValueError("Idempotency-Key must contain between 1 and 160 characters")
    fingerprint = hashlib.sha256(json.dumps({
        "workflow_id": str(workflow_id),
        "steps": steps,
        "input": input_data,
        "priority": priority,
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    replay = _load_replay(
        organization_id=organization.id,
        actor_id=actor.id,
        operation=CREATE_WORKFLOW_RUN_OPERATION,
        key=idempotency_key,
        fingerprint=fingerprint,
    )
    if replay is not None:
        return replay, True
    with transaction.atomic():
        enforce_quota(organization)
        replay = _load_replay(
            organization_id=organization.id,
            actor_id=actor.id,
            operation=CREATE_WORKFLOW_RUN_OPERATION,
            key=idempotency_key,
            fingerprint=fingerprint,
        )
        if replay is not None:
            return replay, True
        record = IdempotencyRecord.objects.create(
            organization=organization,
            actor=actor,
            operation=CREATE_WORKFLOW_RUN_OPERATION,
            key=idempotency_key,
            request_fingerprint=fingerprint,
            expires_at=timezone.now() + timedelta(hours=24),
        )
        run = create_run(
            organization=organization,
            owner=actor,
            executor_kind=Run.ExecutorKind.WORKFLOW,
            executor_key="workflow-sequential",
            source_type="workflow",
            source_id=workflow_id,
            definition_snapshot={
                "workflow_id": str(workflow_id),
                "workflow_name": workflow_name,
                "workflow_steps": steps,
            },
            input_data=input_data,
            priority=priority,
            max_attempts=1,
            retry_safe=False,
        )
        record.status = IdempotencyRecord.Status.COMPLETED
        record.response_status = 202
        record.response_body = {"run_id": str(run.id)}
        record.save(update_fields=("status", "response_status", "response_body"))
    return run, False
