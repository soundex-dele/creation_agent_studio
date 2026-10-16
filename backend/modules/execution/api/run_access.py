"""Shared task-tree policy composed with application-owned access contributions."""
from modules.execution.models import Run
from modules.execution.api.serializers import RunSerializer
from apps.applications.app_center.extensions import run_access, run_access_many


_UNRESOLVED = object()


def prime_run_access(user, runs, *, run_cache, decision_cache):
    """Resolve ancestors and application permissions in batches for one request."""
    frontier = runs
    while frontier:
        missing = {(run.organization_id, run.parent_id) for run in frontier
                   if run.parent_id and (run.organization_id, run.parent_id) not in run_cache}
        if not missing:
            break
        parents = list(Run.objects.filter(
            organization_id__in={org for org, _ in missing},
            pk__in={pk for _, pk in missing},
        ).defer("output_summary"))
        run_cache.update(dict.fromkeys(missing))
        run_cache.update(((run.organization_id, run.pk), run) for run in parents)
        frontier = parents
    roots = {}
    for run in runs:
        root = root_run(run, run_cache=run_cache)
        if root and (user.pk, root.organization_id, root.pk) not in decision_cache:
            roots[root.pk] = root
    if not roots:
        return
    decisions = run_access_many(user, list(roots.values()))
    for root in roots.values():
        decision_cache[user.pk, root.organization_id, root.pk] = _can_access_root(
            user, root, application_decision=decisions[root.pk],
        )


def root_run(run, *, run_cache=None):
    root = run
    visited = {root.pk}
    while root.parent_id:
        if root.parent_id in visited:
            return None
        visited.add(root.parent_id)
        key = (run.organization_id, root.parent_id)
        if run_cache is not None and key in run_cache:
            root = run_cache[key]
        else:
            root = Run.objects.for_organization(run.organization_id).filter(pk=root.parent_id).first()
            if run_cache is not None:
                run_cache[key] = root
        if root is None:
            return None
    return root


def has_application_access_policy(run):
    from django.contrib.auth.models import AnonymousUser
    root = root_run(run)
    return root is None or run_access(AnonymousUser(), root) is not None


def can_access_run(user, run, *, run_cache=None, decision_cache=None):
    if not user.is_authenticated:
        return False
    root = root_run(run, run_cache=run_cache)
    if root is None:
        return False
    key = (user.pk, root.organization_id, root.pk)
    if decision_cache is not None and key in decision_cache:
        return decision_cache[key]
    decision = _can_access_root(user, root)
    if decision_cache is not None:
        decision_cache[key] = decision
    return decision


def _can_access_root(user, root, *, application_decision=_UNRESOLVED):
    decision = run_access(user, root) if application_decision is _UNRESOLVED else application_decision
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
