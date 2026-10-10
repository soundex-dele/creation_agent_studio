import uuid
from urllib.parse import quote
from django.db import connection, transaction
from django.db.models import F
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_yasg.utils import swagger_auto_schema
from apps.applications.models import Application
from apps.enterprise.models import Membership
from core.resource_access import accessible_resources
from modules.tenancy.permissions import HasPathOrganizationRole
from modules.execution.application.start_runs import start_application_run
from modules.execution.application.errors import DeploymentUnavailable, IdempotencyKeyReused, InvalidExecutionDefinition
from modules.execution.infrastructure.artifacts import get_artifact_storage
from .access import application_for, project_for
from .models import Project, Snapshot, Task, Content, Version, Handoff
from .sources import fingerprint, limits
from .content import validate_document, markdown, animation, jianying
from .serializers import ProjectInput, ImportInput, TaskInput, SaveInput, HandoffInput, HandoffSaveInput


def parsed(cls, request, partial=False):
    serializer = cls(data=request.data, partial=partial)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def key_for(request):
    key = request.headers.get('Idempotency-Key', '')
    if not key or len(key) > 160:
        raise ValidationError('需要不超过 160 字符的 Idempotency-Key。')
    return key


def project_data(p):
    return {'id': str(p.id), 'title': p.title, 'archived': p.archived, 'updated_at': p.updated_at}


def task_data(t):
    return {'id': str(t.id), 'kind': t.kind, 'snapshot_id': str(t.snapshot_id), 'options': t.options,
            'status': t.run.status if t.run else 'failed', 'run_id': str(t.run_id or ''),
            'error': t.run.error_message if t.run else '任务不可用', 'output': t.output,
            'progress': (t.run.events.filter(type='progress.updated').order_by('-sequence').values_list('payload', flat=True).first() or {}) if t.run else {},
            'created_at': t.created_at}


def snapshot_data(s):
    job = s.task_set.filter(kind='import').select_related('run').first()
    status = s.status
    if status == 'pending' and job and job.run and job.run.status in {'failed', 'cancelled'}:
        status = job.run.status
    if status == 'ready' and job and job.run and job.run.status != 'succeeded':
        status = job.run.status
    return {'id': str(s.id), 'origin': {k: v for k, v in s.origin.items() if k != 'upload_key'},
            'status': status, 'error': s.error or (job.run.error_message if job and job.run else ''),
            'digest': s.digest, 'coverage': s.coverage, 'created_at': s.created_at}


def content_data(c):
    return {'id': str(c.id), 'title': c.title, 'analysis_id': str(c.analysis_id), 'revision': c.revision,
            'draft': c.draft, 'versions': [{'id': str(v.id), 'revision': v.revision, 'document': v.document} for v in c.versions.all()]}


def destination(user, project, target_id):
    return get_object_or_404(accessible_resources(Application.objects.for_organization(project.organization_id).filter(
        is_active=True, slug__in=['copy-to-jianying', 'animation-studio']), user, operation='run'), pk=target_id)


def handoff_data(h):
    if h.kind == 'animation':
        url = f'/applications/{h.target_application_id}/animation-studio?project={h.target_id}'
    else:
        url = f'/applications/{h.target_application_id}/chat?slug=copy-to-jianying&repoApplication={h.project.application_id}&repoHandoff={h.id}'
        if h.target_id:
            url += '&conversation=' + quote(h.target_id)
    return {'id': str(h.id), 'kind': h.kind, 'version_id': str(h.version_id), 'target_application_id': h.target_application_id,
            'target_id': h.target_id, 'url': url, 'draft': h.draft, 'revision': h.revision,
            'status': '作品草稿已创建' if h.kind == 'animation' else ('会话已关联' if h.target_id else '待进入制作'), 'created_at': h.created_at}


class BaseView(APIView):
    permission_classes = [HasPathOrganizationRole]
    minimum_role = Membership.Role.VIEWER

    def application(self):
        return application_for(self.request.user, self.kwargs['organization_id'], self.kwargs['application_id'])

    def project(self, lock=False):
        return project_for(self.request.user, self.kwargs['organization_id'], self.kwargs['application_id'], self.kwargs['project_id'], lock)

    def handle_exception(self, exc):
        if isinstance(exc, (ValueError, PermissionError)):
            exc = ValidationError(str(exc))
        return super().handle_exception(exc)


class ProjectsView(BaseView):
    def get(self, request, **kwargs):
        app = self.application()
        items = Project.objects.filter(application=app, owner=request.user, archived=request.query_params.get('archived') == '1')
        return Response([project_data(p) for p in items.filter(title__icontains=request.query_params.get('q', '')[:200])[:200]])

    @swagger_auto_schema(request_body=ProjectInput)
    def post(self, request, **kwargs):
        app = self.application()
        return Response(project_data(Project.objects.create(application=app, organization=app.organization,
            owner=request.user, **parsed(ProjectInput, request))), status=201)


class ProjectView(BaseView):
    def get(self, request, **kwargs):
        p = self.project()
        return Response({**project_data(p), 'snapshots': [snapshot_data(s) for s in p.snapshots.defer('files')],
            'tasks': [task_data(t) for t in p.tasks.select_related('run').all()[:100]],
            'contents': [content_data(c) for c in p.contents.filter(generation__run__status='succeeded')],
            'handoffs': [handoff_data(h) for h in p.handoffs.select_related('target_application', 'project').all()], 'limits': limits()})

    @swagger_auto_schema(request_body=ProjectInput)
    @transaction.atomic
    def patch(self, request, **kwargs):
        p = self.project(lock=True)
        for k, v in parsed(ProjectInput, request, partial=True).items():
            setattr(p, k, v)
        p.save()
        return Response(project_data(p))


def start(project, user, snapshot, kind, options, key, digest):
    task = Task.objects.create(project=project, snapshot=snapshot, kind=kind, options=options, request_key=key, request_hash=digest)
    try:
        task.run, _ = start_application_run(organization_id=project.organization_id, application_id=project.application_id,
            actor=user, input_data={'repo_project_id': str(project.id), 'task_id': str(task.id)}, priority=0,
            idempotency_key=f'repo:{task.id}')
    except (DeploymentUnavailable, IdempotencyKeyReused, InvalidExecutionDefinition) as exc:
        raise ValidationError(str(exc)) from None
    task.save(update_fields=['run'])
    return task


def previous(project, key, digest, model=Task):
    item = model.objects.filter(project=project, request_key=key).first()
    if item and item.request_hash != digest:
        raise ValidationError('同一请求键不能用于不同内容。')
    return item


class ImportView(BaseView):
    @swagger_auto_schema(request_body=ImportInput)
    @transaction.atomic
    def post(self, request, **kwargs):
        p = self.project(lock=True)
        values = parsed(ImportInput, request)
        origin = {k: v for k, v in values.items() if k != 'file'}
        raw = None
        if values['kind'] == 'zip':
            upload = values['file']
            if upload.size > limits()['archive_bytes']:
                raise ValidationError('源码 ZIP 超过上传大小限制。')
            raw = upload.read(limits()['archive_bytes'] + 1)
            import hashlib
            origin.update(filename=upload.name, sha256=hashlib.sha256(raw).hexdigest())
        if values['kind'] == 'local':
            from apps.applications.runtime_paths import resolve_runtime_path
            origin['path'] = str(resolve_runtime_path(values['path'], request.user))
        key, digest = key_for(request), fingerprint(origin)
        existing = previous(p, key, digest)
        if existing:
            return Response(task_data(existing))
        upload_key = ''
        if raw is not None:
            upload_key = f'repo-import/{p.organization_id}/{p.owner_id}/{uuid.uuid4()}.zip'
            get_artifact_storage().put(upload_key, raw)
            origin['upload_key'] = upload_key
        try:
            snapshot = Snapshot.objects.create(project=p, origin=origin)
            task = start(p, request.user, snapshot, 'import', {'upload_key': upload_key}, key, digest)
        except Exception:
            if upload_key:
                get_artifact_storage().delete(upload_key)
            raise
        return Response(task_data(task), status=202)


class TasksView(BaseView):
    @swagger_auto_schema(request_body=TaskInput)
    @transaction.atomic
    def post(self, request, **kwargs):
        p = self.project(lock=True)
        values = parsed(TaskInput, request)
        for k in ('snapshot_id', 'analysis_id'):
            if k in values:
                values[k] = str(values[k])
        key, digest = key_for(request), fingerprint(values)
        existing = previous(p, key, digest)
        if existing:
            return Response(task_data(existing))
        if values['kind'] == 'analyze':
            snapshot = get_object_or_404(p.snapshots, pk=values.get('snapshot_id'), status='ready')
            if not snapshot.task_set.filter(kind='import', run__status='succeeded').exists():
                raise ValidationError('快照导入任务尚未成功完成。')
        else:
            analysis = get_object_or_404(p.tasks, pk=values.get('analysis_id'), kind='analyze', run__status='succeeded')
            selected = values.get('feature_ids', [])
            if not selected or not set(selected) <= {f['id'] for f in analysis.output['features']}:
                raise ValidationError('请选择当前分析结果中的功能。')
            snapshot = analysis.snapshot
        return Response(task_data(start(p, request.user, snapshot, values['kind'], values, key, digest)), status=202)


class TaskView(BaseView):
    def get(self, request, task_id, **kwargs):
        return Response(task_data(get_object_or_404(self.project().tasks, pk=task_id)))

    def post(self, request, task_id, **kwargs):
        from app_center.research_assistant.backend.services import cancel
        task = get_object_or_404(self.project().tasks, pk=task_id)
        cancel(task.run, request.user, 'user_cancelled')
        task.refresh_from_db()
        if task.kind == 'import' and task.run and task.run.status == 'cancelled' and task.options.get('upload_key'):
            get_artifact_storage().delete(task.options['upload_key'])
        return Response(task_data(task))


class EvidenceView(BaseView):
    def get(self, request, snapshot_id, **kwargs):
        snapshot = get_object_or_404(self.project().snapshots, pk=snapshot_id, status='ready')
        if not snapshot.task_set.filter(kind='import', run__status='succeeded').exists():
            raise ValidationError('快照导入任务尚未成功完成。')
        path = request.query_params.get('path', '')
        if path not in snapshot.files:
            raise ValidationError('文件不在当前快照中。')
        source_url = ''
        if snapshot.origin['kind'] == 'github':
            source_url = snapshot.origin['url'] + '/blob/' + snapshot.origin['commit'] + '/' + quote(path)
        return Response({'path': path, **snapshot.files[path], 'source_url': source_url, 'snapshot_id': str(snapshot.id)})


class ContentView(BaseView):
    @swagger_auto_schema(request_body=SaveInput)
    @transaction.atomic
    def put(self, request, content_id, **kwargs):
        p = self.project(lock=True)
        c = get_object_or_404(p.contents.select_for_update(), pk=content_id, generation__run__status='succeeded')
        values = parsed(SaveInput, request)
        if values['revision'] != c.revision:
            return Response({'detail': '服务器已有新版本，本地内容已保留。', 'current': content_data(c)}, status=409)
        document = validate_document(values['document'], c.analysis.output)
        if document != c.draft:
            c.revision += 1
            c.draft, c.title = document, document['title']
            c.save()
            Version.objects.create(content=c, revision=c.revision, document=document)
        return Response(content_data(c))


class DownloadView(BaseView):
    def get(self, request, content_id, **kwargs):
        c = get_object_or_404(self.project().contents, pk=content_id, generation__run__status='succeeded')
        response = HttpResponse(markdown(c.draft), content_type='text/markdown; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="repo-content.md"'
        response['Cache-Control'] = 'private, no-store'
        return response


class IntegrationsView(BaseView):
    def get(self, request, **kwargs):
        app = self.application()
        apps = accessible_resources(Application.objects.for_organization(app.organization_id).filter(
            is_active=True, slug__in=['copy-to-jianying', 'animation-studio']), request.user, operation='run')
        return Response([{'id': a.id, 'name': a.name, 'slug': a.slug} for a in apps])


class HandoffsView(BaseView):
    @swagger_auto_schema(request_body=HandoffInput)
    @transaction.atomic
    def post(self, request, **kwargs):
        p = self.project(lock=True)
        values = parsed(HandoffInput, request)
        target = destination(request.user, p, values['target_id'])
        version = get_object_or_404(Version, pk=values['version_id'], content__project=p, content__generation__run__status='succeeded')
        key, digest = key_for(request), fingerprint({'version': str(version.id), 'target': target.id})
        old = previous(p, key, digest, Handoff)
        if old:
            return Response(handoff_data(old))
        kind = 'animation' if target.slug == 'animation-studio' else 'jianying'
        draft = animation(version.document) if kind == 'animation' else jianying(version.document)
        h = Handoff.objects.create(project=p, version=version, target_application=target, kind=kind, draft=draft,
                                   request_key=key, request_hash=digest)
        if kind == 'animation':
            from app_center.animation_studio.backend.models import AnimationProject
            from app_center.animation_studio.backend.projects import document_assets
            document_assets(request.user, target, draft)
            work = AnimationProject.objects.create(organization=p.organization, application=target,
                owner=request.user, title=version.document['title'], draft=draft)
            h.target_id = str(work.id)
            h.save(update_fields=['target_id'])
        return Response(handoff_data(h), status=201)


class HandoffView(BaseView):
    def item(self, lock=False):
        self.application()
        qs = Handoff.objects.select_related('project', 'target_application').filter(project__organization_id=self.kwargs['organization_id'],
            project__application_id=self.kwargs['application_id'], project__owner=self.request.user)
        if lock and connection.vendor == 'sqlite':
            qs.filter(pk=self.kwargs['handoff_id']).update(revision=F('revision'))
        h = get_object_or_404(qs.select_for_update() if lock else qs, pk=self.kwargs['handoff_id'])
        destination(self.request.user, h.project, h.target_application_id)
        return h

    def get(self, request, **kwargs):
        return Response(handoff_data(self.item()))

    @swagger_auto_schema(request_body=HandoffSaveInput)
    @transaction.atomic
    def patch(self, request, **kwargs):
        h = self.item(lock=True)
        data = parsed(HandoffSaveInput, request)
        if h.kind != 'jianying':
            raise ValidationError('请在动画制作中编辑作品。')
        if data['revision'] != h.revision:
            return Response({'detail': '交接草稿存在新版本，请保留当前内容并重新载入。'}, status=409)
        if 'draft' in data:
            if any(k not in h.draft or not isinstance(v, str) or len(v) > 80000 for k, v in data['draft'].items()):
                raise ValidationError('剪映表单字段格式无效。')
            h.draft = {**h.draft, **data['draft']}
        if data.get('conversation_id'):
            from apps.conversations.models import Conversation
            conversation = get_object_or_404(Conversation, pk=data['conversation_id'], user=request.user, chat_application__application_id=h.target_application_id, organization=h.project.organization)
            h.target_id = str(conversation.pk)
        h.revision += 1
        h.save()
        return Response(handoff_data(h))
