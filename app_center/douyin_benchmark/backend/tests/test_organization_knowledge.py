import copy
import json
from unittest.mock import Mock

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

from apps.enterprise.models import Membership
from apps.knowledge.models import KnowledgeBase, KnowledgeDocument
from apps.knowledge.execution import execute_knowledge_index
from apps.knowledge.retrieval import search
from .. import models as m
from ..organization_knowledge import public_card
from ...runtime import execute
from .test_douyin import ctx, claim, script  # noqa: F401
from .test_research import workspace_ctx, start, finish  # noqa: F401
from .test_knowledge import save_card


def library(ctx, name='组织资料'):
    return KnowledgeBase.objects.create(organization=ctx.org, name=name)


def share(ctx, card, base, **values):
    return ctx.client.post(ctx.root + f'/knowledge-cards/{card.pk}/shares',
        {'knowledge_base_id': base.pk, 'revision': card.revision, **values}, format='json')


def index_document(document):
    document.refresh_from_db()
    run = document.indexing_run
    output = execute_knowledge_index({'run_id': str(run.pk), 'definition_snapshot': run.definition_snapshot}, Mock(cancelled=False))
    document.refresh_from_db()
    return output


def shared(ctx, monkeypatch):
    _, _, card, _ = save_card(ctx, monkeypatch)
    base = library(ctx)
    response = share(ctx, card, base)
    assert response.status_code == 200, response.data
    document = KnowledgeDocument.objects.get(pk=response.data['document_id'])
    index_document(document)
    chunk = search(organization_id=ctx.org.pk, query='受众', knowledge_base_ids=[base.pk])[1][0]
    return card, base, document, chunk


def topics(ctx, chunk, key='org-topics', **extra):
    return start(ctx, {'kind': 'topics', 'positioning': '科普', 'theme': '受众',
                      'organization_knowledge_chunks': [{'chunk_id': chunk['chunk_id'], 'revision': chunk['revision']}], **extra}, key)


def test_share_duplicate_privacy_multibase_and_independent_deletion(workspace_ctx, monkeypatch):
    ctx = workspace_ctx
    card, base, document, chunk = shared(ctx, monkeypatch)
    again = share(ctx, card, base)
    assert again.data['document_id'] == document.pk
    assert m.CreationKnowledgeShare.objects.count() == 1
    with pytest.raises(IntegrityError), transaction.atomic():
        existing = m.CreationKnowledgeShare.objects.get()
        existing.pk = None
        existing.save(force_insert=True)
    assert '围绕受众' in document.content and '拍摄前先明确受众' in document.content
    public = json.dumps(public_card(card), ensure_ascii=False)
    for key in ['task_id', 'work_id', 'account_id', 'candidate_id', 'extraction_key']:
        assert key not in public and key not in document.metadata
    assert str(card.pk) not in document.content
    assert chunk['revision'] == document.active_revision
    assert chunk['provenance']['basis'] == 'author_view'
    second = library(ctx, '第二个库')
    assert share(ctx, card, second).data['document_id'] != document.pk
    assert ctx.client.delete(ctx.root + f'/knowledge-cards/{card.pk}').status_code == 204
    document.refresh_from_db()
    assert not document.is_deleted
    assert search(organization_id=ctx.org.pk, query='受众', knowledge_base_ids=[base.pk])[1]


def test_manual_update_old_index_isolation_failure_and_recreate(ctx, monkeypatch):
    card, base, document, old_chunk = shared(ctx, monkeypatch)
    old_revision = document.active_revision
    card.text = '新版本：受众需要明确的操作步骤。'; card.revision += 1; card.save()
    document.refresh_from_db()
    assert '新版本' not in document.content
    assert share(ctx, card, base, revision=1).status_code == 409
    assert share(ctx, card, base).data['document_id'] == document.pk
    document.refresh_from_db()
    assert document.active_revision == 0 and document.pending_revision > old_revision
    assert search(organization_id=ctx.org.pk, query='受众', knowledge_base_ids=[base.pk])[1] == []
    assert topics(ctx, old_chunk).status_code == 409
    old_run = document.indexing_run
    with monkeypatch.context() as patch:
        patch.setattr('apps.knowledge.execution.extract_document', Mock(side_effect=ValueError('index failed')))
        with pytest.raises(ValueError):
            index_document(document)
    assert share(ctx, card, base).data['index_status'] == 'pending'
    document.refresh_from_db()
    assert document.pending_revision > old_run.definition_snapshot['revision']
    stale = execute_knowledge_index({'run_id': str(old_run.pk), 'definition_snapshot': old_run.definition_snapshot}, Mock(cancelled=False))
    assert stale['superseded']
    index_document(document)
    assert document.status == 'ready'
    document.is_deleted = True; document.save(update_fields=['is_deleted'])
    assert share(ctx, card, base).status_code == 409
    assert ctx.client.get(ctx.root + f'/knowledge-cards/{card.pk}/shares').data['results'][0]['document_deleted']
    response = share(ctx, card, base, recreate=True)
    assert response.data['document_id'] != document.pk
    assert m.CreationKnowledgeShare.objects.count() == 1
    assert share(ctx, card, base, recreate=True).data['document_id'] == response.data['document_id']


def test_share_permissions_scope_and_disallowed_methods(ctx, monkeypatch):
    card, base, document, chunk = shared(ctx, monkeypatch)
    endpoint = ctx.root + f'/knowledge-cards/{card.pk}/shares'
    assert ctx.client.patch(endpoint, {}, format='json').status_code == 405
    assert ctx.client.delete(endpoint).status_code == 405
    ctx.client.force_authenticate(ctx.reader)
    assert ctx.client.get(endpoint).status_code == 404
    assert share(ctx, card, base).status_code == 404
    ctx.client.force_authenticate(ctx.owner)
    internal = card.library.knowledge_base
    assert share(ctx, card, internal).status_code == 404
    other = get_user_model().objects.create_user(username='other-org-knowledge')
    foreign_base = KnowledgeBase.objects.create(organization=other.owned_organizations.get(), name='其他组织')
    assert share(ctx, card, foreign_base).status_code == 404
    base.is_active = False; base.save()
    assert share(ctx, card, base).status_code == 404
    # Retain card ownership but remove organization write permission.
    Membership.objects.filter(organization=ctx.org, user=ctx.owner).update(role=Membership.Role.VIEWER)
    assert not ctx.client.get(endpoint).data['can_share']
    assert share(ctx, card, base).status_code == 403


def test_creation_freezes_server_content_and_inherits_snapshot(workspace_ctx, monkeypatch):
    ctx = workspace_ctx
    card, base, document, chunk = shared(ctx, monkeypatch)
    response = topics(ctx, chunk, organization_knowledge_chunks=[{**chunk, 'snippet': '客户端伪造内容'}])
    assert response.status_code == 201, response.data
    task = m.Task.objects.get(pk=response.data['id'])
    frozen = copy.deepcopy(task.input['reference']['organization_knowledge'])
    assert frozen[0]['snippet'] == chunk['snippet']
    assert 'organization_knowledge' not in task.input['brief']
    assert response.data['output']['organization_knowledge'] == frozen
    task.output = {'topics': [{'title': '受众', 'angle': '问题', 'hook': '开头'}]}; task.save(); finish(task)
    card.text = '后来修改的观点'; card.revision += 1; card.save()
    share(ctx, card, base); index_document(document)
    for kind in ['script', 'article']:
        response = start(ctx, {'kind': kind, 'source_task_id': str(task.pk)}, kind)
        assert response.status_code == 201, response.data
        assert response.data['output']['organization_knowledge'] == frozen
    document.is_deleted = True; document.save()
    assert start(ctx, {'kind': 'script', 'source_task_id': str(task.pk)}, 'deleted').status_code == 400
    assert ctx.client.get(ctx.root + f'/tasks/{task.pk}').data['output']['organization_knowledge'] == frozen


def test_organization_references_reach_all_prompts(ctx, monkeypatch):
    _, _, _, chunk = shared(ctx, monkeypatch)
    captured = {}
    def model(task, prompt, data, *args, **kwargs):
        captured[task.kind] = (prompt, data)
        if task.kind == 'topics':
            return {'topics': [{'title': f'选题{i}', 'angle': '角度', 'hook': '开头'} for i in range(3)]}
        if task.kind == 'script':
            return script()
        return {'title': '文章', 'body': '参考作者观点的文章', 'notes': []}
    monkeypatch.setattr('app_center.douyin_benchmark.backend.analysis.call_model', model)
    response = topics(ctx, chunk)
    task = m.Task.objects.get(pk=response.data['id']); execute(*claim(task)); finish(task)
    for kind in ['script', 'article']:
        response = start(ctx, {'kind': kind, 'source_task_id': str(task.pk)}, kind)
        assert response.status_code == 201, response.data
        execute(*claim(m.Task.objects.get(pk=response.data['id'])))
    assert set(captured) == {'topics', 'script', 'article'}
    for prompt, data in captured.values():
        assert 'reference.organization_knowledge' in prompt
        assert '不能将组织资料自动写成用户亲身经历' in prompt
        assert data['reference']['organization_knowledge'][0]['snippet'] == chunk['snippet']


def test_organization_member_can_reuse_shared_document_but_not_private_card(workspace_ctx, monkeypatch):
    ctx = workspace_ctx
    card, base, document, _ = shared(ctx, monkeypatch)
    organization_root = ctx.root.split('/applications/')[0]
    ctx.client.force_authenticate(ctx.reader)
    assert ctx.client.get(ctx.root + f'/knowledge-cards/{card.pk}').status_code == 404
    response = ctx.client.post(organization_root + '/knowledge-search/',
                              {'query': '受众', 'knowledge_base_ids': [base.pk]}, format='json')
    assert response.status_code == 200, response.data
    chunk = response.data['results'][0]
    assert chunk['revision'] == document.active_revision
    assert chunk['provenance']['basis'] == 'author_view'
    response = topics(ctx, chunk, key='member-topics')
    assert response.status_code == 201, response.data
    assert m.Task.objects.get(pk=response.data['id']).owner_id == ctx.reader.pk
    content = ctx.client.get(organization_root + f'/knowledge-bases/{base.pk}/documents/{document.pk}/content/')
    assert content.status_code == 200
    assert '原始出处' in content.content.decode()
    assert str(card.pk) not in content.content.decode()


def test_regular_organization_document_without_douyin_provenance_is_selectable(ctx):
    from apps.knowledge.services import reindex_document
    base = library(ctx)
    document = KnowledgeDocument.objects.create(organization=ctx.org, knowledge_base=base,
        title='产品说明', content='受众适用范围与产品资料', original_filename='产品说明.txt', mime_type='text/plain')
    reindex_document(document, ctx.owner); index_document(document)
    chunk = search(organization_id=ctx.org.pk, query='受众', knowledge_base_ids=[base.pk])[1][0]
    response = topics(ctx, chunk)
    assert response.status_code == 201, response.data
    assert response.data['output']['organization_knowledge'][0]['provenance'] == {}


def test_selection_validation_limits_private_scope_and_disabled_sources(ctx, monkeypatch):
    card, base, document, chunk = shared(ctx, monkeypatch)
    selection = {'chunk_id': chunk['chunk_id'], 'revision': chunk['revision']}
    assert topics(ctx, chunk, organization_knowledge_chunks=[selection, selection]).status_code == 400
    assert topics(ctx, chunk, organization_knowledge_chunks=[{**selection, 'revision': 999}]).status_code == 409
    assert topics(ctx, chunk, organization_knowledge_chunks=[selection] * 10,
                  knowledge_cards=[{'id': str(card.pk), 'revision': 1}]).status_code == 400
    response = topics(ctx, chunk)
    assert response.status_code == 201, response.data
    task = m.Task.objects.get(pk=response.data['id']); task.output = {'topics': [{'title': '选题'}]}; task.save(); finish(task)
    assert start(ctx, {'kind': 'script', 'source_task_id': str(task.pk), 'organization_knowledge_chunks': [selection]}, 'smuggle').status_code == 400
    base.is_active = False; base.save()
    assert topics(ctx, chunk, key='disabled').status_code == 409
    assert start(ctx, {'kind': 'article', 'source_task_id': str(task.pk)}, 'disabled-inherit').status_code == 400
    base.is_active = True; base.save()
    # Private card chunks cannot be used through the organization reference path.
    index_document(card.document)
    private = card.document.chunks.first()
    assert topics(ctx, chunk, key='private', organization_knowledge_chunks=[{'chunk_id': private.pk, 'revision': private.revision}]).status_code == 409
    other = get_user_model().objects.create_user(username='foreign-reader')
    from ..organization_knowledge import freeze_chunks, check_inherited
    from ..services import Conflict
    from rest_framework.exceptions import ValidationError
    scope = {'organization_id': other.owned_organizations.get().pk}
    with pytest.raises(Conflict):
        freeze_chunks(scope, [selection])
    with pytest.raises(ValidationError):
        check_inherited(scope, task.input['reference']['organization_knowledge'])


def test_history_survives_target_account_deletion(ctx, monkeypatch):
    from .test_research import other_account
    from .test_owned import setup_profile, confirm
    _, _, _, chunk = shared(ctx, monkeypatch)
    target = other_account(ctx); profile = setup_profile(ctx, target); confirm(ctx, profile)
    response = topics(ctx, chunk, target_account_id=str(target.pk))
    assert response.status_code == 201, response.data
    task = m.Task.objects.get(pk=response.data['id']); finish(task)
    frozen = task.input['reference']['organization_knowledge']
    assert ctx.client.delete(ctx.root + f'/accounts/{target.pk}').status_code == 204
    assert ctx.client.get(ctx.root + f'/tasks/{task.pk}').data['output']['organization_knowledge'] == frozen


@pytest.mark.django_db(transaction=True)
def test_concurrent_share_returns_one_document(ctx, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from django.db import connection, connections
    from modules.tenancy.database import set_local_organization
    from ..organization_knowledge import publish
    _, _, card, _ = save_card(ctx, monkeypatch)
    base = library(ctx)
    barrier = Barrier(2)
    def submit():
        try:
            barrier.wait(timeout=10)
            if connection.vendor == 'postgresql':
                with transaction.atomic():
                    set_local_organization(ctx.org.pk)
                    return publish(card, ctx.owner, {'knowledge_base_id': base.pk, 'revision': 1, 'recreate': False})
            return publish(card, ctx.owner, {'knowledge_base_id': base.pk, 'revision': 1, 'recreate': False})
        finally:
            connections.close_all()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: submit(), range(2)))
    assert results[0]['document_id'] == results[1]['document_id']
    assert m.CreationKnowledgeShare.objects.filter(card=card, knowledge_base=base).count() == 1
    assert KnowledgeDocument.objects.filter(knowledge_base=base).count() == 1
