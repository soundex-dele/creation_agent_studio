import csv
import hashlib
import io
import logging
from uuid import uuid4
from django.db import transaction
from django.db.models import Sum
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from modules.platform_api.identity import Application, Membership, accessible_resources
from modules.platform_api.tenancy import HasPathOrganizationRole
from modules.platform_api.images import inspect_image, MAX_IMAGE_BYTES
from modules.platform_api.artifacts import get_artifact_storage, ArtifactObjectUnavailable
from modules.platform_api.execution import start_application_run, cancel_run
from modules.platform_api.execution import DeploymentUnavailable, IdempotencyKeyReused, InvalidExecutionDefinition
from .models import MusicLibrary, Playlist, MusicOperation, MusicTask, MusicImage
from .domain import DEFAULTS, ACTIVE, Mutation, TaskInput, digest, identity, tracks_validated


def task_data(task):
    status = task.status
    if task.run and status in ACTIVE and task.run.status in {'failed', 'cancelled'}:
        status = task.run.status
    return dict(id=str(task.pk), kind=task.kind, status=status, progress=task.progress,
                error=task.error or ('任务执行失败，请检查额度或模型状态后重试。' if status == 'failed' else ''),
                result=task.result, imported=task.imported, createdAt=task.created_at.isoformat(),
                imageIds=task.snapshot.get('imageIds', []), filters=task.snapshot.get('filters', {}))


def snapshot(library):
    return dict(revision=library.revision, preferences={**DEFAULTS, **library.preferences}, feedback=library.feedback,
                playlists=[dict(id=str(p.pk), name=p.name, tracks=p.tracks) for p in library.playlists.all()])


def cleanup_images(task):
    for image in task.images.all():
        try:
            get_artifact_storage().delete(image.object_key)
            image.delete()
        except Exception:
            logging.getLogger(__name__).exception('Song image cleanup pending: %s', image.pk)


class Access(APIView):
    permission_classes = [HasPathOrganizationRole]
    minimum_role = Membership.Role.VIEWER

    def library(self, *, lock=False):
        application = get_object_or_404(accessible_resources(
            Application.objects.for_organization(self.kwargs['organization_id']).filter(
                is_active=True, slug='song-curator', kind=Application.Kind.CUSTOM),
            self.request.user, operation='run'), pk=self.kwargs['application_id'])
        library, _ = MusicLibrary.objects.for_organization(application.organization_id).get_or_create(
            organization=application.organization, application=application, owner=self.request.user)
        return MusicLibrary.objects.select_for_update().get(pk=library.pk) if lock else library

    def conflict(self, message='数据已更新，请刷新后重新应用本次操作。'):
        return Response({'detail': message}, status=409)


class StateView(Access):
    def get(self, request, **kwargs):
        return Response(snapshot(self.library()))

    @transaction.atomic
    def patch(self, request, **kwargs):
        validator = Mutation(data=request.data)
        validator.is_valid(raise_exception=True)
        data = dict(validator.data)
        key = data.pop('requestKey')
        fingerprint = digest(data)
        library = self.library(lock=True)
        previous = MusicOperation.objects.filter(library=library, request_key=key).first()
        if previous:
            return Response(snapshot(library)) if previous.request_hash == fingerprint else self.conflict('请求键已用于不同操作。')
        if data['revision'] != library.revision:
            return self.conflict()
        action = data['action']
        playlist = get_object_or_404(library.playlists, pk=data['playlistId']) if data.get('playlistId') else None
        if action == 'confirm':
            task = get_object_or_404(library.tasks, pk=data['taskId'], deleted=False, kind='import', status='succeeded')
            if task.imported:
                return self.conflict('这批识别结果已经导入。')
            task.imported = True
            task.save(update_fields=['imported'])
        if action == 'create' or (action == 'confirm' and not playlist):
            if library.playlists.count() >= 50:
                raise ValidationError('最多保存 50 个歌单。')
            playlist = Playlist.objects.create(organization=library.organization, library=library, name=data['name'])
        if action == 'rename':
            playlist.name = data['name']
            playlist.save(update_fields=['name', 'updated_at'])
        if action == 'delete':
            playlist.delete()
        if action in ('create', 'add', 'confirm'):
            additions = tracks_validated(data.get('tracks', []))
            seen = {identity(t) for t in playlist.tracks}
            playlist.tracks += [t for t in additions if identity(t) not in seen]
            if len(playlist.tracks) > 500:
                raise ValidationError('每个歌单最多 500 首，请拆分为多个歌单。')
            playlist.save(update_fields=['tracks', 'updated_at'])
        if action == 'remove':
            ids = set(data['trackIds'])
            if not ids.issubset({t['id'] for t in playlist.tracks}):
                raise ValidationError('所选歌曲已不存在。')
            playlist.tracks = [t for t in playlist.tracks if t['id'] not in ids]
            playlist.save(update_fields=['tracks', 'updated_at'])
        if action == 'preferences':
            library.preferences = data['preferences']
        if action == 'feedback':
            track = tracks_validated(data['tracks'])[0]
            library.feedback = [r for r in library.feedback if identity(r['track']) != identity(track)]
            if data['feedback'] != 'none':
                if len(library.feedback) >= 2000:
                    raise ValidationError('反馈已达 2000 条，请先清理旧反馈。')
                library.feedback.append({'track': track, 'value': data['feedback']})
        library.revision += 1
        library.save(update_fields=['preferences', 'feedback', 'revision'])
        MusicOperation.objects.create(organization=library.organization, library=library, request_key=key, request_hash=fingerprint)
        return Response(snapshot(library))


class ImagesView(Access):
    @transaction.atomic
    def post(self, request, **kwargs):
        library = self.library(lock=True)
        key = str(request.headers.get('Idempotency-Key') or '').strip()
        if not key or len(key) > 160:
            raise ValidationError('请提供有效的请求键。')
        upload = request.FILES.get('file')
        if upload is None or upload.size > MAX_IMAGE_BYTES:
            raise ValidationError('请选择不超过 20 MB 的 PNG、JPEG 或 WebP 图片。')
        content = upload.read(MAX_IMAGE_BYTES + 1)
        metadata = inspect_image(content)
        fingerprint = hashlib.sha256(content).hexdigest()
        existing = library.images.filter(request_key=key).first()
        if existing:
            if existing.request_hash != fingerprint:
                return self.conflict('请求键已用于其他图片。')
            if existing.task_id and existing.task.deleted:
                return self.conflict('图片所属任务已删除，请重新上传。')
            return Response({'id': str(existing.pk)})
        if library.images.filter(task__isnull=True).count() >= 20:
            raise ValidationError('待导入图片已达 20 张，请移除不用的图片后继续。')
        if (library.images.aggregate(total=Sum('size'))['total'] or 0) + len(content) > 500 * 1024 * 1024:
            raise ValidationError('歌单图片已达 500 MB，请删除不用的导入任务后继续。')
        image_id = uuid4()
        object_key = f'song-curator/{library.organization_id}/{library.owner_id}/{image_id}'
        storage = get_artifact_storage()
        storage.put(object_key, content)
        try:
            image = MusicImage.objects.create(id=image_id, organization=library.organization, library=library,
                object_key=object_key, mime_type=metadata['mime_type'], size=len(content), request_key=key, request_hash=fingerprint)
        except Exception:
            storage.delete(object_key)
            raise
        return Response({'id': str(image.pk)}, status=201)


class ImageView(Access):
    def get(self, request, image_id, **kwargs):
        image = get_object_or_404(self.library().images, pk=image_id)
        if image.task_id and image.task.deleted:
            raise Http404
        try:
            response = FileResponse(get_artifact_storage().open(image.object_key), content_type=image.mime_type)
        except ArtifactObjectUnavailable:
            raise Http404('原图已不可用。') from None
        response['Cache-Control'] = 'private, no-store'
        response['X-Content-Type-Options'] = 'nosniff'
        return response

    @transaction.atomic
    def delete(self, request, image_id, **kwargs):
        library = self.library(lock=True)
        image = library.images.filter(pk=image_id, task__isnull=True).first()
        if image:
            get_artifact_storage().delete(image.object_key)
            image.delete()
        return Response(status=204)


class TasksView(Access):
    def get(self, request, **kwargs):
        library = self.library()
        try:
            page = max(1, int(request.query_params.get('page', '1')))
        except ValueError:
            raise ValidationError('页码无效。') from None
        tasks = library.tasks.filter(deleted=False).select_related('run')
        return Response({'count': tasks.count(), 'results': [task_data(t) for t in tasks[(page-1)*20:page*20]]})

    @transaction.atomic
    def post(self, request, **kwargs):
        validator = TaskInput(data=request.data)
        validator.is_valid(raise_exception=True)
        data = dict(validator.data)
        key = data.pop('requestKey')
        fingerprint = digest(data)
        library = self.library(lock=True)
        existing = library.tasks.filter(request_key=key).select_related('run').first()
        if existing:
            if existing.request_hash != fingerprint or existing.deleted:
                return self.conflict('请求键已用于其他任务或已删除任务。')
            return Response(task_data(existing))
        if data['revision'] != library.revision:
            return self.conflict()
        if library.tasks.filter(status__in=ACTIVE, deleted=False).exclude(run__status__in=['failed', 'cancelled', 'succeeded']).count() >= 3:
            raise ValidationError('已有 3 个任务处理中，请稍后再试。')
        images = list(library.images.filter(pk__in=data['imageIds'], task__isnull=True))
        if len(images) != len(data['imageIds']):
            raise ValidationError('图片已使用或不可访问，请重新上传。')
        seeds = []
        if data['kind'] == 'similar':
            playlist = get_object_or_404(library.playlists, pk=data['playlistId'])
            ids = set(data['trackIds'])
            if ids and not ids.issubset({t['id'] for t in playlist.tracks}):
                raise ValidationError('种子歌曲已不存在。')
            seeds = [t for t in playlist.tracks if not ids or t['id'] in ids]
            if not seeds:
                raise ValidationError('请先在歌单中添加歌曲。')
        preferences = {**DEFAULTS, **library.preferences}
        recent = [track for t in library.tasks.filter(deleted=False, status='succeeded').exclude(kind='import')[:10]
                  for track in t.result.get('tracks', [])]
        frozen = {**data, 'seeds': seeds, 'preferences': preferences,
                  'filters': {**preferences, **data['filters']}, 'feedback': library.feedback, 'recent': recent}
        task = MusicTask.objects.create(organization=library.organization, library=library, kind=data['kind'],
            request_key=key, request_hash=fingerprint, snapshot=frozen)
        try:
            task.run, _ = start_application_run(organization_id=library.organization_id, application_id=library.application_id,
                actor=request.user, input_data={'task_id': str(task.pk)}, priority=0, idempotency_key=f'song:{task.pk}')
        except (DeploymentUnavailable, IdempotencyKeyReused, InvalidExecutionDefinition) as exc:
            transaction.set_rollback(True)
            return self.conflict(str(exc))
        task.save(update_fields=['run'])
        library.images.filter(pk__in=data['imageIds']).update(task=task)
        return Response(task_data(task), status=202)


class TaskView(Access):
    def get(self, request, task_id, **kwargs):
        return Response(task_data(get_object_or_404(self.library().tasks.select_related('run'), pk=task_id, deleted=False)))

    @transaction.atomic
    def delete(self, request, task_id, **kwargs):
        task = self.library(lock=True).tasks.select_for_update().filter(pk=task_id).first()
        if task:
            task.deleted = True
            task.cancel_requested = True
            task.save(update_fields=['deleted', 'cancel_requested'])
            cancel_run(task.run, request.user, '删除音乐任务')
            transaction.on_commit(lambda: cleanup_images(task))
        return Response(status=204)


class CancelView(Access):
    @transaction.atomic
    def post(self, request, task_id, **kwargs):
        task = get_object_or_404(self.library(lock=True).tasks.select_for_update(), pk=task_id, deleted=False)
        if task_data(task)['status'] in ACTIVE:
            task.cancel_requested = True
            task.status = 'cancelled'
            task.save(update_fields=['cancel_requested', 'status'])
            cancel_run(task.run, request.user, '用户取消音乐任务')
        return Response(task_data(task))


class ExportView(Access):
    def get(self, request, playlist_id, **kwargs):
        playlist = get_object_or_404(self.library().playlists, pk=playlist_id)
        # `format` is DRF's reserved renderer override, not a download option.
        kind = request.query_params.get('fileType', 'txt')
        if kind not in ('txt', 'csv'):
            raise ValidationError('仅支持 TXT 和 CSV。')
        if kind == 'txt':
            content = '\n'.join(f"{t['title']} — {t['artist'] or '歌手待补充'}" + (f" ({t['version']})" if t['version'] else '') for t in playlist.tracks)
        else:
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(['歌名', '歌手', '专辑', '版本'])
            for track in playlist.tracks:
                # Spreadsheet formula injection protection for user/model text.
                values = [track.get(k, '') for k in ('title', 'artist', 'album', 'version')]
                writer.writerow(["'" + v if v.lstrip().startswith(('=', '+', '-', '@')) else v for v in values])
            content = '\ufeff' + output.getvalue()
        response = HttpResponse(content, content_type=f'text/{"csv" if kind == "csv" else "plain"}; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="playlist.{kind}"'
        return response
