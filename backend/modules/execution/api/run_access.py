"""Shared task-tree policy composed with application-owned access contributions."""
from modules.execution.models import Run
from modules.execution.api.serializers import RunSerializer
from apps.applications.app_center.extensions import run_access


def root_run(run):
    root = run
    visited = {root.pk}
    while root.parent_id:
        if root.parent_id in visited:
            return None
        visited.add(root.parent_id)
        root = Run.objects.for_organization(run.organization_id).filter(pk=root.parent_id).first()
        if root is None:
            return None
    return root


def has_application_access_policy(run):
    from django.contrib.auth.models import AnonymousUser
    root = root_run(run)
    return root is None or run_access(AnonymousUser(), root) is not None


def can_access_run(user, run):
    if not user.is_authenticated:
        return False
    root = root_run(run)
    if root is None:
        return False
    decision = run_access(user, root)
    if decision is not None:
        return decision
    # Conversation APIs are owner-only, including for administrators. Apply
    # the same boundary to Run history and every endpoint exposing its data.
    # Workflow roots also expose their steps' conversations; checking the root
    # protects descendants even when they have no conversation_id of their own.
    # Access to a shared supervisor does not grant access to others' chats.
    if root.source_type == "workflow" or RunSerializer._conversation_id(root):
        return root.owner_id == user.id
    if root.source_type != "supervisor":
        return True
    if user.is_superuser or root.owner_id == user.id:
        return True
    from apps.agents.models import Agent
    from core.resource_access import can_access_resource

    supervisor = Agent.objects.select_related("supervisor_profile").filter(
        pk=root.source_id,
        organization_id=root.organization_id,
        kind=Agent.Kind.SUPERVISOR,
    ).first()
    if supervisor is None:
        return False
    return can_access_resource(supervisor, user, operation="run")
