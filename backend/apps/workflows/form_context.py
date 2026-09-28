"""Resolve private references at the run boundary, never inside workers."""
from copy import deepcopy

from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from apps.applications.form_presets import check_values, find_prompt, resolve_preset
from apps.applications.models import Application
from apps.applications.serializers import application_definition
from apps.enterprise.permissions import resolve_organization
from app_center.brand_library.backend.context import resolve_brand_snapshot
from app_center.brand_library.backend.serializers import BrandReferenceSerializer
from core.resource_access import can_access_resource
from modules.execution.models import Run


class NodeBrandSerializer(serializers.Serializer):
    mode = serializers.ChoiceField(choices=['inherit', 'disabled', 'override'])
    reference = BrandReferenceSerializer(required=False)

    def validate(self, attrs):
        if attrs['mode'] == 'override' and not attrs.get('reference'):
            raise serializers.ValidationError('请选择节点品牌资料。')
        return attrs


class WorkflowBrandSerializer(serializers.Serializer):
    reference = BrandReferenceSerializer(required=False, allow_null=True)
    nodes = serializers.DictField(child=NodeBrandSerializer(), required=False, default=dict)


def validate_step_presets(steps, workflow, request):
    previous = {s.key: s for s in workflow.steps.all()} if workflow else {}
    for item in steps:
        config = item.get('config') or {}
        if not isinstance(config, dict):
            raise ValidationError({'config': '节点配置必须为对象。'})
        if any(key in config for key in ('brand_snapshot', 'explicit_input_fields', 'brand_reference')):
            raise ValidationError({'config': '品牌资料只能在本次运行中选择。'})
        preset = config.get('form_preset')
        if not preset:
            continue
        if not isinstance(preset, dict) or not isinstance(config.get('automation') or {}, dict):
            raise ValidationError({'form_preset': '模板及自动输入配置必须为对象。'})
        app = get_object_or_404(Application, pk=item['application_id'])
        prompt = find_prompt(application_definition(app), (config.get('automation') or {}).get('guided_prompt_key'))
        old = previous.get(item['key'])
        if old and old.application_id == app.id and preset == (old.config or {}).get('form_preset'):
            if preset.get('prompt_key') != prompt['key']:
                raise ValidationError({'form_preset': '模板与节点表单不匹配。'})
            check_values(prompt, preset.get('values'))
        else:
            # Do not accept client-authored personal template snapshots.
            config['form_preset'] = resolve_preset(request, app, prompt, preset)


def freeze_form_context(request, snapshots):
    serializer = WorkflowBrandSerializer(data=request.data.get('brand_context') or {})
    serializer.is_valid(raise_exception=True)
    selected = serializer.validated_data
    unknown = set(selected['nodes']) - {s['key'] for s in snapshots}
    if unknown:
        raise ValidationError({'brand_context': '品牌配置包含不存在的节点。'})
    explicit = request.data.get('explicit_input_fields')
    if explicit is not None:
        explicit = serializers.ListField(child=serializers.CharField(max_length=100), max_length=100).run_validation(explicit)
    for step in snapshots:
        definition = step.get('content') or {}
        config = step.setdefault('effective_config', {})
        config.pop('brand_snapshot', None)
        if explicit is not None:
            config['explicit_input_fields'] = explicit
        preset = config.get('form_preset')
        if preset:
            if not isinstance(preset, dict) or not isinstance(config.get('automation') or {}, dict):
                raise ValidationError({'form_preset': '模板及自动输入配置必须为对象。'})
            prompt = find_prompt(definition, (config.get('automation') or {}).get('guided_prompt_key'))
            if preset.get('prompt_key') != prompt['key']:
                raise ValidationError({'form_preset': '模板与节点表单不匹配。'})
            check_values(prompt, preset.get('values'))
        node = selected['nodes'].get(step['key'], {'mode': 'inherit'})
        reference = None if node['mode'] == 'disabled' else node.get('reference') if node['mode'] == 'override' else selected.get('reference')
        if not definition.get('default_config', {}).get('brand_reference', {}).get('enabled'):
            if node['mode'] == 'override':
                raise ValidationError({'brand_context': f"节点 {step['key']} 不支持品牌引用。"})
            continue
        if reference:
            app = get_object_or_404(Application, pk=step['application_id'])
            config['brand_snapshot'] = resolve_brand_snapshot(request=request, application=app, definition=definition, reference=reference)
    return snapshots


def manual_step_context(request, application, data):
    organization = resolve_organization(request)
    run_id = serializers.UUIDField().run_validation(data.get('run_id'))
    run = get_object_or_404(Run.objects.filter(organization=organization, owner=request.user,
        executor_key='workflow-manual', source_type='workflow'), pk=run_id)
    step = next((s for s in run.definition_snapshot.get('workflow_steps', [])
                 if s['key'] == data.get('step_key') and s['application_id'] == application.id), None)
    if step is None or not can_access_resource(application, request.user, operation='run'):
        raise ValidationError({'workflow_context': '运行节点与应用不匹配或不可访问。'})
    config = step.get('effective_config') or {}
    definition = step.get('content') or application_definition(application)
    prompt = find_prompt(definition, (config.get('automation') or {}).get('guided_prompt_key'))
    return deepcopy({'form_preset': config.get('form_preset'), 'brand_snapshot': config.get('brand_snapshot'), 'prompt': prompt})
