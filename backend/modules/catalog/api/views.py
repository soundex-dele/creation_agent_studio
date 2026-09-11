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
)
from modules.catalog.models import (
    Application,
    ApplicationDeployment,
    ApplicationDraft,
    ApplicationRevision,
    DeploymentEnvironment,
)
from apps.applications.models import ApplicationCategory
from modules.catalog.services import (
    canonical_content_hash,
    publish_application,
    rollback_application_deployment,
    switch_application_deployment,
    update_application_draft,
)
from modules.execution.api.base import ProblemDetailsAPIView
from modules.tenancy.models import Membership
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
    UpdateApplicationDraftSerializer,
)


def _problem(request, *, status_code, code, title, detail):
    return Response(
        {
            "type": f"urn:creation-agent-studio:problem:{code}",
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


def _can_manage_production(request):
    if request.user.is_superuser:
        return True
    membership = getattr(request, "organization_membership", None)
    return membership is not None and ROLE_LEVEL.get(membership.role, 0) >= ROLE_LEVEL[
        Membership.Role.ADMIN
    ]


def _validate_environment(request, environment):
    if environment not in DeploymentEnvironment.values:
        return _problem(
            request,
            status_code=status.HTTP_400_BAD_REQUEST,
            code="invalid_deployment_environment",
            title="Invalid deployment environment",
            detail="environment must be development, staging, or production.",
        )
    if environment == DeploymentEnvironment.PRODUCTION and not _can_manage_production(
        request
    ):
        return _problem(
            request,
            status_code=status.HTTP_403_FORBIDDEN,
            code="production_deployment_requires_admin",
            title="Production deployment requires administrator",
            detail="Only organization administrators and owners can change production deployments.",
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
                application = Application.objects.create(
                    organization=request.organization,
                    created_by=request.user,
                    category=category,
                    name=serializer.validated_data["name"],
                    slug=serializer.validated_data["slug"],
                    description=serializer.validated_data["description"],
                    executor_key=str(content.get("executor_key") or ""),
                    renderer_key=str(content.get("renderer_key") or ""),
                    input_schema=content.get("input_schema") or {},
                    output_schema=content.get("output_schema") or {},
                    default_config=content.get("default_config") or {},
                )
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
        body["deployments"] = ApplicationDeploymentSerializer(
            ApplicationDeployment.objects.for_organization(organization_id)
            .filter(application=application)
            .order_by("environment"),
            many=True,
        ).data
        return Response(body)


class OrganizationApplicationRuntimeView(ProblemDetailsAPIView):
    permission_classes = (IsAuthenticated, HasPathOrganizationRole)

    def get(self, request, organization_id, application_id):
        application = _application(organization_id, application_id)
        if application is None:
            return _not_found(request)
        environment = request.query_params.get(
            "environment", DeploymentEnvironment.PRODUCTION
        )
        if environment not in DeploymentEnvironment.values:
            return _problem(
                request,
                status_code=status.HTTP_400_BAD_REQUEST,
                code="invalid_deployment_environment",
                title="Invalid deployment environment",
                detail="environment must be development, staging, or production.",
            )
        deployment = (
            ApplicationDeployment.objects.for_organization(organization_id)
            .select_related("revision")
            .filter(application=application, environment=environment)
            .first()
        )
        if deployment is None:
            return _problem(
                request,
                status_code=status.HTTP_409_CONFLICT,
                code="application_deployment_unavailable",
                title="Application deployment unavailable",
                detail=f"The application has no {environment} deployment.",
            )
        revision = deployment.revision
        return Response(
            {
                "organization_id": str(application.organization_id),
                "application_id": str(application.id),
                "name": application.name,
                "slug": application.slug,
                "description": application.description,
                "environment": deployment.environment,
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


class OrganizationApplicationDeploymentsView(ProblemDetailsAPIView):
    permission_classes = (IsAuthenticated, HasPathOrganizationRole)

    def get(self, request, organization_id, application_id):
        application = _application(organization_id, application_id)
        if application is None:
            return _not_found(request)
        deployments = ApplicationDeployment.objects.for_organization(
            organization_id
        ).filter(application=application).order_by("environment")
        return Response(ApplicationDeploymentSerializer(deployments, many=True).data)


class OrganizationApplicationDeploymentView(ProblemDetailsAPIView):
    permission_classes = (IsAuthenticated, HasPathOrganizationRole)

    def get(self, request, organization_id, application_id, environment):
        application = _application(organization_id, application_id)
        if application is None:
            return _not_found(request)
        if environment not in DeploymentEnvironment.values:
            return _validate_environment(request, environment)
        deployment = ApplicationDeployment.objects.for_organization(
            organization_id
        ).filter(application=application, environment=environment).first()
        if deployment is None:
            return _problem(
                request,
                status_code=status.HTTP_404_NOT_FOUND,
                code="application_deployment_not_found",
                title="Application deployment not found",
                detail="The requested deployment has not been configured.",
            )
        return Response(ApplicationDeploymentSerializer(deployment).data)

    def put(self, request, organization_id, application_id, environment):
        environment_problem = _validate_environment(request, environment)
        if environment_problem is not None:
            return environment_problem
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
                environment=environment,
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

    def post(self, request, organization_id, application_id, environment):
        environment_problem = _validate_environment(request, environment)
        if environment_problem is not None:
            return environment_problem
        application = _application(organization_id, application_id)
        if application is None:
            return _not_found(request)
        serializer = RollbackApplicationDeploymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            deployment = rollback_application_deployment(
                application=application,
                actor=request.user,
                environment=environment,
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
