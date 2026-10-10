import json
from unittest.mock import Mock

import pytest

from .. import analysis, models as m
from ...runtime import execute
from .test_douyin import ctx, claim  # noqa: F401
from .test_article import article_content, topics_for
from .test_owned import setup_profile, confirm
from .test_research import start


def creation_task(ctx, route):
    if route == 'article':
        _, _, topics = topics_for(ctx)
        values = {'kind': 'article', 'source_task_id': str(topics.pk)}
    elif route == 'saved_idea':
        confirm(ctx, setup_profile(ctx))
        idea = ctx.client.post(ctx.root + '/ideas', {'title': '已保存的主题'}, format='json').data
        values = {'kind': 'article', 'idea_id': idea['id'], 'target_account_id': str(ctx.account.pk)}
    elif route == 'owned_topics':
        confirm(ctx, setup_profile(ctx))
        values = {'kind': 'topics', 'target_account_id': str(ctx.account.pk)}
    else:
        values = {'kind': 'topics', 'positioning': '读书', 'theme': '表达'}
    response = start(ctx, values, 'skill-creation')
    assert response.status_code == 201, response.data
    return m.Task.objects.get(pk=response.data['id'])


@pytest.mark.parametrize('route', ['topics', 'owned_topics', 'article', 'saved_idea'])
def test_creation_loads_full_skill_into_model_and_keeps_it_on_repair(ctx, skill, monkeypatch, route):
    task = creation_task(ctx, route)
    output = article_content() if task.kind == 'article' else {'topics': [dict(
        title=f'选题{i}', angle='新角度', hook='开头', pillar='表达', reason='符合定位',
        materials_needed='真实案例', duplicate_note='已有样本中未发现重复',
    ) for i in range(3)]}
    model = Mock(side_effect=[{}, output])
    monkeypatch.setattr(analysis, 'generate_json', model)
    execute(*claim(task))
    assert model.call_count == 2
    for call in model.call_args_list:
        instruction = call.kwargs['instruction']
        for text in ['wechat-viral-article', '写作技能正文', '写作资料', '大纲模板',
                     '本次任务的明确要求优先', '不承诺爆款效果']:
            assert text in instruction
        assert instruction.count('--- references/writing.md ---') == 1
        assert instruction.index('大纲模板') < instruction.index('本次任务的明确要求优先')
        if task.kind == 'topics':
            assert '恰好3个新选题' in instruction
        else:
            assert '"body"' in instruction and 'voice_profile.prompt' in instruction
        if route in ['owned_topics', 'article', 'saved_idea']:
            model_data = json.loads(call.kwargs['content'])
            assert model_data['brief']['voice_profile'] == task.input['brief']['voice_profile']
    assert '上次结构或引用校验未通过' in model.call_args.kwargs['instruction']
    task.refresh_from_db()
    assert task.stage == 'completed'
    if task.kind == 'article':
        assert task.versions.get().content == output
    else:
        assert len(task.output['topics']) == 3


@pytest.mark.parametrize('route', ['topics', 'article'])
@pytest.mark.parametrize('missing_file', ['SKILL.md', 'references/writing.md'])
def test_creation_reports_missing_skill_without_calling_model(ctx, skill, monkeypatch, route, missing_file):
    task = creation_task(ctx, route)
    (skill / missing_file).unlink()
    model = Mock()
    monkeypatch.setattr(analysis, 'generate_json', model)
    with pytest.raises(RuntimeError, match='无法加载 wechat-viral-article 技能资料'):
        execute(*claim(task))
    model.assert_not_called()
    task.refresh_from_db()
    assert task.stage == 'failed' and missing_file in task.error
    assert not task.versions.exists()
