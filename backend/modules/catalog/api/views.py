from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from modules.catalog.errors import (
    DeploymentRollbackUnavailable,
    DeploymentVersionConflict,
    DraftVersionConflict,
    InvalidApplicationDefinition,
    InvalidDeploymentRevision,
    QualityGateNotPassed,
)
from modules.catalog.models import (
    ApplicationDeployment,
    ApplicationDraft,
    ApplicationRevision,
    SkillDeployment,
    SkillDraft,
    SkillRevision,
)
from apps.applications.models import Application, ApplicationCategory, ChatApplication, Skill
from modules.catalog.services import (
    canonical_content_hash,
    publish_application,
    rollback_application_deployment,
    rollback_skill_deployment,
    switch_application_deployment,
    switch_skill_deployment,
    update_application_draft,
    update_skill_draft,
    publish_skill,
)
from modules.execution.api.base import ProblemDetailsAPIView
from apps.enterprise.models import Membership
from modules.tenancy.permissions import HasPathOrganizationRole, ROLE_LEVEL

from .pagination import ApplicationCursorPagination, ApplicationRevisionCursorPagination
from .serializers import (
    ApplicationDeploymentSerializer,
    ApplicationDraftSerializer,
    ApplicationRevisionSerializer,
    ApplicationSerializer,
    CreateApplicationSerializer,
    PublishApplicationSerializer,
    RollbackApplicationDeploymentSerializer,
    SwitchApplicationDeploymentSerializer,
    UpdateApplicationStatusSerializer,
    UpdateApplicationDraftSerializer,
    SkillDeploymentSerializer,
    SkillDraftSerializer,
    SkillRevisionSerializer,
    SwitchSkillDeploymentSerializer,
)


def _problem(request, *, status_code, code, title, detail):
    return Response(
        {
            "type": f"urn:agent-studio:problem:{code}",
            "code": code,
            "title": title,
            "status": status_code,
            "detail": detail,
            "request_id": getattr(request, "request_id", ""),
        },
        status=status_code,
        content_type="application/problem+json",
    )


def _validation_detail(exc):
    messages = getattr(exc, "messages", None)
    return messages[0] if messages else str(exc)


def _application(organization_id, application_id):
    return Application.objects.for_organization(organization_id).filter(
        pk=application_id
    ).first()


def _not_found(request):
    return _problem(
        request,
        status_code=status.HTTP_404_NOT_FOUND,
        code="application_not_found",
        title="Application not found",
        detail="The requested application does not exist or is not accessible.",
    )


def _skill(organization_id, skill_id):
    return Skill.objects.for_organization(organization_id).filter(
        pk=skill_id,
        is_active=True,
    ).first()


def _skill_not_found(request):
    return _problem(
        request,
        status_code=status.HTTP_404_NOT_FOUND,
        code="skill_not_found",
        title="Skill not found",
        detail="The requested skill does not exist or is not accessible.",
    )


def _can_manage_deployment(request):
    if request.user.is_superuser:
        return True
    membership = getattr(request, "organization_membership", None)
    return membership is not None and ROLE_LEVEL.get(membership.role, 0) >= ROLE_LEVEL[
        Membership.Role.ADMIN
    ]


def _require_deployment_admin(request):
    if not _can_manage_deployment(request):
        return _problem(
            request,
            status_code=status.HTTP_403_FORBIDDEN,
            code="deployment_requires_admin",
            title="Deployment requires administrator",
            detail="Only organization administrators and owners can change deployments.",
        )
    return None


class OrganizationApplicationsView(ProblemDetailsAPIView):
    permission_classes = (IsAuthenticated, HasPathOrganizationRole)

    def get(self, request, organization_id):
        applications = Application.objects.for_organization(organization_id).order_by(
            "-created_at", "-id"
        )
        paginator = ApplicationCursorPagination()
        page = paginator.paginate_queryset(applications, request, view=self)
        return paginator.get_paginated_response(
            ApplicationSerializer(page, many=True).data
        )

    def post(self, request, organization_id):
        serializer = CreateApplicationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                category_id = serializer.validated_data.get("category_id")
                if category_id is not None:
                    category = ApplicationCategory.objects.filter(
                        pk=category_id
                    ).first()
                    if category is None:
                        return _problem(
                            request,
                            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            code="application_category_not_found",
                            title="Application category not found",
                            detail="The requested application category does not exist.",
                        )
                else:
                    category, _ = ApplicationCategory.objects.get_or_create(
                        slug="uncategorized",
                        defaults={
                            "name": "Uncategorized",
                            "description": "Applications without an explicit category.",
                        },
                    )
                content = serializer.validated_data["content"]
                kind = content.get("kind", Application.Kind.CUSTOM)
                application = Application.objects.create(
                    organization=request.organization,
                    created_by=request.user,
                    category=category,
                    name=serializer.validated_data["name"],
                    slug=serializer.validated_data["slug"],
                    description=serializer.validated_data["description"],
                    kind=kind,
                )
                if kind == Application.Kind.CHAT:
                    ChatApplication.objects.create(application=application)
                draft = ApplicationDraft.objects.create(
                    organization=request.organization,
                    application=application,
                    updated_by=request.user,
                    content=content,
                )
        except IntegrityError:
            return _problem(
                request,
                status_code=status.HTTP_409_CONFLICT,
                code="application_slug_conflict",
                title="Application slug conflict",
                detail="An application with this slug already exists in the organization.",
            )

        body = ApplicationSerializer(application).data
        body["draft"] = ApplicationDraftSerializer(draft).data
        return Response(body, status=status.HTTP_201_CREATED)


class OrganizationApplicationView(ProblemDetailsAPIView):
    permission_classes = (IsAuthenticated, HasPathOrganizationRole)

    def get(self, request, organization_id, application_id):
        application = _application(organization_id, application_id)
        if application is None:
            return _not_found(request)
        body = ApplicationSerializer(application).data
        draft = ApplicationDraft.objects.for_organization(organization_id).filter(
            application=application
        ).first()
        body["draft"] = ApplicationDraftSerializer(draft).data if draft else None
        deployment = (
            ApplicationDeployment.objects.for_organization(organization_id)
            .filter(application=application)
            .first()
        )
        body["deployment"] = (
            ApplicationDeploymentSerializer(deployment).data if deployment else None
        )
        return Response(body)

    def patch(self, request, organization_id, application_id):
        if not _can_manage_deployment(request):
            return _problem(
                request,
                status_code=status.HTTP_403_FORBIDDEN,
                code="application_status_requires_admin",
                title="Application status requires administrator",
                detail=(
                    "Only organization administrators and owners can enable "
                    "or disable applications."
                ),
            )
        serializer = UpdateApplicationStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            application = (
                Application.objects.for_organization(organization_id)
                .select_for_update()
                .filter(pk=application_id)
                .first()
            )
            if application is None:
                return _not_found(request)
            application.is_active = serializer.validated_data["is_active"]
            application.save(update_fields=("is_active", "updated_at"))
        return Response(ApplicationSerializer(application).data)


class OrganizationApplicationRuntimeView(ProblemDetailsAPIView):
    permission_classes = (IsAuthenticated, HasPathOrganizationRole)

    def get(self, request, organization_id, application_id):
        application = _application(organization_id, application_id)
        if application is None:
            return _not_found(request)
        deployment = (
            ApplicationDeployment.objects.for_organization(organization_id)
            .select_related("revision")
            .filter(application=application)
            .first()
        )
        if deployment is None:
            return _problem(
                request,
                status_code=status.HTTP_409_CONFLICT,
                code="application_deployment_unavailable",
                title="Application deployment unavailable",
                detail="The application has no active deployment.",
            )
        revision = deployment.revision
        return Response(
            {
                "organization_id": str(application.organization_id),
                "application_id": str(application.id),
                "name": application.name,
                "slug": application.slug,
                "description": application.description,
                "deployment_id": str(deployment.id),
                "deployment_version": deployment.version,
                "revision_id": str(revision.id),
                "revision_no": revision.revision_no,
                "content_hash": revision.content_hash,
                "schema_version": revision.schema_version,
                "definition": revision.content,
            }
        )


class OrganizationApplicationDraftView(ProblemDetailsAPIView):
    permission_classes = (IsAuthenticated, HasPathOrganizationRole)

    def get(self, request, organization_id, application_id):
        application = _application(organization_id, application_id)
        if application is None:
            return _not_found(request)
        draft = ApplicationDraft.objects.for_organization(organization_id).filter(
            application=application
        ).first()
        if draft is None:
            return _problem(
                request,
                status_code=status.HTTP_409_CONFLICT,
                code="application_draft_missing",
                title="Application draft missing",
                detail="The application does not have an editable draft.",
            )
        return Response(ApplicationDraftSerializer(draft).data)

    def put(self, request, organization_id, application_id):
        application = _application(organization_id, application_id)
        if application is None:
            return _not_found(request)
        serializer = UpdateApplicationDraftSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            draft = update_application_draft(
                application=application,
                actor=request.user,
                expected_version=serializer.validated_data["expected_version"],
                content=serializer.validated_data["content"],
            )
        except DraftVersionConflict as exc:
            return _problem(
                request,
                status_code=status.HTTP_409_CONFLICT,
                code=exc.problem_code,
                title="Draft version conflict",
                detail=_validation_detail(exc),
            )
        except ValidationError as exc:
            return _problem(
                request,
                status_code=status.HTTP_409_CONFLICT,
                code=getattr(exc, "problem_code", "catalog_invariant_violation"),
                title="Catalog invariant violation",
                detail=_validation_detail(exc),
            )
        return Response(ApplicationDraftSerializer(draft).data)


class OrganizationApplicationRevisionsView(ProblemDetailsAPIView):
    permission_classes = (IsAuthenticated, HasPathOrganizationRole)

    def get(self, request, organization_id, application_id):
        application = _application(organization_id, application_id)
        if application is None:
            return _not_found(request)
        revisions = ApplicationRevision.objects.for_organization(
            organization_id
        ).filter(application=application)
        paginator = ApplicationRevisionCursorPagination()
        page = paginator.paginate_queryset(revisions, request, view=self)
        return paginator.get_paginated_response(
            ApplicationRevisionSerializer(page, many=True).data
        )

    def post(self, request, organization_id, application_id):
        application = _application(organization_id, application_id)
        if application is None:
            return _not_found(request)
        serializer = PublishApplicationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        draft = ApplicationDraft.objects.for_organization(organization_id).filter(
            application=application
        ).first()
        content_hash = canonical_content_hash(draft.content) if draft else None
        existed = bool(
            content_hash
            and ApplicationRevision.objects.for_organization(organization_id).filter(
                application=application, content_hash=content_hash
            ).exists()
        )
        try:
            revision = publish_application(
                application=application,
                actor=request.user,
                expected_draft_version=serializer.validated_data[
                    "expected_draft_version"
                ],
                release_notes=serializer.validated_data["release_notes"],
            )
        except InvalidApplicationDefinition as exc:
            response = _problem(
                request,
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                code=exc.problem_code,
                title="Invalid application definition",
                detail=_validation_detail(exc),
            )
            response.data["errors"] = exc.definition_errors
            return response
        except DraftVersionConflict as exc:
            return _problem(
                request,
                status_code=status.HTTP_409_CONFLICT,
                code=exc.problem_code,
                title="Draft version conflict",
                detail=_validation_detail(exc),
            )
        except ValidationError as exc:
            return _problem(
                request,
                status_code=status.HTTP_409_CONFLICT,
                code=getattr(exc, "problem_code", "catalog_invariant_violation"),
                title="Catalog invariant violation",
                detail=_validation_detail(exc),
            )
        response = Response(
            ApplicationRevisionSerializer(revision).data,
            status=status.HTTP_200_OK if existed else status.HTTP_201_CREATED,
        )
        if existed:
            response["Idempotent-Replay"] = "true"
        return response


class OrganizationApplicationRevisionView(ProblemDetailsAPIView):
    permission_classes = (IsAuthenticated, HasPathOrganizationRole)

    def get(self, request, organization_id, application_id, revision_id):
        application = _application(organization_id, application_id)
        if application is None:
            return _not_found(request)
        revision = ApplicationRevision.objects.for_organization(
            organization_id
        ).filter(pk=revision_id, application=application).first()
        if revision is None:
            return _problem(
                request,
                status_code=status.HTTP_404_NOT_FOUND,
                code="application_revision_not_found",
                title="Application revision not found",
                detail="The requested revision does not exist or is not accessible.",
            )
        return Response(ApplicationRevisionSerializer(revision).data)


class OrganizationApplicationDeploymentView(ProblemDetailsAPIView):
    permission_classes = (IsAuthenticated, HasPathOrganizationRole)

    def get(self, request, organization_id, application_id):
        application = _application(organization_id, application_id)
        if application is None:
            return _not_found(request)
        deployment = ApplicationDeployment.objects.for_organization(
            organization_id
        ).filter(application=application).first()
        if deployment is None:
            return _problem(
                request,
                status_code=status.HTTP_404_NOT_FOUND,
                code="application_deployment_not_found",
                title="Application deployment not found",
                detail="The requested deployment has not been configured.",
            )
        return Response(ApplicationDeploymentSerializer(deployment).data)

    def put(self, request, organization_id, application_id):
        permission_problem = _require_deployment_admin(request)
        if permission_problem is not None:
            return permission_problem
        application = _application(organization_id, application_id)
        if application is None:
            return _not_found(request)
        serializer = SwitchApplicationDeploymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        expected_version = serializer.validated_data["expected_version"]
        try:
            deployment = switch_application_deployment(
                application=application,
                actor=request.user,
                revision_id=serializer.validated_data["revision_id"],
                expected_version=expected_version,
                config_override=serializer.validated_data["config_override"],
            )
        except DeploymentVersionConflict as exc:
            return _problem(
                request,
                status_code=status.HTTP_409_CONFLICT,
                code=exc.code,
                title="Deployment version conflict",
                detail=str(exc),
            )
        except InvalidDeploymentRevision as exc:
            return _problem(
                request,
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                code=exc.code,
                title="Invalid deployment revision",
                detail=str(exc),
            )
        except QualityGateNotPassed as exc:
            return _problem(
                request,
                status_code=status.HTTP_409_CONFLICT,
                code=exc.code,
                title="Deployment quality gate not passed",
                detail=str(exc),
            )
        return Response(
            ApplicationDeploymentSerializer(deployment).data,
            status=(
                status.HTTP_201_CREATED
                if expected_version == 0
                else status.HTTP_200_OK
            ),
        )


class OrganizationApplicationDeploymentRollbackView(ProblemDetailsAPIView):
    permission_classes = (IsAuthenticated, HasPathOrganizationRole)

    def post(self, request, organization_id, application_id):
        permission_problem = _require_deployment_admin(request)
        if permission_problem is not None:
            return permission_problem
        application = _application(organization_id, application_id)
        if application is None:
            return _not_found(request)
        serializer = RollbackApplicationDeploymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            deployment = rollback_application_deployment(
                application=application,
                actor=request.user,
                expected_version=serializer.validated_data["expected_version"],
            )
        except DeploymentVersionConflict as exc:
            return _problem(
                request,
                status_code=status.HTTP_409_CONFLICT,
                code=exc.code,
                title="Deployment version conflict",
                detail=str(exc),
            )
        except DeploymentRollbackUnavailable as exc:
            return _problem(
                request,
                status_code=status.HTTP_409_CONFLICT,
                code=exc.code,
                title="Deployment rollback unavailable",
                detail=str(exc),
            )
        return Response(ApplicationDeploymentSerializer(deployment).data)


class OrganizationSkillDraftView(ProblemDetailsAPIView):
    permission_classes = (IsAuthenticated, HasPathOrganizationRole)

    def get(self, request, organization_id, skill_id):
        skill = _skill(organization_id, skill_id)
        if skill is None:
            return _skill_not_found(request)
        draft = SkillDraft.objects.for_organization(organization_id).filter(
            skill=skill
        ).first()
        if draft is None:
            return _problem(
                request,
                status_code=409,
                code="skill_draft_missing",
                title="Skill draft missing",
                detail="The skill does not have an editable draft.",
            )
        return Response(SkillDraftSerializer(draft).data)

    def put(self, request, organization_id, skill_id):
        skill = _skill(organization_id, skill_id)
        if skill is None:
            return _skill_not_found(request)
        serializer = UpdateApplicationDraftSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            draft = update_skill_draft(
                skill=skill,
                actor=request.user,
                expected_version=serializer.validated_data["expected_version"],
                content=serializer.validated_data["content"],
            )
        except DraftVersionConflict as exc:
            return _problem(
                request, status_code=409, code=exc.problem_code,
                title="Draft version conflict", detail=_validation_detail(exc),
            )
        return Response(SkillDraftSerializer(draft).data)


class OrganizationSkillRevisionsView(ProblemDetailsAPIView):
    permission_classes = (IsAuthenticated, HasPathOrganizationRole)

    def get(self, request, organization_id, skill_id):
        skill = _skill(organization_id, skill_id)
        if skill is None:
            return _skill_not_found(request)
        revisions = SkillRevision.objects.for_organization(organization_id).filter(
            skill=skill
        ).order_by("revision_no")
        return Response(SkillRevisionSerializer(revisions, many=True).data)

    def post(self, request, organization_id, skill_id):
        skill = _skill(organization_id, skill_id)
        if skill is None:
            return _skill_not_found(request)
        serializer = PublishApplicationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        draft = SkillDraft.objects.for_organization(organization_id).filter(
            skill=skill
        ).first()
        content_hash = canonical_content_hash(draft.content) if draft else None
        existed = bool(
            content_hash
            and SkillRevision.objects.for_organization(organization_id).filter(
                skill=skill, content_hash=content_hash
            ).exists()
        )
        try:
            revision = publish_skill(
                skill=skill,
                actor=request.user,
                expected_draft_version=serializer.validated_data["expected_draft_version"],
                release_notes=serializer.validated_data["release_notes"],
            )
        except DraftVersionConflict as exc:
            return _problem(
                request, status_code=409, code=exc.problem_code,
                title="Draft version conflict", detail=_validation_detail(exc),
            )
        response = Response(
            SkillRevisionSerializer(revision).data,
            status=200 if existed else 201,
        )
        if existed:
            response["Idempotent-Replay"] = "true"
        return response


class OrganizationSkillRevisionView(ProblemDetailsAPIView):
    permission_classes = (IsAuthenticated, HasPathOrganizationRole)

    def get(self, request, organization_id, skill_id, revision_id):
        skill = _skill(organization_id, skill_id)
        if skill is None:
            return _skill_not_found(request)
        revision = SkillRevision.objects.for_organization(organization_id).filter(
            pk=revision_id, skill=skill
        ).first()
        if revision is None:
            return _problem(
                request, status_code=404, code="skill_revision_not_found",
                title="Skill revision not found",
                detail="The requested revision does not exist or is not accessible.",
            )
        return Response(SkillRevisionSerializer(revision).data)


class OrganizationSkillDeploymentView(ProblemDetailsAPIView):
    permission_classes = (IsAuthenticated, HasPathOrganizationRole)

    def get(self, request, organization_id, skill_id):
        skill = _skill(organization_id, skill_id)
        if skill is None:
            return _skill_not_found(request)
        deployment = SkillDeployment.objects.for_organization(organization_id).filter(
            skill=skill
        ).first()
        if deployment is None:
            return _problem(
                request, status_code=404, code="skill_deployment_not_found",
                title="Skill deployment not found",
                detail="The requested deployment has not been configured.",
            )
        return Response(SkillDeploymentSerializer(deployment).data)

    def put(self, request, organization_id, skill_id):
        permission_problem = _require_deployment_admin(request)
        if permission_problem is not None:
            return permission_problem
        skill = _skill(organization_id, skill_id)
        if skill is None:
            return _skill_not_found(request)
        serializer = SwitchSkillDeploymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            deployment = switch_skill_deployment(
                skill=skill,
                actor=request.user,
                revision_id=serializer.validated_data["revision_id"],
                expected_version=serializer.validated_data["expected_version"],
            )
        except DeploymentVersionConflict as exc:
            return _problem(
                request, status_code=409, code=exc.code,
                title="Skill deployment rejected", detail=str(exc),
            )
        except InvalidDeploymentRevision as exc:
            return _problem(
                request, status_code=422, code=exc.code,
                title="Invalid skill deployment revision", detail=str(exc),
            )
        except QualityGateNotPassed as exc:
            return _problem(
                request, status_code=409, code=exc.code,
                title="Deployment quality gate not passed", detail=str(exc),
            )
        return Response(
            SkillDeploymentSerializer(deployment).data,
            status=201 if serializer.validated_data["expected_version"] == 0 else 200,
        )


class OrganizationSkillDeploymentRollbackView(ProblemDetailsAPIView):
    permission_classes = (IsAuthenticated, HasPathOrganizationRole)

    def post(self, request, organization_id, skill_id):
        permission_problem = _require_deployment_admin(request)
        if permission_problem is not None:
            return permission_problem
        skill = _skill(organization_id, skill_id)
        if skill is None:
            return _skill_not_found(request)
        serializer = RollbackApplicationDeploymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            deployment = rollback_skill_deployment(
                skill=skill,
                actor=request.user,
                expected_version=serializer.validated_data["expected_version"],
            )
        except (DeploymentVersionConflict, DeploymentRollbackUnavailable) as exc:
            return _problem(
                request, status_code=409, code=exc.code,
                title="Skill rollback rejected", detail=str(exc),
            )
        return Response(SkillDeploymentSerializer(deployment).data)
