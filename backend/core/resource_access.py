"""Shared visibility rules for user-facing applications and agents."""

from copy import deepcopy

from django.db.models import Q
from rest_framework import serializers

from apps.users.models import User


ADMIN_SCOPE = "admin"
RESTRICTED_SCOPE = "restricted"
ORGANIZATION_SCOPE = "organization"


def is_platform_admin(user):
    return bool(
        user
        and user.is_authenticated
        and (user.is_superuser or user.role == User.Role.ADMIN)
    )


def can_create_agents(user):
    return is_platform_admin(user) or bool(
        user and user.is_authenticated and user.can_create_agents
    )


def can_view_agents(user):
    return is_platform_admin(user) or bool(
        user and user.is_authenticated and user.can_view_agents
    )


def can_update_agents(user):
    return is_platform_admin(user) or bool(
        user and user.is_authenticated and user.can_update_agents
    )


def can_delete_agents(user):
    return is_platform_admin(user) or bool(
        user and user.is_authenticated and user.can_delete_agents
    )


def can_toggle_agents(user):
    return is_platform_admin(user) or bool(
        user and user.is_authenticated and user.can_toggle_agents
    )


def can_administer_agents(user):
    return any((
        can_update_agents(user),
        can_delete_agents(user),
        can_toggle_agents(user),
    ))


def can_toggle_applications(user):
    return is_platform_admin(user) or bool(
        user and user.is_authenticated and user.can_toggle_applications
    )


def can_view_applications(user):
    return is_platform_admin(user) or bool(
        user and user.is_authenticated and user.can_view_applications
    )


def can_view_resource_model(model, user):
    label = model._meta.label_lower
    if label == "agents.agent":
        return can_view_agents(user)
    if label == "applications.application":
        return can_view_applications(user)
    return True


def accessible_resources(queryset, user):
    """Return only resources that the user may discover or execute."""

    if not user or not user.is_authenticated:
        return queryset.none()
    if is_platform_admin(user):
        return queryset
    organization_ids = user.organization_memberships.filter(
        is_active=True,
    ).values_list("organization_id", flat=True)
    tenant_boundary = Q(organization_id__in=organization_ids) | Q(
        organization__isnull=True
    )
    if can_view_resource_model(queryset.model, user):
        return queryset.filter(tenant_boundary).distinct()
    return queryset.filter(
        tenant_boundary,
    ).filter(
        Q(access_scope=RESTRICTED_SCOPE, allowed_users=user)
        | Q(access_scope=ORGANIZATION_SCOPE)
    ).distinct()


def can_access_resource(resource, user):
    if not user or not user.is_authenticated:
        return False
    if is_platform_admin(user):
        return True
    if resource.organization_id is not None and not user.organization_memberships.filter(
        organization_id=resource.organization_id,
        is_active=True,
    ).exists():
        return False
    if can_view_resource_model(type(resource), user):
        return True
    return bool(
        resource.access_scope == ORGANIZATION_SCOPE
        or (
            resource.access_scope == RESTRICTED_SCOPE
            and resource.allowed_users.filter(pk=user.pk).exists()
        )
    )


def filter_accessible_agent_bindings(definition, user, organization_id):
    """Remove Agent bindings that would reveal or execute inaccessible Agents."""

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
    ).values_list("id", flat=True))
    result["agent_bindings"] = [
        binding for binding in bindings
        if binding.get("agent_id") in visible_ids
    ]
    return result


class ResourcePermissionSerializer(serializers.Serializer):
    access_scope = serializers.ChoiceField(choices=(
        ADMIN_SCOPE,
        RESTRICTED_SCOPE,
        ORGANIZATION_SCOPE,
    ))
    allowed_user_ids = serializers.PrimaryKeyRelatedField(
        source="allowed_users",
        queryset=User.objects.exclude(username="system").filter(is_active=True),
        many=True,
        required=False,
        default=list,
    )

    def validate(self, attrs):
        scope = attrs["access_scope"]
        allowed_users = attrs.get("allowed_users", [])
        if scope == RESTRICTED_SCOPE and not allowed_users:
            raise serializers.ValidationError({
                "allowed_user_ids": "请至少选择一个账号。",
            })
        if scope != RESTRICTED_SCOPE:
            attrs["allowed_users"] = []
        return attrs

    def update(self, instance, validated_data):
        allowed_users = validated_data.pop("allowed_users", [])
        instance.access_scope = validated_data["access_scope"]
        instance.save(update_fields=("access_scope", "updated_at"))
        instance.allowed_users.set(allowed_users)
        return instance

    def create(self, validated_data):  # pragma: no cover - update-only serializer
        raise NotImplementedError

    def to_representation(self, instance):
        return {
            "access_scope": instance.access_scope,
            "allowed_user_ids": list(
                instance.allowed_users.order_by("id").values_list("id", flat=True)
            ),
        }
