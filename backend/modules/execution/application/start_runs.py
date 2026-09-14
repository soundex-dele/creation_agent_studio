import hashlib
import json
import time
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, OperationalError, transaction
from django.utils import timezone
from jsonschema import SchemaError, ValidationError as JsonSchemaValidationError
from jsonschema.validators import validator_for

from modules.catalog.models import (
    AgentDeployment,
    ApplicationDeployment,
    DeploymentEnvironment,
    SkillDeployment,
)
from modules.execution.models import IdempotencyRecord, Run

from .errors import (
    DeploymentUnavailable,
    IdempotencyKeyReused,
    InvalidExecutionDefinition,
)
from .ports import execution_domain_port
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


def _skill_policy_keys(bindings):
    values = []
    for binding in bindings or []:
        if isinstance(binding, dict):
            value = (
                binding.get("slug")
                or binding.get("skill_id")
                or binding.get("id")
            )
        else:
            value = binding
        if value:
            values.append(str(value))
    return values


def freeze_skill_revisions(*, organization_id, environment, content):
    """Resolve every Skill binding to one immutable deployed revision."""

    dependencies = content.get("dependencies") or {}
    bindings = content.get("skill_bindings") or dependencies.get("skills") or []
    if not isinstance(bindings, list):
        raise InvalidExecutionDefinition("Skill bindings must be a list")

    normalized = []
    skill_ids = []
    for index, binding in enumerate(bindings):
        if isinstance(binding, dict):
            skill_id = binding.get("skill_id") or binding.get("id")
            binding_config = dict(binding)
        else:
            skill_id = binding
            binding_config = {"skill_id": str(binding)}
        try:
            parsed_id = uuid.UUID(str(skill_id))
        except (TypeError, ValueError, AttributeError) as exc:
            raise InvalidExecutionDefinition(
                f"Skill binding at index {index} must contain a valid skill_id"
            ) from exc
        normalized.append((parsed_id, binding_config))
        skill_ids.append(parsed_id)

    if len(skill_ids) != len(set(skill_ids)):
        raise InvalidExecutionDefinition("Skill bindings must be unique")
    if not skill_ids:
        return []

    deployments = {
        deployment.skill_id: deployment
        for deployment in SkillDeployment.objects.for_organization(organization_id)
        .select_related("revision", "skill")
        .filter(
            skill_id__in=skill_ids,
            skill__is_active=True,
            environment=environment,
        )
    }
    missing = [str(skill_id) for skill_id in skill_ids if skill_id not in deployments]
    if missing:
        raise DeploymentUnavailable(
            f"Skills have no {environment} deployment: {', '.join(missing)}"
        )

    frozen = []
    for skill_id, binding in normalized:
        deployment = deployments[skill_id]
        revision = deployment.revision
        if (
            deployment.organization_id != organization_id
            or revision.organization_id != organization_id
            or revision.skill_id != skill_id
        ):
            raise InvalidExecutionDefinition(
                "Skill deployment crosses a skill or organization boundary"
            )
        frozen.append(
            {
                "skill_id": str(skill_id),
                "skill_slug": deployment.skill.slug,
                "binding": binding,
                "deployment_id": str(deployment.id),
                "deployment_environment": deployment.environment,
                "deployment_version": deployment.version,
                "revision_id": str(revision.id),
                "revision_no": revision.revision_no,
                "content_hash": revision.content_hash,
                "schema_version": revision.schema_version,
                "content": revision.content,
            }
        )
    return frozen


def _enforce_definition_governance(organization, content, effective_config):
    port = execution_domain_port()
    model = str(
        effective_config.get("model")
        or (content.get("model_config") or {}).get("model")
        or ""
    )
    port.enforce_model_policy(organization, model)
    dependencies = content.get("dependencies") or {}
    skill_bindings = content.get("skill_bindings") or dependencies.get("skills") or []
    port.enforce_skill_policy(organization, _skill_policy_keys(skill_bindings))
    return port.governance_snapshot(organization)


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
        port = execution_domain_port()
        application = port.application_for_update(organization_id, application_id)
        if application is None:
            raise DeploymentUnavailable("Application is not available")
        port.enforce_quota(application.organization)
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
        skill_revisions = freeze_skill_revisions(
            organization_id=organization_id,
            environment=environment,
            content=revision.content,
        )
        governance = _enforce_definition_governance(
            application.organization, revision.content, effective_config
        )
        guarded_input = port.apply_input_guardrails(application.organization, input_data)
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
                "governance": governance,
                "skill_revisions": skill_revisions,
                "content": revision.content,
            },
            input_data=guarded_input,
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
    idempotency_input_data=None,
):
    """Create the sole durable execution representation for an Agent call."""
    if not idempotency_key or len(idempotency_key) > 160:
        raise ValueError("Idempotency-Key must contain between 1 and 160 characters")
    fingerprint = hashlib.sha256(json.dumps({
        "agent_id": str(agent_id),
        "environment": environment,
        # Callers such as Conversation build part of the Run input from
        # server-side history. That derived history can change after the first
        # successful request and must not make an otherwise identical HTTP
        # retry look like a conflicting idempotency-key reuse.
        "input": (
            input_data
            if idempotency_input_data is None
            else idempotency_input_data
        ),
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
        port = execution_domain_port()
        agent = port.agent_for_update(organization_id, agent_id)
        if agent is None:
            raise DeploymentUnavailable("Agent is not available")
        deployment = AgentDeployment.objects.for_organization(
            organization_id
        ).select_related("revision").filter(
            agent=agent,
            environment=environment,
        ).first()
        if deployment is None:
            raise DeploymentUnavailable(f"Agent has no {environment} deployment")
        if (
            agent.organization_id != organization_id
            or deployment.organization_id != organization_id
            or deployment.revision.organization_id != organization_id
            or deployment.revision.agent_id != agent.id
        ):
            raise InvalidExecutionDefinition(
                "Agent deployment crosses an agent or organization boundary"
            )
        registered = getattr(settings, "EXECUTION_CHILD_ADAPTERS", {}).get("agent", {})
        executor_key = "agent-completion"
        if executor_key not in registered:
            raise InvalidExecutionDefinition("Agent executor is not registered")
        run_organization = port.organization(organization_id)
        port.enforce_quota(run_organization)
        agent_definition = deployment.revision.content
        effective_config = {
            **dict(agent_definition.get("model_config") or {}),
            **dict(deployment.config_override or {}),
        }
        governance = _enforce_definition_governance(
            run_organization, agent_definition, effective_config
        )
        runtime_skills = input_data.get("skills") or []
        port.enforce_skill_policy(
            run_organization,
            [
                str(item.get("name") or "")
                for item in runtime_skills
                if isinstance(item, dict) and item.get("name")
            ],
        )
        guarded_input = port.apply_input_guardrails(run_organization, input_data)
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
                "agent_revision_id": str(deployment.revision_id),
                "agent_revision_no": deployment.revision.revision_no,
                "agent_content_hash": deployment.revision.content_hash,
                "deployment_id": str(deployment.id),
                "deployment_environment": deployment.environment,
                "deployment_version": deployment.version,
                "agent_definition": agent_definition,
                "effective_config": effective_config,
                "governance": governance,
                # Agent Skills are loaded from the active adapter directory at
                # execution time and intentionally use the latest files.
                "skill_revisions": [],
            },
            input_data=guarded_input,
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
        port = execution_domain_port()
        port.enforce_quota(organization)
        frozen_steps = []
        for step in steps:
            content = step.get("content") or {}
            _enforce_definition_governance(
                organization, content, step.get("effective_config") or {}
            )
            frozen_step = dict(step)
            frozen_step["skill_revisions"] = freeze_skill_revisions(
                organization_id=organization.id,
                environment=DeploymentEnvironment.PRODUCTION,
                content=content,
            )
            frozen_steps.append(frozen_step)
        governance = port.governance_snapshot(organization)
        guarded_input = port.apply_input_guardrails(organization, input_data)
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
            executor_key="workflow-dag",
            source_type="workflow",
            source_id=workflow_id,
            definition_snapshot={
                "workflow_id": str(workflow_id),
                "workflow_name": workflow_name,
                "workflow_steps": frozen_steps,
                "governance": governance,
                "durable_children": True,
            },
            input_data=guarded_input,
            priority=priority,
            max_attempts=3,
            retry_safe=True,
        )
        record.status = IdempotencyRecord.Status.COMPLETED
        record.response_status = 202
        record.response_body = {"run_id": str(run.id)}
        record.save(update_fields=("status", "response_status", "response_body"))
    return run, False
