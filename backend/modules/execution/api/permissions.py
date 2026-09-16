from apps.enterprise.models import Membership
from modules.execution.models import Run


TERMINAL_RUN_STATUSES = (
    Run.Status.SUCCEEDED,
    Run.Status.FAILED,
    Run.Status.CANCELLED,
)


def can_delete_run(run, request):
    """Return whether the current actor may request Run deletion."""

    if not request or not request.user.is_authenticated:
        return False
    if request.user.is_superuser:
        return True
    membership = getattr(request, "organization_membership", None)
    if membership is None:
        return False
    if membership.role in (Membership.Role.OWNER, Membership.Role.ADMIN):
        return True
    return (
        membership.role == Membership.Role.DEVELOPER
        and run.owner_id == request.user.id
    )
