import hashlib
import json
import time
from datetime import timedelta

from django.db import IntegrityError, OperationalError, transaction
from django.utils import timezone

from modules.catalog.models import Application, ApplicationDeployment
from modules.execution.models import IdempotencyRecord, Run

from .errors import (
    DeploymentUnavailable,
    IdempotencyKeyReused,
    InvalidExecutionDefinition,
)
from .runs import create_run


CREATE_APPLICATION_RUN_OPERATION = "application.run.create"


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


def _load_replay(*, organization_id, actor_id, key, fingerprint):
    record = IdempotencyRecord.objects.for_organization(organization_id).filter(
        actor_id=actor_id,
        operation=CREATE_APPLICATION_RUN_OPERATION,
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
            key=idempotency_key,
            fingerprint=fingerprint,
        )
        if replay is not None:
            return replay, True

        executor_kind, executor_key, max_attempts, retry_safe = _definition_values(revision)
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
