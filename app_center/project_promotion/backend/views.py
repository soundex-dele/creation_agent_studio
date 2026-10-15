from copy import deepcopy
from django.db import transaction
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import serializers as s
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from modules.platform_api.identity import Application
from modules.platform_api.identity import Membership
from modules.platform_api.identity import accessible_resources
from modules.platform_api.tenancy import HasPathOrganizationRole
from .models import RESOURCES, Workspace, Case, Topic, Channel, Version, Feedback
from .schemas import SCHEMAS, STATUSES, PLATFORMS, CopyBody, validated
from .materials import topic_materials, resolve_materials, set_materials, require_confirmed, sources_current, snapshot_materials


class Conflict(APIException):
    status_code = 409
    default_detail = '资料已更新，请重新加载后再保存。'


def basic(row):
    value = dict(id=str(row.pk), title=row.title, status=row.status, data=row.data, revision=row.revision,
                 archived=row.archived, created_at=row.created_at.isoformat(), updated_at=row.updated_at.isoformat())
    for key in ('case_id', 'topic_id', 'channel_id', 'confirmed_version_id', 'platform'):
        if hasattr(row, key):
            raw = getattr(row, key)
            value[key] = str(raw) if raw is not None else None
    if isinstance(row, Channel):
        value['latest_version'] = version_data(row.versions.first())
    if isinstance(row, Case):
        value['source_snapshot'] = row.source_snapshot
    if isinstance(row, Topic):
        value['case_ids'] = [str(material.pk) for material in topic_materials(row)]
    return value


def version_data(row):
    return dict(id=str(row.pk), number=row.number, body=row.body, snapshot=row.snapshot,
                created_at=row.created_at.isoformat()) if row else None


def channel_snapshot(channel):
    sources = [basic(material) for material in topic_materials(channel.topic)]
    return dict(case=sources[0], cases=sources, topic=basic(channel.topic), platform=channel.platform)


class Access(APIView):
    permission_classes = [HasPathOrganizationRole]
    minimum_role = Membership.Role.VIEWER

    def application(self):
        if not hasattr(self, '_application'):
            self._application = get_object_or_404(accessible_resources(
                Application.objects.for_organization(self.kwargs['organization_id']).filter(
                    is_active=True, slug='project-promotion', kind='custom'), self.request.user, operation='run'),
                pk=self.kwargs['application_id'])
        return self._application

    def ownership(self):
        return dict(organization_id=self.kwargs['organization_id'], application=self.application(), owner=self.request.user)

    def scope(self, model):
        return model.objects.for_organization(self.kwargs['organization_id']).filter(application=self.application(), owner=self.request.user)

    def lock(self):
        obj, _ = Workspace.objects.get_or_create(**self.ownership())
        return self.scope(Workspace).select_for_update().get(pk=obj.pk)

    def linked(self, model, identifier):
        identifier = s.UUIDField().run_validation(identifier)
        return get_object_or_404(self.scope(model), pk=identifier)


class Records(Access):
    def resource(self):
        kind = self.kwargs['resource']
        if kind not in RESOURCES:
            raise Http404
        return kind, RESOURCES[kind]

    def get(self, request, record_id=None, **kwargs):
        _, model = self.resource()
        query = self.scope(model)
        if record_id:
            return Response(basic(get_object_or_404(query, pk=record_id)))
        page = s.IntegerField(min_value=1).run_validation(request.query_params.get('page', 1))
        count = query.count()
        return Response(dict(count=count, next=page + 1 if count > page * 50 else None,
                             results=[basic(row) for row in query[(page - 1) * 50:page * 50]]))

    @transaction.atomic
    def post(self, request, **kwargs):
        self.lock()
        return self.save(request.data)

    @transaction.atomic
    def patch(self, request, record_id, **kwargs):
        self.lock()
        _, model = self.resource()
        return self.save(request.data, get_object_or_404(self.scope(model).select_for_update(), pk=record_id))

    def save(self, payload, row=None):
        kind, model = self.resource()
        allowed = {'title', 'status', 'revision', 'archived', 'data'}
        relation = {'channels': ('topic_id', Topic), 'feedback': ('channel_id', Channel)}.get(kind)
        if kind == 'topics':
            allowed.update({'case_id', 'case_ids'})
        if relation:
            allowed.add(relation[0])
        if kind == 'channels':
            allowed.add('platform')
        if not isinstance(payload, dict) or set(payload) - allowed:
            raise ValidationError('包含不支持的字段。')
        if row and payload.get('revision') != row.revision:
            raise Conflict()
        title = s.CharField(max_length=200).run_validation(payload.get('title', row.title if row else None))
        status = s.ChoiceField(choices=STATUSES[kind]).run_validation(payload.get('status', row.status if row else STATUSES[kind][0]))
        raw = deepcopy(row.data) if row else {}
        if not isinstance(payload.get('data', {}), dict):
            raise ValidationError('data 必须为对象。')
        raw.update(payload.get('data', {}))
        data = validated(SCHEMAS[kind], raw)
        extra = {}
        if relation:
            key, related_model = relation
            identifier = payload.get(key, getattr(row, key, None))
            if identifier is None and kind == 'feedback':
                extra[key] = None
            else:
                linked = self.linked(related_model, identifier)
                if row and str(getattr(row, key)) != str(linked.pk):
                    raise ValidationError('请新建记录以更换关联来源。')
                extra[key] = linked.pk
                if kind == 'feedback' and linked.status != 'published':
                    raise ValidationError('反馈只能关联已发布内容，来源不明时请留空。')
        if kind == 'cases' and status == 'confirmed':
            fields = ('audience', 'problem', 'solution', 'implemented') if data['material_type'] == 'case' else ('summary', 'facts')
            if any(not data[field].strip() for field in fields):
                raise ValidationError('确认案例前请补齐目标读者、问题、解决方案和已实现能力。' if data['material_type'] == 'case'
                    else '确认素材前请补齐摘要和事实资料。')
        if kind == 'topics':
            materials = resolve_materials(self, payload, row)
            extra['case_id'] = materials[0].pk
            if status == 'confirmed':
                require_confirmed(materials)
            if data.get('source_feedback_id'):
                self.linked(Feedback, data['source_feedback_id'])
        if kind == 'channels':
            platform = s.ChoiceField(choices=PLATFORMS).run_validation(payload.get('platform', row.platform if row else None))
            if row and platform != row.platform:
                raise ValidationError('每个渠道独立管理，请为其他平台新增记录。')
            if not row and self.scope(Channel).filter(topic_id=extra['topic_id'], platform=platform).exists():
                raise Conflict('此选题已有该渠道，请打开现有记录。')
            extra['platform'] = platform
            if status in ('ready', 'published') and (not row or not row.confirmed_version_id):
                raise ValidationError('请先审核并确认一个文案版本。')
            if status == 'published' and not data['published_at']:
                raise ValidationError('请登记实际发布时间。')
            if status == 'published' and row and row.status != 'published':
                if row.topic.archived or row.topic.status != 'confirmed':
                    raise ValidationError('请先确认有效选题。')
                require_confirmed(topic_materials(row.topic))
                snapshot = row.confirmed_version.snapshot
                if not sources_current(row.topic, snapshot) or snapshot.get('topic', {}).get('revision') != row.topic.revision:
                    raise Conflict('素材或选题已变化，请核对并确认新版本后发布。')
            if status != 'published' and (data['published_at'] or data['publication_url']):
                raise ValidationError('请将状态改为已发布后登记发布信息。')
            if row and row.status == 'published' and status != 'published':
                raise ValidationError('已发布记录保留发布状态和所用版本。')
        archived = s.BooleanField().run_validation(payload.get('archived', row.archived if row else False))
        if row:
            for key, value in dict(title=title, status=status, data=data, archived=archived, **extra).items():
                setattr(row, key, value)
            row.revision += 1
            row.save()
            if kind == 'topics':
                set_materials(row, materials)
            return Response(basic(row))
        row = model.objects.create(**self.ownership(), title=title, status=status, data=data, archived=archived, **extra)
        if kind == 'topics':
            set_materials(row, materials)
        return Response(basic(row), status=201)


class Versions(Access):
    def get(self, request, record_id, **kwargs):
        channel = self.linked(Channel, record_id)
        return Response([version_data(v) for v in channel.versions.all()])

    @transaction.atomic
    def post(self, request, record_id, **kwargs):
        self.lock()
        channel = self.linked(Channel, record_id)
        if request.data.get('revision') != channel.revision:
            raise Conflict()
        if channel.archived:
            raise ValidationError('请先恢复渠道记录。')
        body = validated(CopyBody, request.data.get('body'))
        snapshot = channel_snapshot(channel)
        if request.data.get('base_version_id'):
            parent = get_object_or_404(channel.versions, pk=s.UUIDField().run_validation(request.data['base_version_id']))
            snapshot['parent_version_id'] = str(parent.pk)
            if parent.snapshot.get('brand'):
                snapshot['brand'] = deepcopy(parent.snapshot['brand'])
        version = Version.objects.create(organization_id=channel.organization_id, channel=channel,
            number=channel.versions.count() + 1, body=body, snapshot=snapshot)
        channel.revision += 1
        channel.save(update_fields=['revision', 'updated_at'])
        return Response(version_data(version), status=201)


class ConfirmVersion(Access):
    @transaction.atomic
    def post(self, request, record_id, version_id, **kwargs):
        self.lock()
        channel = self.linked(Channel, record_id)
        if request.data.get('revision') != channel.revision:
            raise Conflict()
        if channel.status == 'published' or channel.archived:
            raise ValidationError('已发布或归档的记录不能更换发布版本。')
        version = get_object_or_404(channel.versions, pk=version_id)
        if channel.topic.status != 'confirmed' or channel.topic.archived:
            raise ValidationError('请先确认有效素材和选题。')
        require_confirmed(topic_materials(channel.topic))
        if not sources_current(channel.topic, version.snapshot):
            raise Conflict('素材已修改，请核对资料并保存新版本后确认。')
        if version.snapshot.get('topic', {}).get('revision') != channel.topic.revision:
            raise Conflict('选题已修改，请核对并保存新版本后确认。')
        channel.confirmed_version = version
        channel.status = 'ready'
        channel.revision += 1
        channel.save()
        return Response(basic(channel))


def report(scope):
    channels = list(scope(Channel).filter(status='published', archived=False).select_related('topic__case'))
    feedback = list(scope(Feedback).filter(archived=False))
    groups = {'platforms': {}, 'cases': {}}
    publications = []
    for channel in channels:
        observations = sorted([f for f in feedback if f.channel_id == channel.pk],
                              key=lambda f: (f.data['observed_on'], f.created_at), reverse=True)
        latest = observations[0] if observations else None
        metrics = {key: latest.data.get(key) if latest else None for key in ('views', 'interactions', 'inquiries')}
        materials = snapshot_materials(channel.confirmed_version.snapshot) if channel.confirmed_version_id else []
        if not materials:
            materials = [basic(m) for m in topic_materials(channel.topic)]
        publications.append(dict(id=str(channel.pk), title=channel.title, platform=channel.platform,
            case_id=materials[0]['id'], case_ids=[m['id'] for m in materials], metrics=metrics, observed_on=latest.data['observed_on'] if latest else None))
        for dimension, key, label in [('platforms', channel.platform, channel.platform),
                                      *[('cases', m['id'], m['title']) for m in materials]]:
            group = groups[dimension].setdefault(key, dict(key=key, label=label, publications=0,
                 metrics={name: dict(total=None, samples=0) for name in metrics}))
            group['publications'] += 1
            for name, number in metrics.items():
                if number is not None:
                    metric = group['metrics'][name]
                    metric['total'] = (metric['total'] or 0) + number
                    metric['samples'] += 1
    return dict(publications=publications, groups={key: list(value.values()) for key, value in groups.items()},
        questions=[dict(id=str(f.pk), channel_id=str(f.channel_id) if f.channel_id else None,
                        questions=f.data['questions']) for f in feedback if f.data['questions']],
        unknown_source_count=sum(f.channel_id is None for f in feedback),
        note='每条已发布内容采用观察日期最新的一次累计数据；空值不计入合计。多素材作品分别计入关联素材，素材组之间不可相加，不代表单份素材的贡献。样本数随指标不同，不跨渠道比较播放与阅读。私信数量为手动登记，未去重；未知来源不归因。')


class Report(Access):
    def get(self, request, **kwargs):
        return Response(report(self.scope))


class Download(Access):
    def get(self, request, record_id, version_id, **kwargs):
        channel = self.linked(Channel, record_id)
        version = get_object_or_404(channel.versions, pk=version_id)
        body = version.body
        html = request.query_params.get('format') == 'html'
        if html and not body.get('formatted_html'):
            raise ValidationError('此版本尚未回存排版 HTML。')
        content = body['formatted_html'] if html else '\n\n'.join(
            f'## {label}\n{body.get(key, "")}' for key, label in [('title', '标题'), ('cover', '封面文字'),
                ('body', '正文'), ('pages', '逐页文案'), ('script', '演示脚本'), ('materials', '素材清单'), ('shots', '拍摄清单'), ('checks', '待核实')])
        response = HttpResponse(content, content_type='application/octet-stream' if html else 'text/markdown; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="promotion-{version.pk}.{"html" if html else "md"}"'
        response['X-Content-Type-Options'] = 'nosniff'
        response['Cache-Control'] = 'private, no-store'
        return response
