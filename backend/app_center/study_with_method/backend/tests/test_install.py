import pytest
from django.conf import settings
from django.contrib.auth import get_user_model

from apps.applications.app_center.discovery import discover_packages
from apps.applications.app_center.installer import sync_package
from apps.applications.models import Application
from apps.enterprise.models import Membership, Organization
from apps.agents.high_school_tutors import TUTOR_DEFINITIONS
from modules.catalog.models import AgentDeployment, ApplicationDeployment

from ..models import CurriculumNode, StudyWorkspace, Subject
from ..services import TUTOR_AGENT_SLUG


@pytest.mark.django_db
def test_package_install_is_idempotent_and_provisions_tutor():
    owner = get_user_model().objects.create_user(username="study-install-owner")
    organization = Organization.objects.create(
        name="Study Install", slug="study-install", owner=owner
    )
    Membership.objects.create(
        organization=organization, user=owner, role=Membership.Role.OWNER
    )
    packages, _errors = discover_packages(settings.APP_CENTER_ROOT, strict=False)
    package = next(item for item in packages if item.manifest.metadata.id == "study-with-method")

    sync_package(package, organization)
    sync_package(package, organization)

    application = Application.objects.get(
        organization=organization, slug="study-with-method"
    )
    assert application.name == "学之有道"
    assert application.draft.content["renderer_key"] == "study-with-method"
    assert application.draft.content["executor_key"] == "study-with-method"
    assert StudyWorkspace.objects.get(application=application).enabled_subjects == list(
        Subject.values
    )
    assert ApplicationDeployment.objects.get(application=application)
    legacy_tutor = organization.agents.get(slug=TUTOR_AGENT_SLUG)
    assert AgentDeployment.objects.get(agent=legacy_tutor)
    tutors = organization.agents.filter(
        slug__in=[definition.slug for definition in TUTOR_DEFINITIONS]
    )
    assert tutors.count() == len(Subject.values)
    assert AgentDeployment.objects.filter(agent__in=tutors).count() == len(Subject.values)
    assert all("提示阶梯" in tutor.draft.content["system_prompt"] for tutor in tutors)
    assert CurriculumNode.objects.filter(code="math.function.monotonicity").exists()
    assert CurriculumNode.objects.filter(subject=Subject.PHYSICS).exists()
