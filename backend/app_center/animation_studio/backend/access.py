from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied, ValidationError
from apps.applications.models import Application
from apps.enterprise.models import Membership
from core.resource_access import accessible_resources
from modules.execution.models import Run
from .models import AnimationAsset


def application_for(user, organization_id, application_id):
    if not Membership.objects.filter(organization_id=organization_id, organization__is_active=True,
                                     user=user, user__is_active=True, is_active=True).exists():
        raise PermissionDenied("当前账号不是有效组织成员。")
    return get_object_or_404(accessible_resources(
        Application.objects.for_organization(organization_id).filter(
            slug="animation-studio", kind="custom", is_active=True), user, operation="run"), pk=application_id)


def runs_for(user, application):
    return Run.objects.for_organization(application.organization_id).filter(
        owner=user, source_type="application", source_id=str(application.id), executor_key="animation-studio")


def generation_for(user, application, run_id, *, ready=False):
    run = get_object_or_404(runs_for(user, application).filter(input__action="generate"), pk=run_id)
    if ready and (run.status != "succeeded" or not run.artifacts.filter(kind="animation-source").exists()):
        raise ValidationError("请先完成该版本的 HTML 预览生成。")
    return run


def assets_for(user, application, ids):
    values = list(AnimationAsset.objects.for_organization(application.organization_id).filter(
        owner=user, application=application, id__in=ids))
    if len(values) != len(ids):
        raise ValidationError("素材不存在或不属于当前用户。")
    if sum(item.size for item in values) > 100 * 1024 * 1024:
        raise ValidationError("一部动画的素材总量不能超过 100 MB。")
    if sum(item.duration is not None for item in values) > 1:
        raise ValidationError("每部动画最多使用一段录音。")
    return values
