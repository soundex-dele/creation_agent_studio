import json
from copy import deepcopy
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers as s
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.applications.models import Application
from apps.enterprise.models import Membership
from core.resource_access import accessible_resources
from modules.tenancy.permissions import HasPathOrganizationRole
from .models import RESOURCES, Preferences, ContentVersion, MetricObservation, Publication, Lead, Property, Content, FollowUp
from .schemas import SCHEMAS, STATUSES, SettingsData, CopyBody, MetricData, validated
from .domain import basic, version_data, property_gaps, snapshot_properties, snapshot_changes, match_properties, calendar, report, date_range


class Conflict(APIException):
    status_code = 409
    default_detail = '资料已被更新，请重新加载后保存。'


class Access(APIView):
    permission_classes = [HasPathOrganizationRole]
    minimum_role = Membership.Role.VIEWER

    def application(self):
        if not hasattr(self, '_application'):
            self._application = get_object_or_404(accessible_resources(
                Application.objects.for_organization(self.kwargs['organization_id']).filter(
                    is_active=True, slug='rental-growth-assistant', kind=Application.Kind.CUSTOM),
                self.request.user, operation='run'), pk=self.kwargs['application_id'])
        return self._application

    def scope(self, model):
        return model.objects.for_organization(self.kwargs['organization_id']).filter(application=self.application(), owner=self.request.user)

    def ownership(self):
        return dict(organization_id=self.kwargs['organization_id'], application=self.application(), owner=self.request.user)

    def prefs(self, lock=False):
        obj, _ = Preferences.objects.get_or_create(**self.ownership(), defaults={'data': validated(SettingsData, {})})
        if lock:
            obj = self.scope(Preferences).select_for_update().get(pk=obj.pk)
        return obj

    def linked(self, resource, identifier):
        try:
            identifier = s.UUIDField().run_validation(identifier)
        except s.ValidationError:
            raise ValidationError('关联记录 ID 格式错误。')
        return get_object_or_404(self.scope(RESOURCES[resource]), pk=identifier)

    def version(self, identifier):
        try:
            identifier = s.UUIDField().run_validation(identifier)
        except s.ValidationError:
            raise ValidationError('文案版本 ID 格式错误。')
        return get_object_or_404(ContentVersion.objects.filter(content__in=self.scope(Content)), pk=identifier)

    def refs(self, kind, data, status):
        for identifier in data.get('property_ids', []):
            self.linked('properties', identifier)
        if data.get('persona_id'):
            self.linked('personas', data['persona_id'])
        if data.get('source_id'):
            source = self.linked('publications', data['source_id'])
            if source.status != 'published':
                raise ValidationError('客户来源需要关联已发布作品。')
        if data.get('deal_property_id'):
            self.linked('properties', data['deal_property_id'])
        if kind == 'leads':
            if bool(data.get('deal_date')) != bool(data.get('deal_property_id')):
                raise ValidationError('成交日期和成交房源需要一起填写。')
            if data.get('deal_date') and data['deal_date'] < data['consulted_on']:
                raise ValidationError('成交日期不能早于首次咨询。')
            if status == 'won' and not data.get('deal_date'):
                raise ValidationError('请填写成交日期和成交房源。')
        if kind == 'followups' and data.get('next_due_date') and data['next_due_date'] < data['due_date']:
            raise ValidationError('下次跟进不能早于本次跟进日期。')
        if kind == 'publications':
            if status == 'planned' and not data.get('scheduled_date'):
                raise ValidationError('待发布作品需要计划日期。')
            if status == 'published' and not data.get('published_at'):
                raise ValidationError('请登记实际发布时间。')

    def serialized(self, resource, record):
        result = basic(record)
        if resource == 'leads':
            contact = record.data.get('contact', '').strip()
            result['duplicates'] = [dict(id=str(r.pk), title=r.title) for r in self.scope(Lead).exclude(pk=record.pk)
                                    if contact and r.data.get('contact', '').strip() == contact]
        if resource in ('contents', 'publications'):
            version = record.versions.first() if resource == 'contents' else record.version
            result['latest_version'] = version_data(version) if version else None
            properties = {str(p.pk): p for p in self.scope(Property)}
            result['changes'] = snapshot_changes(version.snapshot, properties) if version else []
        return result


class Records(Access):
    def model(self):
        kind = self.kwargs['resource']
        if kind not in RESOURCES:
            from django.http import Http404
            raise Http404
        return kind, RESOURCES[kind]

    def get(self, request, record_id=None, **kwargs):
        kind, model = self.model()
        if record_id:
            return Response(self.serialized(kind, get_object_or_404(self.scope(model), pk=record_id)))
        query = self.scope(model)
        if request.query_params.get('archived') != 'all':
            query = query.filter(archived=request.query_params.get('archived') == 'true')
        if request.query_params.get('search'):
            query = query.filter(title__icontains=request.query_params['search'][:200])
        if request.query_params.get('status'):
            query = query.filter(status=request.query_params['status'])
        if kind in ('followups', 'viewings') and request.query_params.get('lead_id'):
            lead = self.linked('leads', request.query_params['lead_id'])
            query = query.filter(lead=lead)
        page = s.IntegerField(min_value=1).run_validation(request.query_params.get('page', 1))
        count = query.count()
        return Response(dict(count=count, next=page + 1 if page * 50 < count else None,
                             results=[self.serialized(kind, r) for r in query[(page - 1) * 50:page * 50]]))

    @transaction.atomic
    def post(self, request, **kwargs):
        self.prefs(lock=True)
        return self.save_record(request.data)

    @transaction.atomic
    def patch(self, request, record_id, **kwargs):
        self.prefs(lock=True)
        _, model = self.model()
        record = get_object_or_404(self.scope(model).select_for_update(), pk=record_id)
        return self.save_record(request.data, record)

    def save_record(self, payload, record=None):
        kind, model = self.model()
        allowed = {'title', 'data', 'status', 'archived', 'revision', 'lead_id', 'version_id', 'mark_property_rented'}
        if not isinstance(payload, dict) or set(payload) - allowed:
            raise ValidationError('请求包含不支持的字段。')
        if record and payload.get('revision') != record.revision:
            raise Conflict()
        previously_done = bool(record and record.status == 'done')
        is_update = record is not None
        title = s.CharField(max_length=200).run_validation(payload.get('title', record.title if record else None))
        status = s.ChoiceField(choices=STATUSES[kind]).run_validation(payload.get('status', record.status if record else STATUSES[kind][0]))
        raw = deepcopy(record.data) if record else {}
        if not isinstance(payload.get('data', {}), dict):
            raise ValidationError('data 必须为对象。')
        raw.update(payload.get('data', {}))
        data = validated(SCHEMAS[kind], raw)
        self.refs(kind, data, status)
        extra = {}
        if kind in ('followups', 'viewings'):
            extra['lead'] = self.linked('leads', payload.get('lead_id', str(record.lead_id) if record else None))
        if kind == 'publications':
            version = self.version(payload.get('version_id', str(record.version_id) if record else None))
            if record and record.status == 'published' and (version.pk != record.version_id or status != 'published'):
                raise ValidationError('已发布记录保留原文案版本和发布状态；如需再次发布，请新增记录。')
            if status == 'published' and (not record or record.status != 'published'):
                props = {str(p.pk): p for p in self.scope(Property)}
                if snapshot_changes(version.snapshot, props):
                    raise ValidationError('房源资料已变化，请核对并保存新的文案版本后登记发布。')
            extra['version'] = version
        archived = s.BooleanField().run_validation(payload.get('archived', record.archived if record else False))
        if record:
            record.title, record.status, record.data, record.archived = title, status, data, archived
            for key, value in extra.items():
                setattr(record, key, value)
            record.revision += 1
            record.save()
        else:
            record = model.objects.create(**self.ownership(), title=title, status=status, data=data, archived=archived, **extra)
        if kind == 'followups' and status == 'done' and not previously_done and data.get('next_due_date'):
            FollowUp.objects.create(**self.ownership(), title=f'{record.lead.title} · 下次跟进'[:200], status='pending', lead=record.lead,
                data=validated(SCHEMAS['followups'], dict(due_date=data['next_due_date'], next_step=data.get('next_step', ''))))
        if kind == 'leads' and payload.get('mark_property_rented'):
            if status != 'won':
                raise ValidationError('仅登记成交时可同步房源状态。')
            prop = self.linked('properties', data['deal_property_id'])
            prop.status = 'rented'; prop.revision += 1; prop.save()
        return Response(self.serialized(kind, record), status=200 if is_update else 201)


class BuiltinPersonas(Access):
    @transaction.atomic
    def put(self, request, **kwargs):
        if request.data:
            raise ValidationError('内置画像初始化无需填写资料。')
        self.prefs(lock=True)
        from .personas import ensure_builtin_personas
        return Response({'created': ensure_builtin_personas(self.ownership())})


class Versions(Access):
    def get(self, request, record_id, **kwargs):
        content = self.linked('contents', record_id)
        return Response([version_data(v) for v in content.versions.all()])

    @transaction.atomic
    def post(self, request, record_id, **kwargs):
        self.prefs(lock=True)
        content = self.linked('contents', record_id)
        if request.data.get('revision') != content.revision:
            raise Conflict()
        body = validated(CopyBody, request.data.get('body'))
        properties = [self.linked('properties', i) for i in content.data.get('property_ids', [])]
        version = ContentVersion.objects.create(organization_id=content.organization_id, content=content,
                    number=content.versions.count() + 1, body=body,
                    snapshot=dict(properties=snapshot_properties(properties), content=deepcopy(content.data)))
        content.revision += 1; content.save()
        return Response(version_data(version), status=201)


class Download(Access):
    def get(self, request, version_id, **kwargs):
        version = self.version(version_id)
        body = version.body
        lines = ['# ' + body['titles'][0], '', body['body'], '', ' '.join(body.get('tags', [])), '', '## 封面', body.get('cover', '')]
        if body.get('script'):
            lines += ['', '## 口播', body['script']]
        lines += ['', '## 实拍图排版与镜头建议']
        lines += [f"{p.get('photo_ref', '建议补拍')}\n{p.get('caption', '')}\n{p.get('layout', '')}" for p in body.get('pages', [])]
        lines += body.get('shots', [])
        lines += ['', '## 待核实信息', *body.get('checks', [])]
        response = HttpResponse('\n\n'.join(lines), content_type='text/markdown; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="rental-copy-v{version.number}.md"'
        return response


class Metrics(Access):
    def get(self, request, record_id, **kwargs):
        pub = self.linked('publications', record_id)
        return Response([dict(id=str(m.pk), data=m.data, created_at=m.created_at.isoformat()) for m in pub.metrics.all()])

    @transaction.atomic
    def post(self, request, record_id, **kwargs):
        self.prefs(lock=True)
        pub = self.linked('publications', record_id)
        if pub.status != 'published':
            raise ValidationError('请先登记发布，再记录效果。')
        item = MetricObservation.objects.create(organization_id=pub.organization_id, publication=pub,
                                                data=validated(MetricData, request.data))
        return Response(dict(id=str(item.pk), data=item.data, created_at=item.created_at.isoformat()), status=201)


class Settings(Access):
    def get(self, request, **kwargs):
        return Response(self.prefs().data)

    @transaction.atomic
    def put(self, request, **kwargs):
        prefs = self.prefs(lock=True)
        prefs.data = validated(SettingsData, request.data); prefs.save()
        return Response(prefs.data)


class Match(Access):
    def get(self, request, record_id, **kwargs):
        return Response(match_properties(self.linked('leads', record_id), self.scope(Property)))


class Overview(Access):
    def get(self, request, section, **kwargs):
        start, end = date_range(request.query_params)
        if section == 'reports':
            return Response(report(self.scope, start, end))
        result = calendar(self.scope, self.prefs().data, start, end)
        if section == 'dashboard':
            result['events'] = [e for e in result['events'] if e['active'] and e['date'] <= result['today']]
            result['attention'] = [dict(**basic(p), gaps=property_gaps(p)) for p in self.scope(Property).filter(archived=False)
                                   if p.status == 'paused' or property_gaps(p)]
            result['property_count'] = self.scope(Property).filter(archived=False).count()
        return Response(result)
