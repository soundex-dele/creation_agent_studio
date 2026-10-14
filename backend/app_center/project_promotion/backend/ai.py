import hashlib
import json
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers as s
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from app_center.brand_library.backend.context import resolve_brand_snapshot
from app_center.brand_library.backend.serializers import BrandReferenceSerializer
from modules.execution.application.start_runs import start_application_run
from modules.execution.application.errors import DeploymentUnavailable, IdempotencyKeyReused, InvalidExecutionDefinition
from .models import AITask, Case, Topic, Channel, Version
from .schemas import Strict, text, validated, CaseData, TopicData, CopyBody
from .views import Access, Conflict, basic, channel_snapshot, report
from apps.applications.runtime_paths import resolve_runtime_path
from pathlib import Path
from modules.execution.application.commands import submit_run_command
from modules.execution.application.errors import CommandNotAllowed

ACTIVE = {'queued', 'running', 'waiting_input', 'waiting_children', 'cancelling'}


class TaskInput(Strict):
    kind = s.ChoiceField(choices=['case', 'project', 'topics', 'copy', 'review'])
    request_key = s.CharField(max_length=160)
    instruction = text(30000)
    project_path = text(2000)
    case_id = s.UUIDField(required=False, allow_null=True, default=None)
    channel_id = s.UUIDField(required=False, allow_null=True, default=None)
    brand_reference = BrandReferenceSerializer(required=False, allow_null=True, default=None)


def task_data(task):
    status = task.status
    if task.run and status in ACTIVE and task.run.status in {'failed', 'cancelled'}:
        status = task.run.status
    return dict(id=str(task.pk), kind=task.kind, status=status, error=task.error or (
        '任务未完成，请检查配置后重试。' if status in {'failed', 'cancelled'} else ''), result=task.result,
        applied=task.applied, request=task.snapshot.get('request', {}), stage=task.data.get('stage', ''), created_at=task.created_at.isoformat(),
        run_id=str(task.run_id) if task.run_id else None, organization_id=str(task.organization_id))


class Tasks(Access):
    def get(self, request, task_id=None, **kwargs):
        query = self.scope(AITask).select_related('run')
        if task_id:
            return Response(task_data(get_object_or_404(query, pk=task_id)))
        page = s.IntegerField(min_value=1).run_validation(request.query_params.get('page', 1))
        count = query.count()
        return Response(dict(count=count, next=page + 1 if page * 50 < count else None,
            results=[task_data(t) for t in query[(page - 1) * 50:page * 50]]))

    @transaction.atomic
    def post(self, request, **kwargs):
        self.lock()
        values = validated(TaskInput, request.data)
        key = values.pop('request_key')
        digest = hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()
        old = self.scope(AITask).filter(request_key=key).select_related('run').first()
        if old:
            if old.request_hash != digest:
                raise Conflict('同一请求键不能提交不同内容。')
            return Response(task_data(old))
        snapshot = dict(request=values)
        if values['kind'] == 'case' and not values['instruction'].strip():
            raise ValidationError('请粘贴开发记录或案例资料。')
        if values['kind'] == 'project':
            try:
                if not Path(values['project_path']).is_absolute():
                    raise ValueError('请填写后端运行机器上的项目绝对路径。')
                path = resolve_runtime_path(values['project_path'], request.user)
                if not path.is_dir():
                    raise ValueError('项目目录不存在或不可读取。')
            except (ValueError, OSError, PermissionError) as exc:
                raise ValidationError({'project_path': str(exc)}) from None
        elif values['project_path']:
            raise ValidationError('只有项目探索任务支持项目路径。')
        if values['kind'] in ('topics', 'review'):
            case = self.linked(Case, values['case_id'])
            if case.status != 'confirmed' or case.archived:
                raise ValidationError('请先选择已确认的案例。')
            snapshot['case'] = basic(case)
        if values['kind'] == 'copy':
            channel = self.linked(Channel, values['channel_id'])
            if channel.archived or channel.topic.archived or channel.topic.case.archived or channel.topic.status != 'confirmed' or channel.topic.case.status != 'confirmed':
                raise ValidationError('请先确认有效案例和选题。')
            snapshot.update(channel_snapshot(channel))
            snapshot['channel_id'] = str(channel.pk)
        if values['kind'] == 'review':
            snapshot['report'] = report(self.scope)
        if values['brand_reference']:
            reference = BrandReferenceSerializer(data=values['brand_reference'])
            reference.is_valid(raise_exception=True)
            snapshot['brand'] = resolve_brand_snapshot(request=request, application=self.application(),
                definition={'default_config': {'brand_reference': {'enabled': True}}}, reference=reference.validated_data)
        if len(json.dumps(snapshot, ensure_ascii=False)) > 180000:
            raise ValidationError('资料过多，请减少素材或复盘记录后重试。')
        task = AITask.objects.create(**self.ownership(), title=values['kind'], status='queued', kind=values['kind'],
                                    request_key=key, request_hash=digest, snapshot=snapshot)
        try:
            run, _ = start_application_run(organization_id=task.organization_id, application_id=task.application_id,
                actor=request.user, input_data={'task_id': str(task.pk)}, priority=0, idempotency_key=f'promotion:{task.pk}')
        except (DeploymentUnavailable, IdempotencyKeyReused, InvalidExecutionDefinition) as exc:
            raise Conflict(str(exc)) from None
        task.run = run
        task.save(update_fields=['run'])
        return Response(task_data(task), status=202)


class TopicResult(Strict):
    title = s.CharField(max_length=200)
    data = TopicData()


class CaseResult(Strict):
    title = s.CharField(max_length=200)
    data = CaseData()


class TopicsResult(Strict):
    topics = TopicResult(many=True, allow_empty=False, max_length=12)
    analysis = text(20000)


def validate_result(task, value):
    result = validated({'case': CaseResult, 'topics': TopicsResult, 'review': TopicsResult, 'copy': CopyBody}[task.kind], value)
    if task.kind == 'case':
        # AI extraction always starts as a demo; the user verifies customer status.
        result['data']['case_type'] = 'demo'
    if task.kind in ('topics', 'review'):
        allowed = {q['id'] for q in task.snapshot.get('report', {}).get('questions', [])}
        for topic in result['topics']:
            if topic['data']['source_feedback_id'] and topic['data']['source_feedback_id'] not in allowed:
                raise ValidationError('引用了不存在的反馈。')
    if task.kind == 'copy':
        platform = task.snapshot['platform']
        if platform == 'xiaohongshu' and not result['pages'].strip():
            raise ValidationError('小红书文案缺少逐页文字。')
        if platform == 'douyin' and (not result['script'].strip() or not result['shots'].strip()):
            raise ValidationError('抖音内容缺少演示脚本或拍摄清单。')
        result['formatted_html'] = ''
    return result


class Apply(Access):
    @transaction.atomic
    def post(self, request, task_id, **kwargs):
        self.lock()
        task = get_object_or_404(self.scope(AITask).select_for_update(), pk=task_id, status='succeeded')
        if task.applied:
            return Response(task_data(task))
        result = task.result
        if task.kind == 'project':
            result['case_ids'] = [str(Case.objects.create(**self.ownership(), title=item['title'], data=item['data'],
                status='draft', source_snapshot=item['source_snapshot']).pk) for item in result['cases']]
        elif task.kind == 'case':
            record = Case.objects.create(**self.ownership(), title=result['title'], data=result['data'], status='draft')
            result['case_id'] = str(record.pk)
        elif task.kind in ('topics', 'review'):
            case = self.linked(Case, task.snapshot['case']['id'])
            if case.archived:
                raise ValidationError('请先恢复案例。')
            result['topic_ids'] = [str(Topic.objects.create(**self.ownership(), case=case, title=t['title'], data=t['data'], status='draft').pk)
                                   for t in result['topics']]
        else:
            channel = self.linked(Channel, task.snapshot['channel_id'])
            if channel.archived:
                raise ValidationError('请先恢复渠道记录。')
            version = Version.objects.create(organization_id=channel.organization_id, channel=channel,
                number=channel.versions.count() + 1, body=result, snapshot=task.snapshot)
            channel.revision += 1
            channel.save(update_fields=['revision', 'updated_at'])
            result = dict(body=result, version_id=str(version.pk), channel_id=str(channel.pk))
        task.result = result
        task.applied = True
        task.save(update_fields=['result', 'applied'])
        return Response(task_data(task))


class Cancel(Access):
    @transaction.atomic
    def post(self, request, task_id, **kwargs):
        task = get_object_or_404(self.scope(AITask).select_for_update(), pk=task_id)
        if task.status in ACTIVE:
            if task.run and task.run.status in ACTIVE:
                try:
                    submit_run_command(run_id=task.run_id, organization_id=task.organization_id, actor=request.user,
                        command_type='cancel', idempotency_key=f'promotion-cancel:{task.pk}')
                except CommandNotAllowed:
                    pass
            task.status = 'cancelled'
            task.save(update_fields=['status'])
        return Response(task_data(task))
