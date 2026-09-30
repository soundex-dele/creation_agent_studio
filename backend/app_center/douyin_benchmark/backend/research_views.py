from django.db import transaction, IntegrityError
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import ValidationError, MethodNotAllowed
from rest_framework.response import Response
from . import models as m
from . import research_serializers as rs
from .views import BaseView, page, TaskView, CancelView, VersionsView, DownloadView, FrameView
from .serializers import TaskSerializer, VersionSerializer
from .research import scope_for, works_for, work_data, valid_date, trend, comparison, start_research
from .services import Conflict
from datetime import timedelta


RESOURCES = {
    'creator-profiles': (m.CreatorProfile, rs.ProfileSerializer), 'inspirations': (m.Inspiration, rs.InspirationSerializer),
    'ideas': (m.Idea, rs.IdeaSerializer), 'publications': (m.Publication, rs.PublicationSerializer),
    'subscriptions': (m.Subscription, rs.SubscriptionSerializer), 'notifications': (m.Notification, rs.NotificationSerializer),
    'digests': (m.Digest, rs.DigestSerializer),
}


class WorkspaceMixin:
    def scope(self):
        return scope_for(self.app(), self.request.user)

    def task(self, lock=False):
        qs = m.Task.objects.filter(**self.scope()).select_related('run')
        return get_object_or_404(qs.select_for_update() if lock else qs, pk=self.kwargs['task_id'])


class RecordsView(WorkspaceMixin, BaseView):
    def resource(self):
        return RESOURCES[self.kwargs['resource']]

    def get(self, request, **kwargs):
        model, serializer = self.resource()
        qs = model.objects.filter(**self.scope())
        if model is m.CreatorProfile:
            qs = qs.order_by('-is_default', '-updated_at', 'id')
        if kwargs.get('record_id'):
            return Response(serializer(get_object_or_404(qs, pk=kwargs['record_id'])).data)
        search = request.query_params.get('search', '')[:200]
        if search and model in [m.Inspiration, m.Idea, m.Publication]:
            qs = qs.filter(Q(title__icontains=search) | Q(notes__icontains=search))
        if model in [m.Inspiration, m.Idea] and request.query_params.get('tag'):
            # Portable for both SQLite and PostgreSQL JSON storage.
            tag = request.query_params['tag'][:40]
            qs = qs.filter(pk__in=[row.pk for row in qs if tag in row.tags])
        if model is m.Idea:
            if request.query_params.get('status'):
                qs = qs.filter(status=request.query_params['status'])
            qs = qs.order_by('position', '-updated_at', 'id') if request.query_params.get('sort') == 'position' else qs
        if model is m.Notification and request.query_params.get('unread') == 'true':
            qs = qs.filter(read=False)
        return Response(page(request, qs, serializer))

    @transaction.atomic
    def post(self, request, **kwargs):
        if kwargs.get('record_id'):
            raise MethodNotAllowed('POST')
        return self.write(request)

    @transaction.atomic
    def patch(self, request, **kwargs):
        return self.write(request, kwargs.get('record_id'))

    def write(self, request, pk=None):
        model, serializer_class = self.resource()
        if model is m.Digest or (model is m.Notification and not pk):
            raise MethodNotAllowed(request.method)
        scope = self.scope()
        type(request.user).objects.select_for_update().get(pk=request.user.pk)
        instance = get_object_or_404(model.objects.filter(**scope).select_for_update(), pk=pk) if pk else None
        if instance and request.data.get('revision') != instance.revision:
            raise Conflict('内容已更新，请刷新后重试。')
        serializer = serializer_class(instance, data=request.data, partial=bool(instance), context={'scope': scope})
        serializer.is_valid(raise_exception=True)
        if model is m.CreatorProfile and serializer.validated_data.get('is_default'):
            from django.db.models import F
            model.objects.filter(**scope, is_default=True).exclude(pk=pk).update(is_default=False, revision=F('revision') + 1)
        extra = {**scope, 'revision': instance.revision + 1 if instance else 1}
        if model is m.Subscription:
            enabled = serializer.validated_data.get('enabled', instance.enabled if instance else False)
            if enabled and not m.CollectorConfig.objects.filter(**scope).exists():
                raise ValidationError('请先保存采集配置。')
            extra.update(next_run_at=timezone.now() if enabled else None, blocked_reason='')
        try:
            with transaction.atomic():
                record = serializer.save(**extra)
        except IntegrityError:
            raise Conflict('该记录已存在，请编辑已有记录。') from None
        if model is m.Publication and record.idea_id:
            from django.db.models import F
            m.Idea.objects.filter(pk=record.idea_id, **scope).update(status='published', revision=F('revision') + 1)
        if model is m.Subscription and not record.enabled:
            from .services import cancel
            for task in m.Task.objects.filter(**scope, input__subscription_id=str(record.pk)).select_related('run'):
                cancel(task)
        return Response(serializer_class(record).data, status=200 if instance else 201)

    @transaction.atomic
    def delete(self, request, **kwargs):
        model, _ = self.resource()
        record = get_object_or_404(model.objects.filter(**self.scope()).select_for_update(), pk=kwargs.get('record_id'))
        if model is m.Subscription:
            from .services import cancel
            for task in m.Task.objects.filter(**self.scope(), input__subscription_id=str(record.pk)).select_related('run'):
                cancel(task)
        record.delete()
        return Response(status=204)


class AllWorksView(WorkspaceMixin, BaseView):
    def get(self, request, **kwargs):
        scope = self.scope()
        qs = works_for(scope)
        if request.query_params.get('accounts'):
            from rest_framework import serializers
            field = serializers.ListField(child=serializers.UUIDField(), max_length=50)
            ids = field.run_validation(request.query_params['accounts'].split(','))
            qs = qs.filter(account_id__in=ids)
        if request.query_params.get('account'):
            qs = qs.filter(account_id=request.query_params['account'])
        if request.query_params.get('group'):
            qs = qs.filter(account__group=request.query_params['group'][:100])
        if request.query_params.get('owned') == 'true':
            qs = qs.filter(account__is_owned=True)
        search = request.query_params.get('search', '')[:200]
        if search:
            qs = qs.filter(metadata__title__icontains=search)
        days = request.query_params.get('days')
        if days and days not in ['7', '30', '90']:
            raise ValidationError('时间范围必须为7、30或90天。')
        rows = [work_data(w) for w in qs]
        if days:
            now = timezone.now()
            rows = [r for r in rows if (date := valid_date(r.get('published_at'))) and now - timedelta(days=int(days)) <= date <= now]
        sort = request.query_params.get('sort', 'published_at')
        if sort not in ['published_at', 'likes', 'comments', 'collects', 'shares']:
            raise ValidationError('排序字段无效。')
        rows.sort(key=lambda r: (r.get(sort) is not None, r.get(sort) or ('' if sort == 'published_at' else 0)), reverse=True)
        from django.core.paginator import Paginator
        paginator = Paginator(rows, 20)
        return Response({'count': len(rows), 'results': list(paginator.get_page(request.query_params.get('page', 1)))})


class TrendView(WorkspaceMixin, BaseView):
    def get(self, request, **kwargs):
        work = get_object_or_404(works_for(self.scope()), pk=kwargs['work_id'])
        return Response({'work': work_data(work), 'points': trend(work)})


class CommentsView(WorkspaceMixin, BaseView):
    def get(self, request, **kwargs):
        work = get_object_or_404(works_for(self.scope()), pk=kwargs['work_id'])
        batches = m.CommentBatch.objects.filter(work=work).order_by('-created_at')
        batch = get_object_or_404(batches, pk=request.query_params['batch']) if request.query_params.get('batch') else batches.first()
        if not batch:
            return Response({'batch': None, 'batches': [], 'count': 0, 'results': []})
        from django.core.paginator import Paginator
        paginator = Paginator(batch.comments.all(), 50)
        return Response({'batch': str(batch.pk), 'task_id': str(batch.task_id), 'complete': batch.complete, 'warning': batch.warning,
            'batches': [{'id': str(b.pk), 'task_id': str(b.task_id), 'created_at': b.created_at.isoformat()} for b in batches[:50]],
            'count': paginator.count, 'results': [{'id': f'comment:{c.pk}', 'platform_id': c.platform_id, 'parent_id': c.parent_id,
                'text': c.text, 'likes': c.likes, 'published_at': c.published_at} for c in paginator.get_page(request.query_params.get('page', 1))]})


class ComparisonView(WorkspaceMixin, BaseView):
    def post(self, request, **kwargs):
        serializer = rs.ResearchInput(data={**request.data, 'kind': 'compare'})
        serializer.is_valid(raise_exception=True)
        return Response(comparison(self.scope(), serializer.validated_data['account_ids'], serializer.validated_data['days']))


class ResearchTasksView(WorkspaceMixin, BaseView):
    def get(self, request, **kwargs):
        qs = m.Task.objects.filter(**self.scope()).select_related('run')
        if request.query_params.get('kind'):
            qs = qs.filter(kind__in=request.query_params['kind'].split(','))
        return Response(page(request, qs, TaskSerializer))

    def post(self, request, **kwargs):
        serializer = rs.ResearchInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        task = start_research(self.app(), request.user, serializer.validated_data, request.headers.get('Idempotency-Key'))
        return Response(TaskSerializer(task).data, status=201)


class PublicationSummaryView(WorkspaceMixin, BaseView):
    def get(self, request, **kwargs):
        from .research import publication_summary
        return Response(publication_summary(self.scope()))


class ResearchTaskView(WorkspaceMixin, TaskView):
    pass


class ResearchCancelView(WorkspaceMixin, CancelView):
    pass


class ResearchVersionsView(WorkspaceMixin, VersionsView):
    pass


class ResearchDownloadView(WorkspaceMixin, DownloadView):
    pass


class ResearchFrameView(WorkspaceMixin, FrameView):
    pass


class VariantApplyView(WorkspaceMixin, BaseView):
    @transaction.atomic
    def post(self, request, **kwargs):
        task = self.task(True)
        if task.kind != 'variants' or not task.run or task.run.status != 'succeeded':
            raise ValidationError('请选择已完成的表达实验。')
        source = get_object_or_404(m.ScriptVersion.objects.filter(**{f'task__{k}': v for k, v in self.scope().items()}), pk=task.input.get('source_version_id'))
        target = m.Task.objects.select_for_update().get(pk=source.task_id)
        latest = target.versions.first()
        if request.data.get('revision') != latest.revision:
            raise Conflict('原脚本已有新版本，请刷新后重试。')
        values = {}
        for key, limit in [('title', 300), ('cover', 300), ('hook', 3000)]:
            value = request.data.get(key, '')
            if not isinstance(value, str) or len(value) > limit:
                raise ValidationError('候选文案长度或类型无效。')
            if value.strip():
                values[key] = value.strip()
        content = dict(latest.content)
        if target.kind == 'rewrite':
            content['text'] = (values.get('hook', '') + '\n\n' + content['text']).strip()
        else:
            content.update({k: v for k, v in values.items() if k != 'hook'})
            if values.get('hook'):
                content['narration'] = values['hook'] + '\n\n' + content['narration']
        from .analysis import validate_script, validate_rewrite
        try:
            content = (validate_rewrite if target.kind == 'rewrite' else validate_script)(content)
        except ValueError as exc:
            raise ValidationError(str(exc)) from None
        version = m.ScriptVersion.objects.create(task=target, revision=latest.revision + 1, content=content)
        return Response(VersionSerializer(version).data, status=201)


class SubscriptionRefreshView(WorkspaceMixin, BaseView):
    @transaction.atomic
    def post(self, request, **kwargs):
        from .services import start
        subscription = get_object_or_404(m.Subscription.objects.filter(**self.scope()).select_for_update(), pk=kwargs['record_id'])
        account = m.Account.objects.select_for_update().get(pk=subscription.account_id)
        task = start(account, {'kind': 'collect', 'count': subscription.count, 'subscription_id': str(subscription.pk),
            'tracked_work_ids': [str(w.pk) for w in subscription.tracked_works.all()]}, request.headers.get('Idempotency-Key'))
        return Response(TaskSerializer(task).data, status=201)
