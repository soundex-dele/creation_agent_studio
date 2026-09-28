"""Private preset CRUD and deterministic parameter layering."""
from copy import deepcopy

from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.enterprise.permissions import resolve_organization
from core.resource_access import can_access_resource
from modules.catalog.guided_prompts import compose_guided_prompt
from modules.catalog.preset_values import validate_preset_values
from .models import PersonalFormPreset


def find_prompt(definition, identifier=None):
    identifier = identifier or definition.get('default_config', {}).get('guided_entry_prompt_key')
    prompts = definition.get('guided_prompts', [])
    prompt = next((p for p in prompts if str(p.get('id') or p['key']) == str(identifier) or p['key'] == identifier), None)
    if prompt is None and not identifier and prompts:
        prompt = prompts[0]
    if prompt is None:
        raise ValidationError({'prompt_id': '引导表单不存在。'})
    return prompt


def check_values(prompt, values):
    try:
        return validate_preset_values(prompt, values)
    except ValueError as exc:
        raise ValidationError({'values': str(exc)}) from exc


def private_presets(request, application):
    organization = resolve_organization(request)
    if organization is None or (application.organization_id and application.organization_id != organization.id):
        raise ValidationError({'organization': '请选择应用所属组织。'})
    if not can_access_resource(application, request.user, operation='run'):
        raise PermissionDenied('无权运行此应用。')
    return PersonalFormPreset.objects.filter(organization=organization, owner=request.user, application=application)


class PersonalPresetSerializer(serializers.ModelSerializer):
    class Meta:
        model = PersonalFormPreset
        fields = ['id', 'prompt_key', 'name', 'description', 'values', 'updated_at']
        read_only_fields = ['id', 'updated_at']

    def validate(self, attrs):
        from .serializers import application_definition
        prompt = find_prompt(application_definition(self.context['application']), attrs.get('prompt_key', getattr(self.instance, 'prompt_key', None)))
        check_values(prompt, attrs.get('values', getattr(self.instance, 'values', {})))
        attrs['prompt_key'] = prompt['key']
        return attrs


class PresetReferenceSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=['builtin', 'personal'])
    id = serializers.CharField(max_length=100)


def resolve_preset(request, application, prompt, reference):
    serializer = PresetReferenceSerializer(data=reference)
    serializer.is_valid(raise_exception=True)
    reference = serializer.validated_data
    if reference['kind'] == 'builtin':
        preset = next((p for p in prompt.get('presets', []) if p['id'] == reference['id']), None)
        if preset is None:
            raise ValidationError({'preset': '内置模板不存在。'})
        name, values = preset['name'], preset['values']
    else:
        identifier = serializers.UUIDField().run_validation(reference['id'])
        preset = get_object_or_404(private_presets(request, application), pk=identifier, prompt_key=prompt['key'])
        name, values = preset.name, preset.values
    check_values(prompt, values)
    return {**reference, 'name': name, 'prompt_key': prompt['key'], 'values': deepcopy(values)}


def compose_effective(*, prompt, answers, application_id, preset=None, brand=None, explicit_fields=None):
    values = (preset or {}).get('values', {})
    if preset:
        if preset.get('prompt_key') != prompt['key']:
            raise ValidationError({'preset': '模板与当前表单不匹配。'})
        check_values(prompt, values)
    explicit = set(answers if explicit_fields is None else explicit_fields)
    effective = {q['key']: q.get('default_value') for q in prompt.get('questions', [])}
    # Startup-schema defaults are also defaults, not user overrides. Keep them
    # for fields absent from the preset (for example a default source topic).
    effective.update({k: v for k, v in answers.items() if k not in explicit})
    effective.update(values)
    effective.update({k: v for k, v in answers.items() if k in explicit})
    sources = {q['key']: ('manual' if q['key'] in explicit else 'template' if q['key'] in values else 'default') for q in prompt.get('questions', [])}
    if brand:
        from app_center.brand_library.backend.context import compose_with_brand_snapshot
        result = compose_with_brand_snapshot(prompt=prompt, answers=effective, snapshot=brand, explicit_fields=explicit, application_id=application_id)
        for key in result['brand_reference']['inherited_fields']:
            sources[key] = 'brand'
            effective[key] = brand['fields'][key]
    else:
        result = compose_guided_prompt(prompt, effective, application_id=application_id)
    result.update(effective_answers=effective, field_sources=sources)
    return result
