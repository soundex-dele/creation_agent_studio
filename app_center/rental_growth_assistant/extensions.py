"""Application-owned policies registered with the trusted host."""
from modules.platform_api.extensions import ApplicationContributions


def run_access(user, run):
    if run.executor_key != 'rental-growth-assistant':
        return None
    from .backend.access import can_access_run
    return can_access_run(user, run)


provider = ApplicationContributions(run_access=run_access)
