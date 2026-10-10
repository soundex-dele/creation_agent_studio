import json
from unittest.mock import Mock

import pytest
from django.utils import timezone
from modules.execution.models import RunLease
from apps.enterprise.models import Membership
from rest_framework.exceptions import PermissionDenied

from .. import models as m
from ..article import has_style, validate_review
from ..voice_style import make_prompt
from ...runtime import execute
from .test_douyin import ctx, claim  # noqa: F401
from .test_article import topics_for, article_content
from .test_research import start


def create_article(ctx, brief=None):
    _, _, topics = topics_for(ctx)
    if brief is not None:
        topics.input['brief'] = brief
        topics.save()
    response = start(ctx, {'kind': 'article', 'source_task_id': str(topics.pk)}, 'review')
    assert response.status_code == 201
    return m.Task.objects.get(pk=response.data['id'])


def test_two_phase_review_uses_frozen_materials_and_saves_only_final_article(ctx, monkeypatch):
    task = create_article(ctx)
    final = {**article_content(), 'body': '按已确认规则修订后的正文。', 'notes': []}
    model = Mock(side_effect=[article_content(), {'article': final, 'summary': '按样本开头习惯，删除额外的总结。'}])
    monkeypatch.setattr('app_center.douyin_benchmark.backend.analysis.generate_json', model)
    payload, sink = claim(task)
    execute(payload, sink)
    assert model.call_count == 2
    first, second = [json.loads(c.kwargs['content']) for c in model.call_args_list]
    assert first['brief'] == second['brief']
    assert first['reference'] == second['reference']
    assert second['draft'] == article_content()
    task.refresh_from_db()
    version = task.versions.get()
    assert version.content == {**final, 'notes': article_content()['notes']}
    assert task.output['style_review'] == dict(status='completed', revision=1, summary='按样本开头习惯，删除额外的总结。')
    assert 'style_review' not in version.content
    # Re-entering after a saved version must reuse the original review, not regenerate.
    execute(payload, sink)
    assert model.call_count == 2 and task.versions.count() == 1


@pytest.mark.parametrize('failure', ['service', 'invalid'])
def test_review_failure_keeps_valid_draft(ctx, monkeypatch, failure):
    task = create_article(ctx)
    outputs = [article_content(), RuntimeError('provider failure')] if failure == 'service' else [article_content(), {}, {}]
    model = Mock(side_effect=outputs)
    monkeypatch.setattr('app_center.douyin_benchmark.backend.analysis.generate_json', model)
    execute(*claim(task))
    task.refresh_from_db()
    assert task.stage == 'completed'
    assert task.output['style_review']['status'] == 'unavailable'
    assert '文风校对未完成' in task.output['style_review']['summary']
    assert task.versions.get().content == article_content()
    assert model.call_count == len(outputs)


def test_review_structure_repair_is_bounded_and_keeps_draft(ctx, monkeypatch):
    task = create_article(ctx)
    model = Mock(side_effect=[article_content(), {}, {'article': article_content(), 'summary': '无需修改。'}])
    monkeypatch.setattr('app_center.douyin_benchmark.backend.analysis.generate_json', model)
    execute(*claim(task))
    assert model.call_count == 3
    assert json.loads(model.call_args.kwargs['content'])['draft'] == article_content()
    task.refresh_from_db()
    assert task.output['style_review']['status'] == 'completed'


@pytest.mark.parametrize('stop', ['cancel', 'lease', 'access'])
@pytest.mark.parametrize('review_error', [False, True])
def test_review_cannot_save_after_cancellation_or_lost_authority(ctx, monkeypatch, stop, review_error):
    task = create_article(ctx)
    payload, sink = claim(task)
    calls = []

    def generate(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return article_content()
        if stop == 'cancel':
            sink.cancelled = True
        elif stop == 'lease':
            RunLease.objects.filter(attempt_id=payload['attempt_id']).update(expires_at=timezone.now())
        else:
            Membership.objects.filter(organization=ctx.org, user=ctx.owner).update(is_active=False)
        if review_error:
            raise RuntimeError('provider failure at the same time')
        return {'article': article_content(), 'summary': '无需修改。'}

    monkeypatch.setattr('app_center.douyin_benchmark.backend.analysis.generate_json', generate)
    with pytest.raises(InterruptedError if stop != 'access' else PermissionDenied):
        execute(payload, sink)
    assert not task.versions.exists()
    task.refresh_from_db()
    assert task.output == {}


@pytest.mark.parametrize('legacy', [False, True])
def test_legacy_and_no_style_briefs(ctx, monkeypatch, legacy):
    brief = {'positioning': '科普', 'theme': '实验', 'profile': {'voice': '先讲具体问题' if legacy else ''}}
    task = create_article(ctx, brief)
    model = Mock(side_effect=[article_content()] + ([{'article': article_content(), 'summary': '按旧档案核对，无需修改。'}] if legacy else []))
    monkeypatch.setattr('app_center.douyin_benchmark.backend.analysis.generate_json', model)
    execute(*claim(task))
    task.refresh_from_db()
    assert model.call_count == (2 if legacy else 1)
    assert task.output['style_review']['status'] == ('completed' if legacy else 'not_applicable')


def test_positioning_only_does_not_count_as_style_but_manual_prompt_does():
    profile = {'positioning': '科普', 'rules': '', 'examples': '', 'avoid': ''}
    profile['prompt'] = make_prompt(profile)
    assert not has_style({'voice_profile': profile})
    profile['prompt'] = '像与朋友聊天一样解释问题'
    assert has_style({'voice_profile': profile})
    assert has_style({'voice_evidence': [{'usage': 'style', 'text': '真实正文'}]})
    assert not has_style({'voice_evidence': [{'usage': 'content', 'text': '内容材料'}]})


def test_review_preserves_cover_and_unresolved_notes():
    draft = {**article_content(), 'cover': '原封面'}
    final, summary = validate_review({'article': {**article_content(), 'notes': ['新待核实项']}, 'summary': '修订说明'}, draft)
    assert final['cover'] == '原封面'
    assert final['notes'] == article_content()['notes'] + ['新待核实项']
    assert summary == '修订说明'
