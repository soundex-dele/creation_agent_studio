import hashlib
import json

from django.db import IntegrityError, transaction
from django.db.models import F
from django.db.models import Q
from django.utils import timezone
from pydantic import ValidationError as PydanticValidationError

from .definition import application_definition_errors, validate_application_definition
from .errors import (
    CatalogInvariantViolation,
    DeploymentRollbackUnavailable,
    DeploymentVersionConflict,
    DraftVersionConflict,
    InvalidApplicationDefinition,
    InvalidDeploymentRevision,
)

from .models import (
    AgentDeployment,
    AgentDraft,
    AgentRevision,
    ApplicationDeployment,
    ApplicationDraft,
    ApplicationRevision,
    ChatApplicationRevision,
    SkillDraft,
    SkillRevision,
)


def canonical_content_hash(content):
    encoded = json.dumps(
        content,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def update_application_draft(*, application, actor, expected_version, content):
    """Replace a draft with a portable compare-and-swap update."""

    draft = ApplicationDraft.objects.filter(application=application).first()
    if draft is None or draft.organization_id != application.organization_id:
        raise CatalogInvariantViolation(
            "Draft and definition must belong to the same organization"
        )

    updated = ApplicationDraft.objects.filter(
        pk=draft.pk,
        organization_id=application.organization_id,
        version=expected_version,
    ).update(
        content=content,
        version=F("version") + 1,
        updated_by=actor,
        updated_at=timezone.now(),
    )
    if updated != 1:
        current_version = (
            ApplicationDraft.objects.filter(pk=draft.pk)
            .values_list("version", flat=True)
            .first()
        )
        raise DraftVersionConflict(
            f"Draft version changed: expected {expected_version}, found {current_version}"
        )
    return ApplicationDraft.objects.get(pk=draft.pk)


def _publish(*, definition, draft_model, revision_model, relation_name, actor, expected_draft_version, release_notes=""):
    with transaction.atomic():
        locked_definition = definition.__class__.objects.select_for_update().get(pk=definition.pk)
        draft = draft_model.objects.select_for_update().get(**{relation_name: locked_definition})
        if draft.organization_id != locked_definition.organization_id:
            raise CatalogInvariantViolation(
                "Draft and definition must belong to the same organization"
            )
        if draft.version != expected_draft_version:
            raise DraftVersionConflict(
                f"Draft version changed: expected {expected_draft_version}, found {draft.version}"
            )

        content_hash = canonical_content_hash(draft.content)
        existing = revision_model.objects.filter(
            **{relation_name: locked_definition},
            content_hash=content_hash,
        ).first()
        if existing is not None:
            return existing

        last_revision = (
            revision_model.objects.filter(**{relation_name: locked_definition})
            .order_by("-revision_no")
            .first()
        )
        revision_no = 1 if last_revision is None else last_revision.revision_no + 1
        return revision_model.objects.create(
            organization_id=locked_definition.organization_id,
            **{relation_name: locked_definition},
            revision_no=revision_no,
            content=draft.content,
            content_hash=content_hash,
            created_by=actor,
            release_notes=release_notes,
        )


def publish_agent(*, agent, actor, expected_draft_version, release_notes=""):
    return _publish(
        definition=agent,
        draft_model=AgentDraft,
        revision_model=AgentRevision,
        relation_name="agent",
        actor=actor,
        expected_draft_version=expected_draft_version,
        release_notes=release_notes,
    )


def publish_skill(*, skill, actor, expected_draft_version, release_notes=""):
    return _publish(
        definition=skill,
        draft_model=SkillDraft,
        revision_model=SkillRevision,
        relation_name="skill",
        actor=actor,
        expected_draft_version=expected_draft_version,
        release_notes=release_notes,
    )


def publish_application(*, application, actor, expected_draft_version, release_notes=""):
    draft = ApplicationDraft.objects.filter(application=application).first()
    if draft is None:
        raise CatalogInvariantViolation("The application does not have a draft")
    try:
        parsed = validate_application_definition(draft.content, schema_version=1)
    except (PydanticValidationError, ValueError) as exc:
        errors = (
            application_definition_errors(exc)
            if isinstance(exc, PydanticValidationError)
            else []
        )
        raise InvalidApplicationDefinition(
            "Application Draft does not satisfy definition schema version 1.",
            errors=errors,
        ) from exc
    if parsed.kind != application.kind:
        raise InvalidApplicationDefinition(
            "Application kind and Draft definition kind must match.",
            errors=[{"field": "kind", "code": "kind_mismatch", "message": "Stable identity and definition kind differ."}],
        )
    if application.kind == application.Kind.CHAT:
        from apps.agents.models import Agent
        from apps.applications.models import Skill
        agent_ids = {binding.agent_id for binding in parsed.agent_bindings}
        allowed_agents = set(Agent.objects.filter(
            Q(organization=application.organization) | Q(is_public=True),
            id__in=agent_ids, is_active=True,
        ).values_list('id', flat=True))
        if agent_ids != allowed_agents:
            raise InvalidApplicationDefinition(
                "Chat definition references unavailable agents.",
                errors=[{"field": "agent_bindings", "code": "invalid_reference", "message": "Agent is unavailable in this organization."}],
            )
        skill_ids = {binding.skill_id for binding in parsed.skill_bindings}
        allowed_skills = {str(value) for value in Skill.objects.filter(
            Q(organization=application.organization) |
            Q(visibility=Skill.Visibility.PUBLIC),
            id__in=skill_ids, is_active=True,
        ).values_list('id', flat=True)}
        if skill_ids != allowed_skills:
            raise InvalidApplicationDefinition(
                "Chat definition references unavailable skills.",
                errors=[{"field": "skill_bindings", "code": "invalid_reference", "message": "Skill is unavailable in this organization."}],
            )
    revision = _publish(
        definition=application,
        draft_model=ApplicationDraft,
        revision_model=ApplicationRevision,
        relation_name="application",
        actor=actor,
        expected_draft_version=expected_draft_version,
        release_notes=release_notes,
    )
    if application.kind == application.Kind.CHAT:
        if not hasattr(application, "chat_application"):
            raise CatalogInvariantViolation("Chat application subtype is missing")
        ChatApplicationRevision.objects.get_or_create(revision=revision)
    return revision


def switch_agent_deployment(
    *, agent, actor, environment, revision_id, expected_version, config_override=None
):
    revision = AgentRevision.objects.filter(
        pk=revision_id,
        organization_id=agent.organization_id,
        agent=agent,
    ).first()
    if revision is None:
        raise InvalidDeploymentRevision(
            "The revision does not belong to this agent and organization."
        )
    config_override = config_override or {}
    with transaction.atomic():
        deployment = AgentDeployment.objects.select_for_update().filter(
            agent=agent,
            organization_id=agent.organization_id,
            environment=environment,
        ).first()
        current_version = deployment.version if deployment else 0
        if current_version != expected_version:
            raise DeploymentVersionConflict(
                f"Deployment version changed: expected {expected_version}, "
                f"found {current_version}"
            )
        if deployment is None:
            return AgentDeployment.objects.create(
                organization_id=agent.organization_id,
                agent=agent,
                environment=environment,
                revision=revision,
                config_override=config_override,
                updated_by=actor,
            )
        previous_revision_id = (
            deployment.revision_id
            if deployment.revision_id != revision.id
            else deployment.previous_revision_id
        )
        deployment.revision = revision
        deployment.previous_revision_id = previous_revision_id
        deployment.config_override = config_override
        deployment.version += 1
        deployment.updated_by = actor
        deployment.save()
        return deployment


def rollback_agent_deployment(*, agent, actor, environment, expected_version):
    with transaction.atomic():
        deployment = AgentDeployment.objects.select_for_update().filter(
            agent=agent,
            organization_id=agent.organization_id,
            environment=environment,
        ).first()
        if deployment is None or deployment.previous_revision_id is None:
            raise DeploymentRollbackUnavailable(
                "No previous revision is available for this deployment."
            )
        if deployment.version != expected_version:
            raise DeploymentVersionConflict(
                f"Deployment version changed: expected {expected_version}, "
                f"found {deployment.version}"
            )
        current_revision_id = deployment.revision_id
        deployment.revision_id = deployment.previous_revision_id
        deployment.previous_revision_id = current_revision_id
        deployment.version += 1
        deployment.updated_by = actor
        deployment.save()
        return deployment


def _deployment_revision(*, application, revision_id):
    revision = ApplicationRevision.objects.filter(
        pk=revision_id,
        organization_id=application.organization_id,
        application=application,
    ).first()
    if revision is None:
        raise InvalidDeploymentRevision(
            "The revision does not belong to this application and organization."
        )
    try:
        parsed = validate_application_definition(
            revision.content, schema_version=revision.schema_version)
    except (PydanticValidationError, ValueError) as exc:
        raise InvalidDeploymentRevision(
            "The revision does not contain a valid application definition."
        ) from exc
    if parsed.kind != application.kind:
        raise InvalidDeploymentRevision(
            "The revision kind does not match the application subtype."
        )
    if (application.kind == application.Kind.CHAT
            and not hasattr(revision, "chat_revision")):
        raise InvalidDeploymentRevision(
            "Chat deployments require a ChatApplicationRevision."
        )
    return revision


def switch_application_deployment(
    *,
    application,
    actor,
    environment,
    revision_id,
    expected_version,
    config_override=None,
):
    """Create or switch a deployment using version 0 as the create precondition."""

    revision = _deployment_revision(application=application, revision_id=revision_id)
    config_override = config_override or {}

    try:
        with transaction.atomic():
            deployment = ApplicationDeployment.objects.filter(
                application=application,
                organization_id=application.organization_id,
                environment=environment,
            ).first()
            if deployment is None:
                if expected_version != 0:
                    raise DeploymentVersionConflict(
                        f"Deployment version changed: expected {expected_version}, found 0"
                    )
                return ApplicationDeployment.objects.create(
                    organization_id=application.organization_id,
                    application=application,
                    environment=environment,
                    revision=revision,
                    config_override=config_override,
                    updated_by=actor,
                )

            previous_revision_id = (
                deployment.revision_id
                if deployment.revision_id != revision.id
                else deployment.previous_revision_id
            )
            updated = ApplicationDeployment.objects.filter(
                pk=deployment.pk,
                version=expected_version,
            ).update(
                revision=revision,
                previous_revision_id=previous_revision_id,
                config_override=config_override,
                version=F("version") + 1,
                updated_by=actor,
                updated_at=timezone.now(),
            )
            if updated != 1:
                current_version = (
                    ApplicationDeployment.objects.filter(pk=deployment.pk)
                    .values_list("version", flat=True)
                    .first()
                )
                raise DeploymentVersionConflict(
                    f"Deployment version changed: expected {expected_version}, found {current_version}"
                )
            return ApplicationDeployment.objects.get(pk=deployment.pk)
    except IntegrityError as exc:
        current_version = (
            ApplicationDeployment.objects.filter(
                application=application,
                environment=environment,
            )
            .values_list("version", flat=True)
            .first()
        )
        if current_version is not None:
            raise DeploymentVersionConflict(
                f"Deployment version changed: expected {expected_version}, found {current_version}"
            ) from exc
        raise


def rollback_application_deployment(
    *, application, actor, environment, expected_version
):
    """Atomically swap the current and previous revisions."""

    with transaction.atomic():
        deployment = ApplicationDeployment.objects.filter(
            application=application,
            organization_id=application.organization_id,
            environment=environment,
        ).first()
        if deployment is None:
            raise DeploymentRollbackUnavailable(
                "No previous revision is available for this deployment."
            )
        if deployment.version != expected_version:
            raise DeploymentVersionConflict(
                f"Deployment version changed: expected {expected_version}, found {deployment.version}"
            )
        if deployment.previous_revision_id is None:
            raise DeploymentRollbackUnavailable(
                "No previous revision is available for this deployment."
            )

        updated = ApplicationDeployment.objects.filter(
            pk=deployment.pk,
            version=expected_version,
        ).update(
            revision_id=deployment.previous_revision_id,
            previous_revision_id=deployment.revision_id,
            version=F("version") + 1,
            updated_by=actor,
            updated_at=timezone.now(),
        )
        if updated != 1:
            current_version = (
                ApplicationDeployment.objects.filter(pk=deployment.pk)
                .values_list("version", flat=True)
                .first()
            )
            raise DeploymentVersionConflict(
                f"Deployment version changed: expected {expected_version}, found {current_version}"
            )
        return ApplicationDeployment.objects.get(pk=deployment.pk)
