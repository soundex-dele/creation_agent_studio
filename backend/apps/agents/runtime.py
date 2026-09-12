from copy import deepcopy

from modules.catalog.models import AgentDeployment, DeploymentEnvironment


def get_agent_definition(agent, *, environment=DeploymentEnvironment.PRODUCTION):
    """Return the deployed definition, falling back to the editable draft.

    Product chat previews may use an unpublished draft; durable execution paths
    should pass a revision explicitly or ensure a deployment exists.
    """
    deployment = AgentDeployment.objects.filter(
        agent=agent, environment=environment).select_related('revision').first()
    if deployment is not None:
        return deepcopy(deployment.revision.content)
    draft = getattr(agent, 'draft', None)
    return deepcopy(draft.content) if draft is not None else {}
