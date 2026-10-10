import copy
import io
import json
import stat
import subprocess
import zipfile
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from rest_framework.test import APIClient
from apps.applications.models import Application
from apps.enterprise.models import Membership
from ..models import Project, Task, Snapshot, Content, Handoff
from ..sources import from_zip, from_local, github_source
from ..content import animation, validate_document
from ... import runtime


class Sink:
    cancelled = False
    def emit(self, *_):
        pass


@pytest.fixture(autouse=True)
def writing_skills(settings, tmp_path):
    settings.CODEX_SKILLS_DIRECTORY = str(tmp_path / 'skills')
    for slug in ('write-short-video-copy', 'write-image-text-copy'):
        path = tmp_path / 'skills' / slug / 'SKILL.md'
        path.parent.mkdir(parents=True)
        path.write_text(f'# {slug}\nUse grounded facts and natural language.', encoding='utf-8')


def archive(files=None):
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as z:
        for path, value in (files or {'README.md': '# Tool\nPDF question answering', 'app.py': 'def answer(query):\n    return search(query)\n'}).items():
            z.writestr(path, value)
    return data.getvalue()


@pytest.fixture
def ctx(db, settings, tmp_path):
    settings.ROOT_URLCONF = 'app_center.repo_explainer.backend.tests.urls'
    settings.ARTIFACT_ROOT = tmp_path / 'artifacts'
    settings.ARTIFACT_STORAGE_BACKEND = 'local'
    settings.AGENT_WORKSPACE_ROOT = tmp_path / 'workspaces'
    owner = get_user_model().objects.create_user(username='repo-owner')
    other = get_user_model().objects.create_user(username='repo-other')
    org = owner.owned_organizations.get()
    Membership.objects.create(organization=org, user=other, role=Membership.Role.ADMIN)
    call_command('sync_app_center', package_id='repo-explainer', organization_id=str(org.id))
    app = Application.objects.get(organization=org, slug='repo-explainer')
    app.visibility = 'organization'; app.save()
    client = APIClient(); client.force_authenticate(owner)
    url = f'/api/v1/organizations/{org.id}/applications/{app.id}/repo-explainer'
    response = client.post(url + '/projects', {'title': '工具介绍'}, format='json')
    assert response.status_code == 201, response.data
    project = Project.objects.get(pk=response.data['id'])
    return SimpleNamespace(owner=owner, other=other, org=org, app=app, project=project, client=client,
                           url=url, root=url + f'/projects/{project.id}')


def upload(ctx, key='import'):
    response = ctx.client.post(ctx.root + '/imports', {'kind': 'zip', 'file': SimpleUploadedFile('repo.zip', archive())}, HTTP_IDEMPOTENCY_KEY=key)
    assert response.status_code in (200, 202), response.data
    return Task.objects.get(pk=response.data['id'])


def finish(task, sink=None):
    output = runtime.execute({'run_id': str(task.run_id), 'organization_id': str(task.project.organization_id), 'input': task.run.input}, sink or Sink())
    task.run.status = 'succeeded'; task.run.output_summary = output; task.run.save()
    task.refresh_from_db()
    return output


def report():
    return {'summary': 'PDF 问答工具', 'audience': '研究人员', 'workflow': ['导入后提问'], 'deployment': ['配置模型'], 'limitations': ['尚未运行验证'],
            'features': [{'title': '文档问答', 'description': '围绕文档提问', 'scenario': '资料研究', 'entry': 'answer()',
                'requirements': '模型配置', 'limitations': '静态分析', 'discrepancies': '', 'status': 'implemented', 'evidence_ids': ['e2']}]}


def document():
    return {'schema_version': 2, 'kind': 'video', 'title': '用 AI 阅读资料', 'cover': '文档变问答',
        'aspect': '16:9', 'duration': 60, 'alternatives': [], 'notes': [], 'publish_copy': '支持文档问答',
        'paragraphs': [{'heading': '', 'text': '导入文档后可以提问。', 'feature_ids': ['f1'], 'evidence_ids': ['e2']}]}


def legacy_document():
    refs = {'feature_ids': ['f1'], 'evidence_ids': ['e2']}
    return {'title': '用 AI 阅读资料', 'cover': '文档变问答', 'aspect': '16:9', 'checklist': ['补充真实截图'],
            'scenes': [{**refs, 'narration': '导入文档后可以提问。', 'visual': '示意流程图', 'seconds': 60}],
            'article': {'title': '工具介绍', 'intro': '适合资料研究', 'sections': [{**refs, 'heading': '功能', 'body': '支持文档问答', 'image': '真实截图待补充'}]}}


def model(**kwargs):
    instruction = kwargs['instruction']
    if 'queries' in instruction:
        return {'queries': ['answer', 'app.py']}
    if '"paragraphs"' in instruction:
        result = document()
        if 'write-image-text-copy' in instruction:
            result['kind'] = 'image_text'
        return result
    return report()


def create_content(ctx, monkeypatch):
    monkeypatch.setattr(runtime, 'generate_json', model)
    imported = upload(ctx); finish(imported)
    response = ctx.client.post(ctx.root + '/tasks', {'kind': 'analyze', 'snapshot_id': str(imported.snapshot_id)}, format='json', HTTP_IDEMPOTENCY_KEY='analysis')
    assert response.status_code == 202, response.data
    analysis = Task.objects.get(pk=response.data['id']); finish(analysis)
    response = ctx.client.post(ctx.root + '/tasks', {'kind': 'write', 'analysis_id': str(analysis.id), 'feature_ids': ['f1']}, format='json', HTTP_IDEMPOTENCY_KEY='write')
    assert response.status_code == 202, response.data
    task = Task.objects.get(pk=response.data['id']); output = finish(task)
    return Content.objects.get(pk=output['content_id'])


def target(ctx, slug):
    return Application.objects.create(organization=ctx.org, category=ctx.app.category, slug=slug, name=slug,
        kind='custom' if slug == 'animation-studio' else 'chat', created_by=ctx.owner, visibility='organization')


def test_import_snapshot_and_idempotency(ctx):
    task = upload(ctx); same = upload(ctx)
    assert task.id == same.id
    finish(task)
    task.snapshot.refresh_from_db()
    assert task.snapshot.status == 'ready'
    assert task.snapshot.files['app.py']['text'].startswith('def answer')
    assert len(task.snapshot.digest) == 64
    response = ctx.client.get(ctx.root + f'/snapshots/{task.snapshot_id}/evidence', {'path': 'app.py'})
    assert response.status_code == 200
    assert 'search(query)' in response.data['text']


def test_model_progress_reports_activity_without_raw_output(ctx, monkeypatch):
    task = upload(ctx); finish(task)
    response = ctx.client.post(ctx.root + '/tasks', {'kind': 'analyze', 'snapshot_id': str(task.snapshot_id)},
        format='json', HTTP_IDEMPOTENCY_KEY='progress-analysis')
    analysis = Task.objects.get(pk=response.data['id'])
    events = []
    sink = Sink()
    sink.emit = lambda kind, payload: events.append((kind, payload))
    monkeypatch.setattr(runtime.time, 'monotonic', lambda: 10)

    def streaming_model(**kwargs):
        callback = kwargs['on_event']
        callback('agent.reasoning', {'text': 'private reasoning'})
        callback('tool.started', {'text': 'private tool arguments'})
        callback('output.delta', {'text': 'test'})
        callback('output.delta', {'text': 'more'})
        return model(**kwargs)

    monkeypatch.setattr(runtime, 'generate_json', streaming_model)
    finish(analysis, sink)
    waiting = [p for _, p in events if p.get('activity') == 'waiting_model']
    responding = [p for _, p in events if p.get('activity') == 'responding']
    assert waiting and len(waiting) == len(responding)
    assert all(p['characters'] == 4 for p in responding)  # throttles subsequent deltas
    assert all(kind == 'progress.updated' for kind, _ in events)
    assert all(set(p) <= {'stage', 'activity', 'characters'} for _, p in events)
    assert events[-1][1]['stage'] == '校验生成结果与来源引用'


def test_task_progress_has_consistent_event_boundary(ctx):
    from modules.execution.models import RunEvent
    from ..views import task_data
    task = upload(ctx)
    sequence = task.run.next_event_sequence + 1
    RunEvent.objects.create(run=task.run, organization=ctx.org, sequence=sequence,
        type='progress.updated', payload={'stage': '读取源码'})
    task.run.status = 'running'; task.run.next_event_sequence = sequence
    task.run.save(update_fields=['status', 'next_event_sequence'])
    # An event committed after the loaded Run must not leak into that response.
    RunEvent.objects.create(run=task.run, organization=ctx.org, sequence=sequence + 1,
        type='progress.updated', payload={'stage': '保存快照'})
    data = task_data(task)
    assert data['run_id'] == str(task.run_id)
    assert data['status'] == 'running'
    assert data['event_sequence'] == sequence
    assert data['progress'] == {'stage': '读取源码'}


def test_private_projects_and_runs(ctx):
    task = upload(ctx)
    ctx.client.force_authenticate(ctx.other)
    assert ctx.client.get(ctx.root).status_code == 404
    assert ctx.client.get(ctx.url + '/projects').data == []
    from ..access import can_access_run
    assert not can_access_run(ctx.other, task.run)
    ctx.client.force_authenticate(ctx.owner)
    ctx.app.is_active = False; ctx.app.save()
    assert ctx.client.get(ctx.root).status_code == 404
    assert not can_access_run(ctx.owner, task.run)


def test_cancelled_import_not_published(ctx):
    task = upload(ctx)
    sink = Sink(); sink.cancelled = True
    with pytest.raises(InterruptedError):
        finish(task, sink)
    task.snapshot.refresh_from_db()
    assert task.snapshot.status == 'cancelled'
    assert task.snapshot.files == {}


def test_analysis_and_content_versions(ctx, monkeypatch):
    c = create_content(ctx, monkeypatch)
    old_version = c.versions.first()
    edited = copy.deepcopy(c.draft); edited['paragraphs'][0]['text'] = '手工修改的内容。'
    response = ctx.client.put(ctx.root + f'/contents/{c.id}', {'revision': 1, 'document': edited}, format='json')
    assert response.status_code == 200, response.data
    assert response.data['revision'] == 2
    assert response.data['draft']['paragraphs'][0]['needs_review']
    old_version.refresh_from_db()
    assert old_version.document['paragraphs'][0]['text'] == '导入文档后可以提问。'
    conflict = ctx.client.put(ctx.root + f'/contents/{c.id}', {'revision': 1, 'document': c.draft}, format='json')
    assert conflict.status_code == 409
    assert conflict.data['current']['revision'] == 2
    assert ctx.client.get(ctx.root + f'/contents/{c.id}/download').status_code == 200


@pytest.mark.parametrize('slug', ['animation-studio', 'copy-to-jianying'])
def test_handoff_fixed_version_permissions_and_duplicate(ctx, monkeypatch, slug):
    c = create_content(ctx, monkeypatch); dest = target(ctx, slug)
    body = {'version_id': str(c.versions.first().id), 'target_id': dest.id}
    response = ctx.client.post(ctx.root + '/handoffs', body, format='json', HTTP_IDEMPOTENCY_KEY='handoff')
    assert response.status_code == 201, response.data
    again = ctx.client.post(ctx.root + '/handoffs', body, format='json', HTTP_IDEMPOTENCY_KEY='handoff')
    assert again.data['id'] == response.data['id']
    assert Handoff.objects.count() == 1
    if slug == 'animation-studio':
        from app_center.animation_studio.backend.models import AnimationProject
        work = AnimationProject.objects.get(pk=response.data['target_id'])
        assert work.draft['scenes'] == []
        assert '导入文档后可以提问。' in work.draft['prompt']
    else:
        url = ctx.url + '/handoffs/' + response.data['id']
        assert ctx.client.get(url).data['draft']['source'] == '导入文档后可以提问。'
        saved = ctx.client.patch(url, {'revision': 1, 'draft': {'source': '目标制作页修改'}}, format='json')
        assert saved.status_code == 200
        assert ctx.client.get(url).data['draft']['source'] == '目标制作页修改'
        assert ctx.client.patch(url, {'revision': 1, 'draft': {}}, format='json').status_code == 409
        c.refresh_from_db(); assert c.draft['paragraphs'][0]['text'] == '导入文档后可以提问。'
    ctx.client.force_authenticate(ctx.other)
    assert ctx.client.get(ctx.url + '/handoffs/' + response.data['id']).status_code == 404
    ctx.client.force_authenticate(ctx.owner)
    dest.is_active = False; dest.save()
    assert ctx.client.get(ctx.url + '/handoffs/' + response.data['id']).status_code == 404


def test_analysis_rejects_fabricated_evidence(ctx, monkeypatch):
    imported = upload(ctx); finish(imported)
    response = ctx.client.post(ctx.root + '/tasks', {'kind': 'analyze', 'snapshot_id': str(imported.snapshot_id)}, format='json', HTTP_IDEMPOTENCY_KEY='analysis')
    task = Task.objects.get(pk=response.data['id'])
    def bad(**kwargs):
        if 'queries' in kwargs['instruction']:
            return {'queries': []}
        data = report(); data['features'][0]['evidence_ids'] = ['invented']; return data
    monkeypatch.setattr(runtime, 'generate_json', bad)
    with pytest.raises(ValueError, match='校验失败'):
        finish(task)
    task.refresh_from_db()
    assert 'diagnostic' in task.output


@pytest.mark.parametrize('path', ['../secret', '/absolute', 'C:/secret', 'a/../../secret', 'a\\..\\secret'])
def test_zip_traversal_rejected(path):
    with pytest.raises(ValueError, match='路径'):
        from_zip(archive({path: 'bad'}), lambda: None)


def test_zip_symlink_rejected():
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as z:
        info = zipfile.ZipInfo('link'); info.create_system = 3; info.external_attr = (stat.S_IFLNK | 0o777) << 16
        z.writestr(info, '../secret')
    with pytest.raises(ValueError, match='链接'):
        from_zip(data.getvalue(), lambda: None)


def test_zip_limits_and_exclusions(settings):
    files, coverage = from_zip(archive({'README.md': 'hello', '.env': 'password', '.netrc': 'credential', 'node_modules/a.js': 'dep', 'image.png': b'\x00'}), lambda: None)
    assert list(files) == ['README.md']
    assert len(coverage['excluded']) == 4
    settings.REPO_EXPLAINER_EXPANDED_BYTES = 4
    with pytest.raises(ValueError, match='解压'):
        from_zip(archive(), lambda: None)


def test_local_uncommitted_snapshot_and_ignore(ctx, settings, tmp_path):
    from core.user_directories import user_directory
    root = user_directory(ctx.owner) / 'test-repo'; root.mkdir(parents=True)
    def git(*args):
        subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True)
    git('init'); git('config', 'user.name', 'Test'); git('config', 'user.email', 'test@example.com')
    (root / '.gitignore').write_text('ignored.txt\n')
    (root / 'app.py').write_text('original')
    git('add', '.'); git('commit', '-m', 'initial')
    (root / 'app.py').write_text('modified'); (root / 'new.py').write_text('new')
    (root / 'ignored.txt').write_text('ignored')
    files, _, origin = from_local(str(root), ctx.owner, lambda: None)
    assert files['app.py']['text'] == 'modified'
    assert 'new.py' in files and 'ignored.txt' not in files
    assert origin['working_tree'] and len(origin['commit']) == 40
    with pytest.raises(PermissionError):
        from_local(str(tmp_path), ctx.other, lambda: None)


def test_conversation_attachment_checks_target_and_owner(ctx, monkeypatch):
    from apps.applications.models import ChatApplication
    from apps.conversations.models import Conversation
    c = create_content(ctx, monkeypatch)
    dest = target(ctx, 'copy-to-jianying')
    chat = ChatApplication.objects.create(application=dest)
    result = ctx.client.post(ctx.root + '/handoffs', {'version_id': str(c.versions.first().id), 'target_id': dest.id}, format='json', HTTP_IDEMPOTENCY_KEY='handoff')
    assert result.status_code == 201, result.data
    url = ctx.url + '/handoffs/' + result.data['id']
    wrong = Conversation.objects.create(user=ctx.other, organization=ctx.org, chat_application=chat)
    assert ctx.client.patch(url, {'revision': 1, 'conversation_id': wrong.id}, format='json').status_code == 404
    own = Conversation.objects.create(user=ctx.owner, organization=ctx.org, chat_application=chat)
    response = ctx.client.patch(url, {'revision': 1, 'conversation_id': own.id}, format='json')
    assert response.status_code == 200, response.data
    assert response.data['target_id'] == str(own.id)
    assert response.data['status'] == '会话已关联'


def test_snapshot_unavailable_until_import_run_succeeds(ctx):
    task = upload(ctx); finish(task)
    task.run.status = 'cancelled'; task.run.save()
    response = ctx.client.post(ctx.root + '/tasks', {'kind': 'analyze', 'snapshot_id': str(task.snapshot_id)}, format='json', HTTP_IDEMPOTENCY_KEY='cancelled-analysis')
    assert response.status_code == 400
    assert ctx.client.get(ctx.root + f'/snapshots/{task.snapshot_id}/evidence', {'path': 'app.py'}).status_code == 400


def test_report_cannot_promote_documentation_to_implementation():
    data = report()
    with pytest.raises(ValueError, match='仅凭文档'):
        runtime.validate_report(data, {'e2': {'path': 'README.md'}})
    data['features'][0]['status'] = 'unconfirmed'
    data['features'][0]['evidence_ids'] = []
    assert runtime.validate_report(data, {})['features'][0]['status'] == 'unconfirmed'


def test_cross_organization_target_rejected(ctx, monkeypatch):
    c = create_content(ctx, monkeypatch)
    dest = Application.objects.create(organization=ctx.other.owned_organizations.get(), category=ctx.app.category,
        slug='animation-studio', name='other', kind='custom', created_by=ctx.other, visibility='organization')
    response = ctx.client.post(ctx.root + '/handoffs', {'version_id': str(c.versions.first().id), 'target_id': dest.id}, format='json', HTTP_IDEMPOTENCY_KEY='foreign')
    assert response.status_code == 404


def test_local_detects_mid_copy_change(ctx, monkeypatch):
    from core.user_directories import user_directory
    from .. import sources
    root = user_directory(ctx.owner) / 'changing'; root.mkdir()
    for args in [('init',), ('config', 'user.name', 'Test'), ('config', 'user.email', 'test@example.com')]:
        subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True)
    (root / 'app.py').write_text('before')
    subprocess.run(['git', '-C', str(root), 'add', '.'], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(root), 'commit', '-m', 'initial'], check=True, capture_output=True)
    original = sources.collect
    def collect(*args):
        value = original(*args)
        (root / 'app.py').write_text('changed during copy')
        return value
    monkeypatch.setattr(sources, 'collect', collect)
    with pytest.raises(ValueError, match='复制期间'):
        sources.from_local(str(root), ctx.owner, lambda: None)


def test_animation_limits():
    doc = document(); doc['duration'] = 121
    with pytest.raises(ValueError, match='120'):
        animation(doc)
    doc['duration'] = 60; doc['paragraphs'][0]['text'] = 'a' * 16000
    with pytest.raises(ValueError, match='16000'):
        animation(doc)


def test_legacy_copy_remains_readable_and_imports_as_text():
    from ..content import markdown, jianying
    doc = legacy_document()
    report_data = {**report(), 'features': [{'id': 'f1'}], 'evidence': {'e2': {}}}
    validated = validate_document(doc, report_data)
    assert '导入文档后可以提问。' in markdown(validated)
    assert jianying(validated)['source'] == '导入文档后可以提问。'
    assert animation(validated)['scenes'] == []


@pytest.mark.parametrize('kind,slug', [('video', 'write-short-video-copy'), ('image_text', 'write-image-text-copy')])
def test_writing_uses_installed_skill_and_only_video_has_handoffs(ctx, monkeypatch, kind, slug):
    from ..content import markdown
    original = create_content(ctx, monkeypatch)
    calls = []
    def capture(**kwargs):
        calls.append(kwargs)
        return model(**kwargs)
    monkeypatch.setattr(runtime, 'generate_json', capture)
    response = ctx.client.post(ctx.root + '/tasks', {'kind': 'write', 'output': kind,
        'analysis_id': str(original.analysis_id), 'feature_ids': ['f1']}, format='json', HTTP_IDEMPOTENCY_KEY='copy-' + kind)
    assert response.status_code == 202, response.data
    task = Task.objects.get(pk=response.data['id']); finish(task)
    content = Content.objects.get(generation=task)
    assert content.draft['kind'] == kind
    assert content.draft['skill']['slug'] == slug
    assert len(content.draft['skill']['sha256']) == 64
    assert '# ' + slug in calls[0]['instruction']  # actual Skill file, not just a name
    assert 'Use grounded facts and natural language.' in calls[0]['instruction']
    assert 'scenes' not in content.draft and 'article' not in content.draft
    assert '导入文档后可以提问。' in markdown(content.draft)
    for target_slug in ('animation-studio', 'copy-to-jianying'):
        app = target(ctx, target_slug)
        response = ctx.client.post(ctx.root + '/handoffs', {'version_id': str(content.versions.first().id), 'target_id': app.id},
            format='json', HTTP_IDEMPOTENCY_KEY=kind + target_slug)
        assert response.status_code == (201 if kind == 'video' else 400), response.data
    if kind == 'image_text':
        assert Handoff.objects.count() == 0
    edited = copy.deepcopy(content.draft); edited['skill'] = {'slug': 'forged', 'sha256': 'x'}
    response = ctx.client.put(ctx.root + f'/contents/{content.id}', {'revision': content.revision, 'document': edited}, format='json')
    assert response.status_code == 200
    assert response.data['draft']['skill'] == content.draft['skill']


def test_missing_skill_fails_explicitly(settings, tmp_path):
    from ..copywriting import load_copy_skill
    settings.CODEX_SKILLS_DIRECTORY = str(tmp_path / 'missing-skills')
    with pytest.raises(ValueError, match='write-short-video-copy'):
        load_copy_skill('video')


def test_copy_schema_rejects_scenes_and_forged_references():
    report_data = {**report(), 'features': [{'id': 'f1'}], 'evidence': {'e2': {}}}
    doc = document(); doc['scenes'] = []
    with pytest.raises(ValueError, match='分镜'):
        validate_document(doc, report_data)
    doc = document(); doc['paragraphs'][0]['evidence_ids'] = ['fake']
    with pytest.raises(ValueError, match='不存在'):
        validate_document(doc, report_data)


def test_github_fixed_sha_and_no_redirects(monkeypatch):
    urls = []
    sha = 'a' * 40
    class Response:
        status_code = 200
        def __init__(self, raw): self.raw = raw
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def iter_content(self, _): yield self.raw
    class Session:
        trust_env = True
        def get(self, url, **options):
            assert options['allow_redirects'] is False
            assert self.trust_env is False
            urls.append(url)
            if 'codeload' in url: return Response(archive({'root/README.md': 'tool'}))
            return Response(json.dumps({'sha': sha} if '/commits/' in url else {'default_branch': 'main'}).encode())
        def close(self): pass
    monkeypatch.setattr('app_center.repo_explainer.backend.sources.requests.Session', Session)
    files, _, origin = github_source('https://github.com/example/tool', '', lambda: None)
    assert origin['commit'] == sha
    assert urls[-1].endswith('/zip/' + sha)
    assert 'README.md' in files
    with pytest.raises(ValueError):
        github_source('http://127.0.0.1/repo', '', lambda: None)
