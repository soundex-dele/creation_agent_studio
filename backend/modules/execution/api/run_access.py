"""Shared task-tree policy. Unmigrated app rules are a frozen compatibility baseline."""
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
    # These applications keep their sessions/state private to the initiating
    # user. Generic Run endpoints must preserve that boundary for the tree.
    if root.executor_key in {"prompt-master"}:
        return root.owner_id == user.id
    if root.executor_key == "repo-explainer":
        from app_center.repo_explainer.backend.access import can_access_run as repo_access
        return repo_access(user, root)
    if root.executor_key == "project-promotion":
        from app_center.project_promotion.backend.access import can_access_run as promotion_access
        return promotion_access(user, root)
    if root.executor_key == "rental-growth-assistant":
        from app_center.rental_growth_assistant.backend.access import can_access_run as rental_access
        return rental_access(user, root)
    if root.executor_key == "research-assistant" or (root.input or {}).get("research_project_id"):
        from django.apps import apps
        if not apps.is_installed("app_center.research_assistant.backend"):
            return False
        from app_center.research_assistant.backend.access import can_access_run as research_access
        return research_access(user, root)
    if root.executor_key == "meeting-assistant":
        if root.owner_id != user.id:
            return False
        from django.http import Http404
        from rest_framework.exceptions import APIException
        from app_center.meeting_assistant.backend.access import recording_for
        try:
            recording_for(user, root.organization_id, root.source_id,
                          (root.input or {}).get("record_id"))
        except (Http404, APIException, ValueError):
            return False
        return True
    if root.executor_key in ("ai-drawing", "animation-studio"):
        if root.owner_id != user.id:
            return False
        from django.http import Http404
        from rest_framework.exceptions import APIException
        if root.executor_key == "animation-studio":
            from app_center.animation_studio.backend.access import application_for
        else:
            from app_center.ai_drawing.backend.access import application_for
        try:
            application_for(user, root.organization_id, root.source_id)
        except (Http404, APIException, ValueError):
            return False
        return True
    if (root.input or {}).get("document_id"):
        if root.owner_id != user.id:
            return False
        from django.apps import apps
        from django.http import Http404
        from rest_framework.exceptions import APIException
        if not apps.is_installed("app_center.documents.backend"):
            return False
        from app_center.documents.backend.models import Document
        from app_center.documents.backend.access import document_for
        doc = Document.objects.filter(pk=root.input["document_id"]).first()
        if doc is None:
            return False
        try:
            document_for(user, root.organization_id, doc.application_id, doc.pk)
        except (Http404, APIException):
            return False
        return True
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
