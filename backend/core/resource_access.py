"""Tenant, role and resource-level authorization for Agents and Applications."""

from copy import deepcopy

from django.db import transaction
from django.db.models import Q
from rest_framework import serializers

from apps.enterprise.models import Membership
from apps.users.models import User


PRIVATE_VISIBILITY = "private"
RESTRICTED_VISIBILITY = "restricted"
ORGANIZATION_VISIBILITY = "organization"

RESOURCE_ROLE_LEVEL = {
    "viewer": 10,
    "user": 20,
    "operator": 30,
    "editor": 40,
}

ORGANIZATION_ROLE_LEVEL = {
    Membership.Role.VIEWER: 10,
    Membership.Role.AUDITOR: 20,
    Membership.Role.OPERATOR: 30,
    Membership.Role.DEVELOPER: 40,
    Membership.Role.ADMIN: 50,
    Membership.Role.OWNER: 60,
}

OPERATION_RESOURCE_ROLE = {
    "discover": "viewer",
    "run": "user",
    "operate": "operator",
    "edit": "editor",
}

OPERATION_ORGANIZATION_ROLE = {
    "discover": Membership.Role.VIEWER,
    "run": Membership.Role.VIEWER,
    "operate": Membership.Role.OPERATOR,
    "edit": Membership.Role.DEVELOPER,
}


def is_platform_admin(user):
    return bool(
        user
        and user.is_authenticated
        and (user.is_superuser or user.role == User.Role.ADMIN)
    )


def is_platform_auditor(user):
    return bool(
        user
        and user.is_authenticated
        and user.role == User.Role.AUDITOR
    )


def _membership_queryset(user):
    if not user or not user.is_authenticated:
        return Membership.objects.none()
    return Membership.objects.filter(
        user=user,
        is_active=True,
        organization__is_active=True,
    )


def organization_role(user, organization_id):
    if is_platform_admin(user):
        return Membership.Role.OWNER
    if organization_id is None:
        return None
    return _membership_queryset(user).filter(
        organization_id=organization_id,
    ).values_list("role", flat=True).first()


def has_organization_role(user, organization, minimum_role):
    if is_platform_admin(user):
        return True
    organization_id = getattr(organization, "id", organization)
    role = organization_role(user, organization_id)
    return (
        ORGANIZATION_ROLE_LEVEL.get(role, 0)
        >= ORGANIZATION_ROLE_LEVEL[minimum_role]
    )


def _organization_ids_at_least(user, minimum_role):
    minimum = ORGANIZATION_ROLE_LEVEL[minimum_role]
    roles = [
        role for role, level in ORGANIZATION_ROLE_LEVEL.items()
        if level >= minimum
    ]
    return _membership_queryset(user).filter(
        role__in=roles,
    ).values_list("organization_id", flat=True)


def _grant_roles_at_least(minimum_role):
    minimum = RESOURCE_ROLE_LEVEL[minimum_role]
    return [
        role for role, level in RESOURCE_ROLE_LEVEL.items()
        if level >= minimum
    ]


def accessible_resources(queryset, user, *, operation="discover"):
    """Filter resources by tenant membership, visibility and per-resource grant."""

    if operation not in OPERATION_RESOURCE_ROLE:
        raise ValueError(f"Unsupported resource operation: {operation}")
    if not user or not user.is_authenticated:
        return queryset.none()
    if is_platform_admin(user):
        return queryset

    memberships = _membership_queryset(user)
    organization_ids = memberships.values_list("organization_id", flat=True)
    administrator_ids = _organization_ids_at_least(user, Membership.Role.ADMIN)
    operation_organization_ids = _organization_ids_at_least(
        user, OPERATION_ORGANIZATION_ROLE[operation],
    )
    grant_roles = _grant_roles_at_least(OPERATION_RESOURCE_ROLE[operation])

    rule = (
        Q(created_by=user)
        | Q(organization_id__in=administrator_ids)
        | Q(
            organization_id__in=operation_organization_ids,
            visibility=ORGANIZATION_VISIBILITY,
        )
        | Q(
            organization_id__in=organization_ids,
            visibility=RESTRICTED_VISIBILITY,
            access_grants__user=user,
            access_grants__role__in=grant_roles,
        )
    )
    if operation in ("discover", "run"):
        # Published global catalog entries are available to authenticated users.
        rule |= Q(
            organization__isnull=True,
            is_public=True,
            visibility=ORGANIZATION_VISIBILITY,
        )
        rule |= Q(
            organization__isnull=True,
            visibility=RESTRICTED_VISIBILITY,
            access_grants__user=user,
            access_grants__role__in=grant_roles,
        )
    return queryset.filter(rule).distinct()


def can_access_resource(resource, user, *, operation="discover"):
    if not resource or not user or not user.is_authenticated:
        return False
    return accessible_resources(
        type(resource).objects.filter(pk=resource.pk),
        user,
        operation=operation,
    ).exists()


def can_manage_resource_permissions(resource, user):
    if is_platform_admin(user):
        return True
    if resource.created_by_id == getattr(user, "id", None):
        return True
    return has_organization_role(
        user, resource.organization_id, Membership.Role.ADMIN,
    )


def can_create_agents(user, organization=None):
    if is_platform_admin(user):
        return True
    if organization is not None:
        return has_organization_role(user, organization, Membership.Role.DEVELOPER)
    return _organization_ids_at_least(
        user, Membership.Role.DEVELOPER,
    ).exists()


def can_update_agents(user, resource=None, organization=None):
    if resource is not None:
        return can_access_resource(resource, user, operation="edit")
    return can_create_agents(user, organization)


def can_delete_agents(user, resource=None, organization=None):
    if is_platform_admin(user):
        return True
    if resource is not None:
        return bool(
            resource.created_by_id == getattr(user, "id", None)
            or has_organization_role(
                user, resource.organization_id, Membership.Role.ADMIN,
            )
        )
    if organization is not None:
        return has_organization_role(user, organization, Membership.Role.ADMIN)
    return _organization_ids_at_least(user, Membership.Role.ADMIN).exists()


def can_toggle_agents(user, resource=None, organization=None):
    if resource is not None:
        return can_access_resource(resource, user, operation="operate")
    if organization is not None:
        return has_organization_role(user, organization, Membership.Role.OPERATOR)
    return _organization_ids_at_least(user, Membership.Role.OPERATOR).exists()


def can_administer_agents(user, organization=None):
    return any((
        can_update_agents(user, organization=organization),
        can_delete_agents(user, organization=organization),
        can_toggle_agents(user, organization=organization),
    ))


def can_create_applications(user, organization=None):
    return can_create_agents(user, organization)


def can_update_applications(user, resource=None, organization=None):
    if resource is not None:
        return can_access_resource(resource, user, operation="edit")
    return can_create_agents(user, organization)


def can_toggle_applications(user, resource=None, organization=None):
    if resource is not None:
        return can_access_resource(resource, user, operation="operate")
    return can_toggle_agents(user, organization=organization)


def filter_accessible_agent_bindings(definition, user, organization_id):
    """Remove Agent bindings that the caller is not allowed to run."""

    from apps.agents.models import Agent

    result = deepcopy(definition)
    bindings = result.get("agent_bindings", [])
    agent_ids = {
        binding.get("agent_id")
        for binding in bindings
        if binding.get("agent_id") is not None
    }
    visible_ids = set(accessible_resources(
        Agent.objects.filter(
            Q(organization_id=organization_id) | Q(organization__isnull=True),
            id__in=agent_ids,
            is_active=True,
        ),
        user,
        operation="run",
    ).values_list("id", flat=True))
    result["agent_bindings"] = [
        binding for binding in bindings
        if binding.get("agent_id") in visible_ids
    ]
    return result


class ResourceGrantSerializer(serializers.Serializer):
    user_id = serializers.IntegerField()
    role = serializers.ChoiceField(choices=tuple(RESOURCE_ROLE_LEVEL))


class ResourcePermissionUserSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    username = serializers.CharField(read_only=True)
    email = serializers.EmailField(read_only=True, allow_blank=True)


class ResourcePermissionSerializer(serializers.Serializer):
    visibility = serializers.ChoiceField(choices=(
        PRIVATE_VISIBILITY,
        RESTRICTED_VISIBILITY,
        ORGANIZATION_VISIBILITY,
    ))
    grants = ResourceGrantSerializer(many=True, required=False, default=list)
    available_users = ResourcePermissionUserSerializer(many=True, read_only=True)

    def validate_grants(self, grants):
        instance = self.instance
        if instance is None:
            return grants
        valid_roles = set(RESOURCE_ROLE_LEVEL)
        seen = set()
        normalized = []
        for index, grant in enumerate(grants):
            user_id = grant.get("user_id")
            role = grant.get("role", "user")
            if not isinstance(user_id, int):
                raise serializers.ValidationError(
                    f"第 {index + 1} 项缺少有效的 user_id。")
            if role not in valid_roles:
                raise serializers.ValidationError(
                    f"第 {index + 1} 项包含无效角色。")
            if user_id in seen:
                raise serializers.ValidationError("同一账号不能重复授权。")
            seen.add(user_id)
            normalized.append({"user_id": user_id, "role": role})

        if instance.created_by_id in seen:
            raise serializers.ValidationError("创建者已隐式拥有全部权限，无需重复授权。")
        eligible = User.objects.filter(is_active=True).exclude(username="system")
        if instance.organization_id is not None:
            eligible = eligible.filter(
                organization_memberships__organization_id=instance.organization_id,
                organization_memberships__is_active=True,
            )
        eligible_ids = set(eligible.values_list("id", flat=True))
        invalid = seen - eligible_ids
        if invalid:
            raise serializers.ValidationError("只能授权资源所属组织的有效成员。")
        return normalized

    def validate(self, attrs):
        if attrs["visibility"] == RESTRICTED_VISIBILITY and not attrs.get("grants"):
            raise serializers.ValidationError({
                "grants": "指定账号范围至少需要一条授权。",
            })
        if attrs["visibility"] != RESTRICTED_VISIBILITY:
            attrs["grants"] = []
        return attrs

    @transaction.atomic
    def update(self, instance, validated_data):
        grants = validated_data.pop("grants", [])
        instance.visibility = validated_data["visibility"]
        instance.save(update_fields=("visibility", "updated_at"))
        instance.access_grants.all().delete()
        grant_model = instance.access_grants.model
        parent_field = "agent" if instance._meta.label_lower == "agents.agent" else "application"
        grant_model.objects.bulk_create([
            grant_model(**{
                parent_field: instance,
                "user_id": grant["user_id"],
                "role": grant["role"],
            })
            for grant in grants
        ])
        return instance

    def create(self, validated_data):  # pragma: no cover - update-only serializer
        raise NotImplementedError

    def to_representation(self, instance):
        eligible = User.objects.filter(is_active=True).exclude(username="system")
        if instance.organization_id is not None:
            eligible = eligible.filter(
                organization_memberships__organization_id=instance.organization_id,
                organization_memberships__is_active=True,
            )
        eligible = eligible.exclude(pk=instance.created_by_id).distinct().order_by("username")
        return {
            "visibility": instance.visibility,
            "grants": list(instance.access_grants.order_by("user_id").values(
                "user_id", "role",
            )),
            "available_users": list(eligible.values("id", "username", "email")),
        }
