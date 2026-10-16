"""Delete accounts without bypassing protected resource ownership."""
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.db.models.deletion import Collector, ProtectedError, RestrictedError
from django.utils.text import slugify
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, ValidationError

from apps.enterprise.models import GovernancePolicy, Membership, Organization, QuotaPolicy
from apps.enterprise.tenancy import get_single_tenant_organization
from .models import User


class AccountDeletionConflict(APIException):
    status_code = 409
    default_detail = (
        '账号拥有非空或共享工作区，或仍关联组织、工作流、技能等受保护资源。'
        '请先转移或清理相关资源，再删除账号；也可以先停用账号。'
    )


def _delete_empty_personal_workspaces(user):
    """Only remove the empty workspace provisioned by the user-created signal."""
    singleton = get_single_tenant_organization(active_only=False)
    base = slugify(user.username)[:70] or f'user-{user.pk}'
    allowed_models = {Organization, Membership, GovernancePolicy, QuotaPolicy}
    for organization in user.owned_organizations.select_for_update().order_by('pk'):
        if (
            (singleton and singleton.pk == organization.pk)
            or organization.slug != f'{base}-{user.pk}'
            or organization.name != f'{user.username} Workspace'
            or organization.memberships.exclude(user=user).exists()
        ):
            raise AccountDeletionConflict()
        collector = Collector(using=user._state.db)
        collector.collect([organization])
        if any(model not in allowed_models and objects
               for model, objects in collector.data.items()):
            raise AccountDeletionConflict()
        if any(query.model not in allowed_models and query.exists()
               for query in collector.fast_deletes):
            raise AccountDeletionConflict()
        # SET_NULL relations are not collected for deletion, but still mean that
        # the workspace has history/content and must not be silently removed.
        for relation in organization._meta.related_objects:
            if relation.related_model not in allowed_models and relation.related_model._base_manager.filter(
                **{relation.field.name: organization},
            ).exists():
                raise AccountDeletionConflict()
        organization.delete()


@transaction.atomic
def delete_account(*, actor, account_id):
    # Lock administrators and the target in a consistent order so concurrent
    # deletions cannot remove each other's authorization or the final admin.
    locked = list(User.objects.select_for_update().filter(
        Q(role=User.Role.ADMIN) | Q(is_superuser=True)
        | Q(pk=actor.pk) | Q(pk=account_id),
    ).order_by('pk'))
    current_actor = next((user for user in locked if user.pk == actor.pk), None)
    if not current_actor or not current_actor.is_active or not (
        current_actor.is_superuser or current_actor.role == User.Role.ADMIN
    ):
        raise PermissionDenied('只有有效的平台管理员可以删除账号。')
    target = next((user for user in locked if user.pk == account_id), None)
    if not target or target.username == 'system':
        raise NotFound()
    if target.pk == actor.pk:
        raise ValidationError({'detail': '不能删除当前登录的账号。'})
    if target.is_superuser and not current_actor.is_superuser:
        raise PermissionDenied('只有超级管理员可以删除超级管理员账号。')
    if target.is_active and target.role == User.Role.ADMIN and not any(
        user.pk != target.pk and user.is_active and user.role == User.Role.ADMIN
        for user in locked
    ):
        raise ValidationError({'detail': '系统必须至少保留一个有效的平台管理员。'})
    try:
        _delete_empty_personal_workspaces(target)
        target.delete()
    except (ProtectedError, RestrictedError, IntegrityError) as exc:
        raise AccountDeletionConflict() from exc
