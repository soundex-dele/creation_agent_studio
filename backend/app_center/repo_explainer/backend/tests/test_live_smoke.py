"""Opt-in acceptance with the configured real model; never runs in ordinary CI."""
import json
import os
from pathlib import Path
import pytest
from .test_repo import ctx, finish, target  # noqa: F401
from ..models import Task, Content


@pytest.mark.skipif(os.environ.get('REPO_EXPLAINER_LIVE_TEST') != '1', reason='需要显式启用真实模型验收')
def test_real_repository_to_production_drafts(ctx, settings, tmp_path):
    settings.APPLICATION_RUNTIME_ALLOW_ALL_PATHS = True
    settings.REPO_EXPLAINER_ROUNDS = 1
    settings.REPO_EXPLAINER_ANALYSIS_CHARS = 8000
    settings.APPLICATION_GENERATION_TIMEOUT_SECONDS = 300
    ctx.owner.is_superuser = True; ctx.owner.save()
    repository = Path(__file__).resolve().parents[3] / 'prompt_master'
    response = ctx.client.post(ctx.root + '/imports', {'kind': 'local', 'path': str(repository)}, format='json', HTTP_IDEMPOTENCY_KEY='live-import')
    assert response.status_code == 202, response.data
    imported = Task.objects.get(pk=response.data['id']); finish(imported)
    response = ctx.client.post(ctx.root + '/tasks', {'kind': 'analyze', 'snapshot_id': str(imported.snapshot_id)}, format='json', HTTP_IDEMPOTENCY_KEY='live-analysis')
    assert response.status_code == 202, response.data
    analysis = Task.objects.get(pk=response.data['id']); report = finish(analysis)
    selected = [f['id'] for f in report['features'][:3]]
    response = ctx.client.post(ctx.root + '/tasks', {'kind': 'write', 'analysis_id': str(analysis.id), 'feature_ids': selected,
        'duration': 60, 'output': 'video'}, format='json', HTTP_IDEMPOTENCY_KEY='live-write')
    assert response.status_code == 202, response.data
    writing = Task.objects.get(pk=response.data['id']); result = finish(writing)
    content = Content.objects.get(pk=result['content_id'])
    assert content.draft['skill']['slug'] == 'write-short-video-copy'
    assert 'scenes' not in content.draft
    for slug in ['copy-to-jianying', 'animation-studio']:
        app = target(ctx, slug)
        response = ctx.client.post(ctx.root + '/handoffs', {'version_id': str(content.versions.first().id), 'target_id': app.id},
            format='json', HTTP_IDEMPOTENCY_KEY='live-' + slug)
        assert response.status_code == 201, response.data
        assert response.data['url'].startswith('/applications/')
        if slug == 'animation-studio':
            assert response.data['draft']['scenes'] == []
    response = ctx.client.post(ctx.root + '/tasks', {'kind': 'write', 'analysis_id': str(analysis.id), 'feature_ids': selected,
        'output': 'image_text'}, format='json', HTTP_IDEMPOTENCY_KEY='live-image-copy')
    assert response.status_code == 202, response.data
    result = finish(Task.objects.get(pk=response.data['id']))
    image_copy = Content.objects.get(pk=result['content_id'])
    assert image_copy.draft['skill']['slug'] == 'write-image-text-copy'
    assert image_copy.draft['kind'] == 'image_text'
    output = tmp_path / 'repo-explainer-live-validation.json'
    output.write_text(json.dumps({'repository': str(repository), 'report': report, 'content': content.draft, 'image_copy': image_copy.draft,
        'checks': 'Real configured model, immutable local snapshot, both production handoff APIs; no browser or video rendering.'}, ensure_ascii=False, indent=2), encoding='utf-8')
    print('LIVE_VALIDATION_ARTIFACT=' + str(output))
