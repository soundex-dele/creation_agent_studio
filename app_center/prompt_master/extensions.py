"""Application-owned policies registered with the trusted host."""
from modules.platform_api.extensions import ApplicationContributions


def run_access(user, run):
    if run.executor_key != 'prompt-master':
        return None
    return user.is_authenticated and run.owner_id == user.id


provider = ApplicationContributions(run_access=run_access)
