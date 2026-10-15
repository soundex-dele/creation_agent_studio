"""Application-owned policies registered with the trusted host."""
from modules.platform_api.extensions import ApplicationContributions


def run_access(user, run):
    if run.executor_key != 'research-assistant' and not (run.input or {}).get('research_project_id'):
        return None
    from .backend.access import can_access_run
    return can_access_run(user, run)


def knowledge_context(document):
    project_id = (document.metadata or {}).get('research_project_id')
    return {'research_project_id': project_id} if project_id else {}


provider = ApplicationContributions(run_access=run_access, knowledge_context=knowledge_context)
