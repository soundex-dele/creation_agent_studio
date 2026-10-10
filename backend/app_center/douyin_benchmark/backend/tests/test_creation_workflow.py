import pytest
from .. import models as m
from ...runtime import execute
from .test_douyin import ctx, claim, add_work, script  # noqa: F401
from .test_owned import setup_profile, confirm, content
from .test_research import start, finish, other_account
from .test_article import article_content


@pytest.mark.parametrize('kind', ['article', 'script'])
def test_saved_idea_writes_directly_and_freezes_voice_and_notes(ctx, monkeypatch, kind):
    profile = setup_profile(ctx)
    voice = confirm(ctx, profile)
    idea = ctx.client.post(ctx.root + '/ideas', {'title': '确定的选题', 'notes': '真实资料与角度'}, format='json').data
    body = {'kind': kind, 'idea_id': idea['id'], 'target_account_id': str(ctx.account.pk)}
    result = start(ctx, body, 'direct')
    assert result.status_code == 201, result.data
    task = m.Task.objects.get(pk=result.data['id'])
    assert start(ctx, body, 'direct').data['id'] == result.data['id']
    assert start(ctx, {**body, 'theme': '变化'}, 'direct').status_code == 409
    assert task.input['topic']['title'] == '确定的选题'
    assert task.input['brief']['theme'] == '确定的选题'
    assert task.input['brief']['voice_version_id'] == voice['id']
    confirm(ctx, profile, content('修改后的文风'))
    m.Idea.objects.filter(pk=idea['id']).update(title='后续修改', notes='后续笔记')
    task.refresh_from_db()
    assert task.input['reference']['idea']['notes'] == '真实资料与角度'
    assert task.input['brief']['voice_version_id'] == voice['id']
    monkeypatch.setattr('app_center.douyin_benchmark.backend.analysis.call_model', lambda *a, **kw: article_content() if kind == 'article' else script())
    execute(*claim(task))
    assert task.versions.count() == 1
    assert not m.Task.objects.filter(kind='topics').exists()


def test_saved_idea_requires_private_source_and_matching_confirmed_profile(ctx):
    profile = setup_profile(ctx)
    idea = ctx.client.post(ctx.root + '/ideas', {'title': '确定的选题'}, format='json').data
    body = {'kind': 'article', 'idea_id': idea['id'], 'target_account_id': str(ctx.account.pk)}
    assert start(ctx, body, 'unconfirmed').status_code == 400
    confirm(ctx, profile)
    foreign = m.Idea.objects.create(organization=ctx.org, application=ctx.app, owner=ctx.reader, title='他人的私有选题')
    assert start(ctx, {**body, 'idea_id': str(foreign.pk)}, 'foreign').status_code == 404
    assert start(ctx, {**body, 'source_task_id': str(ctx.task.pk)}, 'ambiguous').status_code == 400
    assert start(ctx, {**body, 'target_account_id': str(other_account(ctx).pk)}, 'wrong').status_code == 404


def saved_article(ctx):
    profile = setup_profile(ctx)
    confirm(ctx, profile)
    idea = ctx.client.post(ctx.root + '/ideas', {'title': '选题'}, format='json').data
    response = start(ctx, {'kind': 'article', 'idea_id': idea['id'], 'target_account_id': str(ctx.account.pk)}, 'article')
    task = m.Task.objects.get(pk=response.data['id'])
    finish(task)
    return task, m.ScriptVersion.objects.create(task=task, revision=1, content=article_content())


def test_article_expression_apply_preserves_body_notes_cover_and_history(ctx):
    article, original = saved_article(ctx)
    response = start(ctx, {'kind': 'variants', 'source_version_id': str(original.pk)}, 'variants')
    assert response.status_code == 201, response.data
    task = m.Task.objects.get(pk=response.data['id'])
    finish(task)
    assert task.input['content'] == original.content
    applied = ctx.client.post(f'{ctx.root}/tasks/{task.pk}/apply', {'revision': 1, 'title': '新的标题', 'cover': '封面短句', 'hook': '新的开头'}, format='json')
    assert applied.status_code == 201, applied.data
    value = applied.data['content']
    assert value['body'] == '新的开头\n\n' + original.content['body']
    assert value['title'] == '新的标题' and value['cover'] == '封面短句'
    assert value['notes'] == original.content['notes']
    original.refresh_from_db()
    assert original.content == article_content() and article.versions.count() == 2
    assert ctx.client.post(f'{ctx.root}/tasks/{task.pk}/apply', {'revision': 1, 'title': '冲突'}, format='json').status_code == 409
    ctx.client.force_authenticate(ctx.reader)
    assert ctx.client.post(f'{ctx.root}/tasks/{task.pk}/apply', {'revision': 2, 'title': '越权'}, format='json').status_code == 404


def test_article_publication_and_review_are_scoped_to_creator(ctx):
    article, version = saved_article(ctx)
    work = add_work(ctx, likes=11)
    own = ctx.client.post(ctx.root + '/publications', {'work': str(work.pk), 'script_version': str(version.pk), 'theme': '当前账号'}, format='json')
    assert own.status_code == 201, own.data
    other = other_account(ctx)
    other.is_owned = True
    other.save()
    other_work = m.Work.objects.create(account=other, platform_id='other', metadata={**work.metadata, 'likes': 999})
    assert ctx.client.post(ctx.root + '/publications', {'work': str(other_work.pk), 'script_version': str(version.pk)}, format='json').status_code == 400
    second = ctx.client.post(ctx.root + '/publications', {'work': str(other_work.pk), 'theme': '另一个账号'}, format='json')
    assert second.status_code == 201
    assert ctx.client.get(ctx.root + '/publications', {'account': str(ctx.account.pk)}).data['count'] == 1
    assert ctx.client.get(ctx.root + '/publications').data['count'] == 2
    summary = ctx.client.get(ctx.root + '/publications/summary', {'account': str(ctx.account.pk)}).data
    assert len(summary['by_theme']) == 1 and summary['by_theme'][0]['label'] == '当前账号'
    review = start(ctx, {'kind': 'review', 'target_account_id': str(ctx.account.pk)}, 'review')
    assert review.status_code == 201
    data = m.Task.objects.get(pk=review.data['id']).input
    assert [row['theme'] for row in data['publications']] == ['当前账号']
    # Editing an existing association cannot bypass account validation.
    assert ctx.client.patch(ctx.root + '/publications/' + own.data['id'], {'revision': 1, 'work': str(other_work.pk)}, format='json').status_code == 400


def test_independent_profiles_filter_does_not_include_account_profiles(ctx):
    setup_profile(ctx)
    ctx.client.post(ctx.root + '/creator-profiles', {'name': '独立档案'}, format='json')
    rows = ctx.client.get(ctx.root + '/creator-profiles', {'unbound': 'true'}).data
    assert rows['count'] == 1 and rows['results'][0]['account'] is None


@pytest.mark.parametrize('kind', ['article', 'script'])
def test_direct_creation_only_freezes_explicit_knowledge_revisions(ctx, monkeypatch, kind):
    from .test_knowledge import save_card
    _, _, card, _ = save_card(ctx, monkeypatch)
    profile = setup_profile(ctx)
    confirm(ctx, profile)
    idea = ctx.client.post(ctx.root + '/ideas', {'title': '直接写作'}, format='json').data
    body = {'kind': kind, 'idea_id': idea['id'], 'target_account_id': str(ctx.account.pk)}
    first = start(ctx, body, 'without-cards')
    assert first.status_code == 201, first.data
    assert 'knowledge' not in m.Task.objects.get(pk=first.data['id']).input['reference']
    selected = start(ctx, {**body, 'knowledge_cards': [{'id': str(card.pk), 'revision': card.revision}]}, 'with-cards')
    assert selected.status_code == 201, selected.data
    task = m.Task.objects.get(pk=selected.data['id'])
    assert task.input['reference']['knowledge'][0]['text'] == card.text
    m.CreationKnowledgeCard.objects.filter(pk=card.pk).update(text='后来编辑的知识', revision=2)
    task.refresh_from_db()
    assert task.input['reference']['knowledge'][0]['text'] == card.text
    assert start(ctx, {**body, 'knowledge_cards': [{'id': str(card.pk), 'revision': 1}]}, 'stale').status_code == 409
