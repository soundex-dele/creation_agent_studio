"""
Permission classes for the project.
"""
from rest_framework import permissions

from core.resource_access import (
    can_create_agents,
    can_delete_agents,
    can_toggle_agents,
    can_toggle_applications,
    can_update_agents,
)


class IsAdmin(permissions.BasePermission):
    """管理员权限"""

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and (request.user.is_superuser or request.user.role == 'admin')
        )


class CanCreateAgent(permissions.BasePermission):
    def has_permission(self, request, view):
        return can_create_agents(request.user)


class CanUpdateAgent(permissions.BasePermission):
    def has_permission(self, request, view):
        return can_update_agents(request.user)


class CanDeleteAgent(permissions.BasePermission):
    def has_permission(self, request, view):
        return can_delete_agents(request.user)


class CanToggleAgent(permissions.BasePermission):
    def has_permission(self, request, view):
        return can_toggle_agents(request.user)


class CanToggleApplication(permissions.BasePermission):
    def has_permission(self, request, view):
        return can_toggle_applications(request.user)


class IsProfessionalOrAdmin(permissions.BasePermission):
    """专业用户或管理员权限"""

    def has_permission(self, request, view):
        return request.user and request.user.role in ['professional', 'admin']


class IsMemberOrAbove(permissions.BasePermission):
    """成员及以上权限。"""

    def has_permission(self, request, view):
        return request.user and request.user.role in ['member', 'professional', 'admin']


# Backward-compatible import alias for integrations that imported the old class name.
IsCreatorOrAbove = IsMemberOrAbove


class IsOwnerOrReadOnly(permissions.BasePermission):
    """所有者可编辑，其他人只读"""

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        return obj.created_by == request.user
