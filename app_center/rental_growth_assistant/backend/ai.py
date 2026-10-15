import hashlib
import json
from copy import deepcopy
from datetime import date, timedelta
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers as s
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from modules.execution.application.start_runs import start_application_run
from modules.execution.application.commands import submit_run_command
from modules.execution.application.errors import DeploymentUnavailable, IdempotencyKeyReused, InvalidExecutionDefinition, CommandNotAllowed
from .views import Access, Conflict
from .models import AITask, Content, ContentVersion, Lead, Property, Persona
from .schemas import StrictSerializer, ContentData, Requirements, CopyBody, PLATFORMS, TYPES, ids, text, validated
from .domain import basic, snapshot_properties, property_gaps, report

ACTIVE = {'queued', 'running', 'waiting_input', 'waiting_children', 'cancelling'}
KINDS = ['topics', 'copy', 'extract', 'reply', 'review']


class TaskInput(StrictSerializer):
    kind = s.ChoiceField(choices=KINDS)
    request_key = s.CharField(max_length=160)
    instruction = text(20000)
    property_ids = ids()
    persona_id = s.UUIDField(required=False, allow_null=True, default=None)
    lead_id = s.UUIDField(required=False, allow_null=True, default=None)
    content_id = s.UUIDField(required=False, allow_null=True, default=None)
    platform = s.ChoiceField(choices=PLATFORMS, default='xiaohongshu', required=False)
    content_type = s.ChoiceField(choices=TYPES, default='property', required=False)
    start_date = s.DateField(required=False, allow_null=True, default=None)


def task_data(task):
    status, error = task.status, task.error
    if task.run and status in ACTIVE and task.run.status in {'failed', 'cancelled'}:
        status = task.run.status
        error = error or '任务未完成，可修复配置后重试。'
    return dict(id=str(task.pk), kind=task.kind, status=status, error=error, result=task.result,
                run_id=str(task.run_id) if task.run_id else None, organization_id=str(task.organization_id),
                applied=task.applied, request=task.snapshot.get('request', {}), created_at=task.created_at.isoformat())


class Tasks(Access):
    def get(self, request, task_id=None, **kwargs):
        query = self.scope(AITask).select_related('run')
        if task_id:
            return Response(task_data(get_object_or_404(query, pk=task_id)))
        page = s.IntegerField(min_value=1).run_validation(request.query_params.get('page', 1))
        count = query.count()
        return Response(dict(count=count, next=page + 1 if page * 50 < count else None,
                             results=[task_data(t) for t in query[(page-1)*50:page*50]]))

    @transaction.atomic
    def post(self, request, **kwargs):
        prefs = self.prefs(lock=True)
        values = validated(TaskInput, request.data)
        key = values.pop('request_key')
        digest = hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()
        old = self.scope(AITask).filter(request_key=key).select_related('run').first()
        if old:
            if old.request_hash != digest:
                raise Conflict('同一请求键不能用于不同任务。')
            return Response(task_data(old))
        kind = values['kind']
        properties = [self.linked('properties', identifier) for identifier in values['property_ids']]
        if kind in ('copy', 'topics'):
            if not properties and kind == 'topics':
                properties = list(self.scope(Property).filter(status='available', archived=False))
            if kind == 'copy' and values['content_type'] in ('property', 'comparison'):
                required = 2 if values['content_type'] == 'comparison' else 1
                if len(properties) < required:
                    raise ValidationError(f'本类内容至少选择 {required} 套房源。')
            for prop in properties:
                if prop.archived or prop.status != 'available' or property_gaps(prop):
                    raise ValidationError(f'{prop.title}：请补齐资料并确认房源处于待出租状态。')
        persona = self.linked('personas', values['persona_id']) if values.get('persona_id') else None
        lead = self.linked('leads', values['lead_id']) if values.get('lead_id') else None
        source = self.linked('contents', values['content_id']) if values.get('content_id') else None
        if kind in ('extract', 'reply') and not lead:
            raise ValidationError('请先选择客户。')
        if kind in ('extract', 'reply') and not values['instruction'].strip():
            raise ValidationError('请输入客户咨询原文或问题。')
        snapshot = dict(request=values, properties=snapshot_properties(properties), voice=prefs.data['voice'],
                        timezone=prefs.data['timezone'], persona=basic(persona) if persona else None)
        if lead and kind in ('extract', 'reply'):
            snapshot['lead'] = dict(id=str(lead.pk), revision=lead.revision,
                                    requirements={k: v for k, v in lead.data.items() if k in Requirements().fields})
        if source:
            version = source.versions.first()
            snapshot['source'] = dict(id=str(source.pk), revision=source.revision, title=source.title, metadata=source.data, body=version.body if version else None)
        if kind == 'topics':
            snapshot['history'] = [dict(title=c.title, platform=c.data.get('platform')) for c in self.scope(Content)[:30]]
            if not values.get('start_date'):
                from zoneinfo import ZoneInfo
                from django.utils import timezone
                values['start_date'] = timezone.now().astimezone(ZoneInfo(prefs.data['timezone'])).date().isoformat()
        if kind == 'review':
            snapshot['report'] = report(self.scope)
        task = AITask.objects.create(**self.ownership(), kind=kind, request_key=key, request_hash=digest, snapshot=snapshot)
        try:
            run, _ = start_application_run(organization_id=task.organization_id, application_id=task.application_id,
                actor=request.user, input_data={'task_id': str(task.pk)}, priority=0, idempotency_key=f'rental:{task.pk}')
        except (DeploymentUnavailable, IdempotencyKeyReused, InvalidExecutionDefinition) as exc:
            raise Conflict(str(exc)) from None
        task.run = run; task.save(update_fields=['run'])
        return Response(task_data(task), status=202)


class Cancel(Access):
    @transaction.atomic
    def post(self, request, task_id, **kwargs):
        task = get_object_or_404(self.scope(AITask).select_for_update().select_related('run'), pk=task_id)
        if task_data(task)['status'] in ACTIVE:
            task.cancel_requested = True; task.status = 'cancelled'; task.save()
            if task.run and task.run.status in ACTIVE:
                try:
                    submit_run_command(run_id=task.run_id, organization_id=task.organization_id, actor=request.user,
                                       command_type='cancel', idempotency_key=f'rental-cancel:{task.pk}')
                except CommandNotAllowed:
                    pass
        return Response(task_data(task))


class Apply(Access):
    @transaction.atomic
    def post(self, request, task_id, **kwargs):
        self.prefs(lock=True)
        task = get_object_or_404(self.scope(AITask).select_for_update(), pk=task_id, status='succeeded')
        if task.applied:
            return Response(task_data(task))
        if task.kind != 'topics':
            raise ValidationError('只有七天选题计划支持此操作；客户需求请审核编辑后保存。')
        content_ids = []
        for topic in task.result['topics']:
            data = validated(ContentData, dict(platform=task.snapshot['request']['platform'], content_type=topic['content_type'],
                 property_ids=topic['property_ids'], persona_id=task.snapshot['request'].get('persona_id'),
                 angle=topic['angle'], planned_date=topic['date']))
            content = Content.objects.create(**self.ownership(), title=topic['title'], status='draft', data=data)
            content_ids.append(str(content.pk))
        task.result['content_ids'] = content_ids; task.applied = True; task.save()
        return Response(task_data(task))


def validate_result(task, value):
    if not isinstance(value, dict):
        raise ValidationError('生成结果必须为对象。')
    if task.kind == 'copy':
        body = validated(CopyBody, value)
        if task.snapshot['request']['platform'] != 'moments' and len(body['titles']) != 3:
            raise ValidationError('需要三个候选标题。')
        if task.snapshot['request']['platform'] in ('douyin', 'channels') and (not body['script'] or not body['shots']):
            raise ValidationError('口播与镜头清单不能为空。')
        photos = {f"{prop['id']}:{i+1}" for prop in task.snapshot['properties'] for i, _ in enumerate(prop['data'].get('photos', []))}
        used = [p['photo_ref'] for p in body['pages'] if p['photo_ref']]
        if any(ref not in photos for ref in used) or len(set(used)) != len(used):
            raise ValidationError('排版引用了不存在或重复的照片编号。')
        if task.snapshot['request']['platform'] in ('xiaohongshu', 'moments'):
            if not body['pages'] or (photos and set(used) != photos):
                raise ValidationError('请为清单中的每张照片安排排版；无照片时提供建议拍摄清单。')
        return body
    if task.kind == 'extract':
        # Partial extraction must not erase existing confirmed values.
        if set(value) != {'requirements'} or not isinstance(value['requirements'], dict):
            raise ValidationError('需要返回需求草稿。')
        clean = validated(Requirements, value['requirements'])
        return {'requirements': {k: clean[k] for k in value['requirements'] if clean[k] not in (None, '', [])}}
    if task.kind in ('reply', 'review'):
        answer = s.CharField(max_length=20000).run_validation(value.get('answer'))
        questions = s.ListField(child=s.CharField(max_length=1000), max_length=30).run_validation(value.get('questions', []))
        citations = s.ListField(child=s.CharField(max_length=100), max_length=100).run_validation(value.get('publication_ids', []))
        if task.kind == 'review':
            allowed = {p['id'] for p in task.snapshot['report']['publications']}
            if any(identifier not in allowed for identifier in citations):
                raise ValidationError('复盘引用了不存在的作品。')
        return dict(answer=answer, questions=questions, publication_ids=citations)
    topics = value.get('topics')
    if not isinstance(topics, list) or len(topics) != 7:
        raise ValidationError('需要七天、每天一个选题。')
    properties = {p['id'] for p in task.snapshot['properties']}
    output = []
    for index, topic in enumerate(topics):
        if not isinstance(topic, dict):
            raise ValidationError('选题格式错误。')
        content_type = s.ChoiceField(choices=TYPES).run_validation(topic.get('content_type'))
        refs = [str(s.UUIDField().run_validation(i)) for i in topic.get('property_ids', [])]
        if any(i not in properties for i in refs) or len(refs) != len(set(refs)):
            raise ValidationError('选题引用了无效房源。')
        if content_type in ('property', 'comparison') and len(refs) < (2 if content_type == 'comparison' else 1):
            raise ValidationError('选题缺少关联房源。')
        output.append(dict(title=s.CharField(max_length=200).run_validation(topic.get('title')),
                           angle=s.CharField(max_length=3000).run_validation(topic.get('angle')),
                           content_type=content_type, property_ids=refs,
                           date=(date.fromisoformat(task.snapshot['request']['start_date']) + timedelta(days=index)).isoformat()))
    return {'topics': output}
