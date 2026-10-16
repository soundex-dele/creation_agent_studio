"""Douyin integration policies; the host only knows their contracts."""
from modules.platform_api.extensions import ApplicationContributions


def run_access(user, run):
    from .backend import access
    if run.executor_key == 'douyin-benchmark':
        return access.can_access_run(user, run)
    if run.executor_key == 'knowledge-index':
        from modules.platform_api.knowledge import KnowledgeDocument
        document = KnowledgeDocument.objects.filter(pk=run.source_id, knowledge_base__scope='douyin_creation').first()
        if document or (run.input or {}).get('douyin_knowledge_card_id'):
            return bool(document and access.can_access_knowledge_index(user, run, document))
    return None


def run_access_many(user, roots):
    from .backend.access import can_access_runs
    runs = [run for run in roots if run.executor_key == 'douyin-benchmark']
    return can_access_runs(user, runs) if runs else {}


def knowledge_context(document):
    if document.knowledge_base.scope != 'douyin_creation':
        return {}
    from .backend.models import CreationKnowledgeCard
    card = CreationKnowledgeCard.objects.filter(document=document, is_deleted=False).first()
    return {'douyin_knowledge_card_id': str(card.pk)} if card else {}


def case_navigation(case, user):
    if case.source_kind != 'douyin' or case.created_by_id != user.pk:
        return None
    from .backend.cases import source_navigation
    return source_navigation(case, user)


def case_targets(source, user, organization_id):
    if source != 'douyin':
        return None
    from modules.platform_api.identity import Application, accessible_resources
    applications = accessible_resources(Application.objects.for_organization(organization_id).filter(
        slug='douyin-benchmark', kind='custom', is_active=True), user, operation='run')
    return [{'id': item.pk, 'name': item.name} for item in applications.order_by('id')]


def dispatch_scheduled():
    from .backend.subscriptions import dispatch_due
    dispatch_due()


provider = ApplicationContributions(run_access=run_access, run_access_many=run_access_many, knowledge_context=knowledge_context,
                           run_access_input_keys=('task_id', 'douyin_knowledge_card_id'),
                           case_navigation=case_navigation, case_targets=case_targets,
                           dispatch_scheduled=dispatch_scheduled)
