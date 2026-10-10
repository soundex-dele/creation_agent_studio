import copy
import uuid
from unittest.mock import Mock

import pytest
from rest_framework.exceptions import ValidationError
from django.http import Http404

from apps.knowledge.execution import execute_knowledge_index
from apps.knowledge.retrieval import search
from .. import knowledge as k, models as m
from ..research import scope_for
from ...runtime import execute
from .test_douyin import ctx, add_work, claim, post, script  # noqa: F401
from .test_research import start, finish, workspace_ctx  # noqa: F401


def source_task(ctx):
    work = add_work(ctx)
    response = post(ctx, {'kind': 'transcribe', 'work_id': str(work.pk)})
    assert response.status_code == 201, response.data
    task = m.Task.objects.get(pk=response.data['id'])
    task.output = {'segments': [{'id': 's1', 'start': 0, 'end': 4, 'text': '拍摄前先明确受众的问题。'}]}
    task.save(update_fields=['output'])
    finish(task)
    return task


def extract(ctx, monkeypatch):
    source = source_task(ctx)
    response = start(ctx, {'kind': 'knowledge_extract', 'source_task_id': str(source.pk)})
    assert response.status_code == 201, response.data
    task = m.Task.objects.get(pk=response.data['id'])
    candidate = {'title': '明确受众', 'text': '围绕受众的问题组织内容。', 'application_notes': '准备口播选题',
                 'tags': ['口播'], 'category': 'content', 'basis': 'author_view', 'refs': [f'{source.pk}:s1']}
    monkeypatch.setattr('app_center.douyin_benchmark.backend.analysis.call_model', lambda *a, **kw: {'cards': [candidate]})
    execute(*claim(task))
    task.refresh_from_db()
    finish(task)
    assert task.output['cards'][0]['evidence'][0]['text'] == source.output['segments'][0]['text']
    return source, task


def save_card(ctx, monkeypatch):
    source, task = extract(ctx, monkeypatch)
    fields = {key: task.output['cards'][0][key] for key in ['candidate_id', 'title', 'text', 'application_notes', 'tags']}
    payload = {'task_id': str(task.pk), 'cards': [fields]}
    response = ctx.client.post(ctx.root + '/knowledge-cards/confirm', payload, format='json')
    assert response.status_code == 200, response.data
    card = m.CreationKnowledgeCard.objects.get(pk=response.data['cards'][0]['id'])
    return source, task, card, payload


def index(card):
    card.document.refresh_from_db()
    run = card.document.indexing_run
    output = execute_knowledge_index({'run_id': str(run.pk), 'definition_snapshot': run.definition_snapshot,
                                     'organization_id': str(card.organization_id)}, Mock(cancelled=False))
    card.document.refresh_from_db()
    assert card.document.status == 'ready', output
    return output


def test_full_knowledge_flow_and_snapshot(workspace_ctx, monkeypatch):
    ctx = workspace_ctx
    source, task, card, payload = save_card(ctx, monkeypatch)
    assert ctx.client.post(ctx.root + '/knowledge-cards/confirm', payload, format='json').data['cards'][0]['id'] == str(card.pk)
    assert m.CreationKnowledgeCard.objects.count() == 1
    index(card)
    rows = ctx.client.get(ctx.root + '/knowledge-cards/recommend', {'query': '受众'}).data['results']
    assert rows[0]['id'] == str(card.pk)
    assert search(organization_id=ctx.org.pk, query='受众')[1] == []
    response = start(ctx, {'kind': 'topics', 'positioning': '科普', 'theme': '明确受众',
                          'knowledge_cards': [{'id': str(card.pk), 'revision': 1}]}, 'topics')
    assert response.status_code == 201, response.data
    topics = m.Task.objects.get(pk=response.data['id'])
    assert topics.input['reference']['knowledge'][0]['text'] == card.text
    topics.output = {'topics': [{'title': '受众', 'angle': '问题', 'hook': '先思考'}]}
    topics.save(update_fields=['output'])
    finish(topics)
    old = copy.deepcopy(topics.input['reference']['knowledge'])
    changed = {'revision': 1, 'title': '更新的受众', 'text': '更新后的内容', 'tags': []}
    assert ctx.client.patch(ctx.root + f'/knowledge-cards/{card.pk}', changed, format='json').status_code == 200
    for kind in ['script', 'article']:
        response = start(ctx, {'kind': kind, 'source_task_id': str(topics.pk)}, kind)
        assert response.status_code == 201, response.data
        created = m.Task.objects.get(pk=response.data['id'])
        assert created.input['reference']['knowledge'] == old
        assert response.data['output']['knowledge_cards'] == old
    assert ctx.client.get(ctx.root + '/knowledge-cards/recommend', {'query': '受众'}).data['results'] == []
    assert ctx.client.delete(ctx.root + f'/knowledge-cards/{card.pk}').status_code == 204
    assert start(ctx, {'kind': 'script', 'source_task_id': str(topics.pk)}, 'deleted').status_code == 400
    assert ctx.client.get(ctx.root + f'/tasks/{topics.pk}').data['output']['knowledge_cards'] == old


def test_privacy_revision_and_unselected(ctx, monkeypatch):
    _, task, card, payload = save_card(ctx, monkeypatch)
    response = start(ctx, {'kind': 'topics', 'positioning': '科普', 'theme': '其他'}, 'without')
    assert 'knowledge' not in m.Task.objects.get(pk=response.data['id']).input['reference']
    assert start(ctx, {'kind': 'topics', 'positioning': '科普', 'theme': '其他',
                      'knowledge_cards': [{'id': str(card.pk), 'revision': 2}]}, 'stale').status_code == 409
    ctx.client.force_authenticate(ctx.reader)
    assert ctx.client.get(ctx.root + '/knowledge-cards').data['count'] == 0
    assert ctx.client.get(ctx.root + f'/knowledge-cards/{card.pk}').status_code == 404
    assert ctx.client.get(ctx.root + '/knowledge-cards/recommend', {'query': '受众'}).data['results'] == []
    assert ctx.client.post(ctx.root + '/knowledge-cards/confirm', payload, format='json').status_code == 404
    assert start(ctx, {'kind': 'knowledge_extract', 'source_task_id': str(task.pk)}, 'foreign').status_code == 404
    assert start(ctx, {'kind': 'topics', 'positioning': '科普', 'theme': '其他',
                      'knowledge_cards': [{'id': str(card.pk), 'revision': 1}]}, 'foreign-card').status_code == 404
    from modules.execution.api.views import _can_access_run
    assert not _can_access_run(Mock(user=ctx.reader), card.document.indexing_run)
    assert _can_access_run(Mock(user=ctx.owner), card.document.indexing_run)


def test_deleted_source_preserves_card(ctx, monkeypatch):
    _, _, card, _ = save_card(ctx, monkeypatch)
    original = copy.deepcopy(card.evidence)
    assert ctx.client.delete(ctx.url).status_code == 204
    response = ctx.client.get(ctx.root + f'/knowledge-cards/{card.pk}')
    assert response.status_code == 200
    assert response.data['source_missing'] is True
    assert response.data['evidence'] == original


def test_index_failure_retry_and_supersession(ctx, monkeypatch):
    _, _, card, _ = save_card(ctx, monkeypatch)
    index(card)
    old_run = card.document.indexing_run
    changed = {'revision': 1, 'title': '更新', 'text': '新的受众资料'}
    assert ctx.client.patch(ctx.root + f'/knowledge-cards/{card.pk}', changed, format='json').status_code == 200
    stale = execute_knowledge_index({'run_id': str(old_run.pk), 'definition_snapshot': old_run.definition_snapshot}, Mock(cancelled=False))
    assert stale['superseded'] is True
    with monkeypatch.context() as patch:
        patch.setattr('apps.knowledge.execution.extract_document', Mock(side_effect=ValueError('index failed')))
        with pytest.raises(ValueError):
            index(card)
    assert ctx.client.get(ctx.root + f'/knowledge-cards/{card.pk}').data['index_status'] == 'failed'
    assert ctx.client.get(ctx.root + '/knowledge-cards/recommend', {'query': '受众'}).data['results'] == []
    assert ctx.client.post(ctx.root + f'/knowledge-cards/{card.pk}/retry-index').status_code == 200
    index(card)
    assert ctx.client.get(ctx.root + '/knowledge-cards/recommend', {'query': '受众'}).data['results']


def test_evidence_validation_and_no_title_only(ctx):
    source = source_task(ctx)
    evidence = k.extraction_evidence(source)
    row = {'title': '知识', 'text': '正文', 'category': 'content', 'basis': 'author_view', 'refs': ['fake']}
    with pytest.raises(ValueError):
        k.validate_candidates({'cards': [row]}, evidence)
    source.output = {'claims': [], 'frames': [{'id': 'f1', 'time': 0}], 'visual_status': 'failed'}
    source.save(update_fields=['output'])
    with pytest.raises(ValidationError):
        k.extraction_evidence(source)
    assert start(ctx, {'kind': 'knowledge_extract', 'source_task_id': str(source.pk)}).status_code == 400


def test_joint_uses_namespaced_original_evidence(ctx):
    first = source_task(ctx)
    first.kind = 'breakdown'
    first.save(update_fields=['kind'])
    # Give the second task an ordinary completed Run through the real service.
    from ..services import start as start_account
    second = start_account(ctx.account, {'kind': 'breakdown', 'work_id': str(first.work_id)}, 'second-start')
    second.output = {'segments': [{'id': 's1', 'text': '另一个案例', 'start': 2, 'end': 4}]}
    second.save(update_fields=['output'])
    finish(second)
    joint = m.Task.objects.create(**scope_for(ctx.app, ctx.owner), kind='joint', request_key='joint', request_hash='x',
                                 output={'evidence': [{'task_id': str(first.pk)}, {'task_id': str(second.pk)}]})
    evidence = k.extraction_evidence(joint)
    assert {row['ref'] for row in evidence} == {f'{first.pk}:s1', f'{second.pk}:s1'}


def test_scope_filters_cover_organization_application_and_owner(ctx, monkeypatch):
    _, _, card, _ = save_card(ctx, monkeypatch)
    index(card)
    for key, value in [('organization_id', uuid.uuid4()), ('application_id', ctx.app.pk + 1), ('owner_id', ctx.reader.pk)]:
        scope = {**scope_for(ctx.app, ctx.owner), key: value}
        assert k.recommend(scope, '受众') == []
        with pytest.raises(Http404):
            k.freeze_selection(scope, [{'id': card.pk, 'revision': 1}])
        with pytest.raises(ValidationError):
            k.check_inherited(scope, [k.snapshot(card)])


def test_selected_evidence_reaches_all_creation_prompts(ctx, monkeypatch):
    _, _, card, _ = save_card(ctx, monkeypatch)
    captured = {}

    def model(task, prompt, data, *args, **kwargs):
        captured[task.kind] = (prompt, data)
        if task.kind == 'topics':
            return {'topics': [{'title': f'选题{i}', 'angle': '新角度', 'hook': '开头'} for i in range(3)]}
        if task.kind == 'script':
            return script()
        return {'title': '文章', 'body': '参考作者观点组织的文章', 'notes': []}

    monkeypatch.setattr('app_center.douyin_benchmark.backend.analysis.call_model', model)
    topics_response = start(ctx, {'kind': 'topics', 'positioning': '科普', 'theme': '受众研究',
                                 'knowledge_cards': [{'id': str(card.pk), 'revision': 1}]}, 'create-topics')
    topics = m.Task.objects.get(pk=topics_response.data['id'])
    execute(*claim(topics)); finish(topics)
    for kind in ['script', 'article']:
        response = start(ctx, {'kind': kind, 'source_task_id': str(topics.pk)}, f'create-{kind}')
        assert response.status_code == 201, response.data
        task = m.Task.objects.get(pk=response.data['id'])
        execute(*claim(task))
        task.refresh_from_db()
        assert task.versions.exists()
    for prompt, data in captured.values():
        assert '不是用户亲身经历' in prompt
        assert data['reference']['knowledge'][0]['id'] == str(card.pk)
        assert 'knowledge' not in data['brief']


def test_visual_evidence_cannot_substitute_for_author_quotes(ctx):
    source = source_task(ctx)
    source.kind = 'breakdown'
    source.output = {'visual_status': 'completed', 'frames': [{'id': 'f1', 'time': 1}],
                     'claims': [{'type': 'observation', 'text': '开头使用大字字幕', 'refs': ['f1']}]}
    evidence = k.extraction_evidence(source)
    row = {'title': '大字字幕', 'text': '用字幕呈现重点', 'category': 'method', 'basis': 'observation', 'refs': [evidence[0]['ref']]}
    assert k.validate_candidates({'cards': [row]}, evidence)['cards'][0]['basis'] == 'observation'
    with pytest.raises(ValueError):
        k.validate_candidates({'cards': [{**row, 'category': 'content', 'basis': 'author_view'}]}, evidence)
    source.output['visual_status'] = 'failed'
    with pytest.raises(ValidationError):
        k.extraction_evidence(source)


def test_cross_account_creation_and_history_survive_source_and_target_deletion(ctx, monkeypatch):
    from .test_research import other_account
    from .test_owned import setup_profile, confirm
    _, extraction, card, payload = save_card(ctx, monkeypatch)
    assert ctx.client.get(ctx.root + f'/tasks/{extraction.pk}').data['output']['saved_candidate_ids'] == ['card-1']
    target = other_account(ctx)
    profile = setup_profile(ctx, target)
    voice = confirm(ctx, profile)
    response = start(ctx, {'kind': 'topics', 'target_account_id': str(target.pk),
                          'knowledge_cards': [{'id': str(card.pk), 'revision': 1}]}, 'cross-account')
    assert response.status_code == 201, response.data
    task = m.Task.objects.get(pk=response.data['id'])
    assert task.input['brief']['target_account_id'] == str(target.pk)
    assert task.input['brief']['voice_version_id'] == voice['id']
    assert task.input['brief']['shared_materials'] == []
    frozen = task.input['reference']['knowledge']
    assert frozen[0]['evidence'][0]['account_id'] == str(ctx.account.pk)
    finish(task)
    assert ctx.client.delete(ctx.url).status_code == 204
    assert ctx.client.get(ctx.root + f'/tasks/{task.pk}').data['output']['knowledge_cards'] == frozen
    assert ctx.client.delete(ctx.root + f'/accounts/{target.pk}').status_code == 204
    assert ctx.client.get(ctx.root + f'/tasks/{task.pk}').data['output']['knowledge_cards'] == frozen
