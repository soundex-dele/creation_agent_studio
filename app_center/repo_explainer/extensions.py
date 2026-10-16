"""Application-owned policies registered with the trusted host."""
from modules.platform_api.extensions import ApplicationContributions


def run_access(user, run):
    if run.executor_key != 'repo-explainer':
        return None
    from .backend.access import can_access_run
    return can_access_run(user, run)


def run_access_many(user, roots):
    from .backend.access import can_access_runs
    runs = [run for run in roots if run.executor_key == 'repo-explainer']
    return can_access_runs(user, runs) if runs else {}


provider = ApplicationContributions(run_access=run_access, run_access_many=run_access_many,
                                    run_access_input_keys=('repo_project_id',))
