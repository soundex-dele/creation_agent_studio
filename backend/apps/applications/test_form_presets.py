from copy import deepcopy
from pathlib import Path

import pytest
import yaml
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from apps.agents.models import Agent, AgentCategory
from apps.enterprise.models import Membership
from apps.applications.models import Application, ApplicationCategory, PersonalFormPreset
from app_center.brand_library.backend.models import BrandProfile
from modules.catalog.models import ApplicationDraft, AgentDraft
from modules.catalog.definition import GuidedPromptDefinition
from modules.catalog.preset_values import validate_preset_values
from modules.execution.models import Run
from modules.execution.runtime.builtin import _render_step_message


@pytest.fixture
def form_ctx(db):
    owner = get_user_model().objects.create_user(username='preset-owner')
    other = get_user_model().objects.create_user(username='preset-other')
    org = owner.owned_organizations.get()
    Membership.objects.create(organization=org, user=other, role='developer')
    category = ApplicationCategory.objects.create(name='Templates', slug='templates')
    agent = Agent.objects.create(category=AgentCategory.objects.create(name='Writers', slug='writers'),
        name='Writer', slug='writer', created_by=owner, organization=org)
    AgentDraft.objects.create(organization=org, agent=agent, updated_by=owner, content={
        'system_prompt': 'Write', 'model_config': {}, 'tool_config': [], 'knowledge_config': [],
        'guardrail_config': {}, 'workflow_config': {}, 'skill_bindings': [],
    })
    app = Application.objects.create(organization=org, category=category, name='Write', slug='preset-writer',
        kind='chat', created_by=owner, visibility='organization')
    library = Application.objects.create(organization=org, category=category, name='Library', slug='brand-library',
        kind='custom', created_by=owner, visibility='organization')
    prompt = {'key': 'write', 'title': 'Write', 'prompt_template': '{source}\n{tone}\n{audience}\n{count}', 'questions': [
        {'key': 'source', 'label': '主题', 'type': 'text', 'required': True, 'preset_save': 'optional'},
        {'key': 'tone', 'label': '语气', 'type': 'single_choice', 'default_value': 'normal', 'options': [
            {'value': 'normal', 'label': '普通'}, {'value': 'warm', 'label': '温暖'}]},
        {'key': 'audience', 'label': '受众', 'type': 'text', 'default_value': '默认读者'},
        {'key': 'count', 'label': '数量', 'type': 'number', 'default_value': 3},
        {'key': 'file_path', 'label': '文件', 'type': 'text', 'preset_save': 'never'},
    ], 'presets': [{'id': 'warm', 'name': '温暖模板', 'values': {'tone': 'warm', 'audience': '模板读者'}}]}
    definition = {'kind': 'chat', 'executor_kind': 'agent', 'executor_key': 'agent-chat', 'renderer_key': 'chat',
        'agent_bindings': [{'agent_id': agent.id, 'is_default': True}], 'skill_bindings': [],
        'default_config': {'guided_entry_prompt_key': 'write', 'brand_reference': {
            'enabled': True, 'default_modules': ['voice', 'positioning'], 'fields': {'tone': 'voice.keywords', 'audience': 'positioning.audience'}}},
        'guided_prompts': [prompt]}
    draft = ApplicationDraft.objects.create(organization=org, application=app, updated_by=owner, content=definition)
    brand = BrandProfile.objects.create(organization=org, owner=owner, application=library, name='品牌', voice={'keywords': '克制'})
    reference = {'profile_id': str(brand.id), 'modules': ['voice', 'positioning'], 'product_ids': [], 'example_ids': []}
    client = APIClient(); client.force_authenticate(owner); client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return dict(owner=owner, other=other, org=org, app=app, client=client, prompt=prompt, draft=draft, brand=brand, reference=reference,
                base=f'/api/v1/apps/{app.slug}/')


def create_personal(c):
    response = c['client'].post(c['base'] + 'form-presets/', {'prompt_key': 'write', 'name': '我的模板', 'values': {'audience': '私人读者', 'tone': 'warm'}}, format='json')
    assert response.status_code == 201, response.data
    return response.data


def create_workflow(c, preset=None, mode='automatic', node_count=1):
    response = c['client'].post('/api/v1/workflows/', {'name': 'Template flow', 'execution_mode': mode, 'steps': [
        {'key': f'node{i}', 'order': i, 'application_id': c['app'].id, 'depends_on': [],
         'config': {'form_preset': preset} if preset else {}} for i in range(node_count)]}, format='json')
    assert response.status_code == 201, response.data
    return response.data


def test_private_crud_scope_and_validation(form_ctx):
    c = form_ctx; saved = create_personal(c); url = c['base'] + f"form-presets/{saved['id']}/"
    assert c['client'].get(c['base'] + 'form-presets/').data[0]['id'] == saved['id']
    for values in ({'missing': 'x'}, {'tone': 'bad'}, {'count': '2'}, {'count': True}, {'file_path': '/tmp/private'}):
        response = c['client'].patch(url, {'values': values}, format='json')
        assert response.status_code == 400, response.data
    assert c['client'].patch(url, {'values': {'source': '可复用的主题'}, 'name': '修改'}, format='json').status_code == 200
    c['client'].force_authenticate(c['other'])
    assert c['client'].get(c['base'] + 'form-presets/').data == []
    assert c['client'].patch(url, {'name': '越权'}, format='json').status_code == 404
    assert c['client'].delete(url).status_code == 404
    c['client'].force_authenticate(c['owner'])
    c['client'].credentials(HTTP_X_ORGANIZATION_ID=str(c['other'].owned_organizations.get().id))
    assert c['client'].get(c['base'] + 'form-presets/').status_code in (400, 403, 404)
    c['client'].credentials(HTTP_X_ORGANIZATION_ID=str(c['org'].id))
    assert c['client'].delete(url).status_code == 204


def test_four_layers_and_explicit_clear(form_ctx):
    c = form_ctx
    payload = {'prompt_id': 'write', 'answers': {'source': '主题', 'tone': 'normal'}, 'explicit_fields': ['source'],
        'preset': {'kind': 'builtin', 'id': 'warm'}, 'brand_reference': c['reference']}
    response = c['client'].post(c['base'] + 'compose-prompt/', payload, format='json')
    assert response.status_code == 200, response.data
    assert response.data['effective_answers']['tone'] == '使用品牌资料：克制'
    assert response.data['effective_answers']['audience'] == '模板读者'
    assert response.data['field_sources'] == {'source': 'manual', 'tone': 'brand', 'audience': 'template', 'count': 'default', 'file_path': 'default'}
    payload['explicit_fields'].append('tone')
    assert c['client'].post(c['base'] + 'compose-prompt/', payload, format='json').data['normalized_answers']['tone'] == '普通'
    payload['answers']['source'] = ''
    assert c['client'].post(c['base'] + 'compose-prompt/', payload, format='json').status_code == 400
    payload['answers']['source'] = '恢复'
    payload.pop('brand_reference'); payload['explicit_fields'] = ['source']
    assert c['client'].post(c['base'] + 'compose-prompt/', payload, format='json').data['normalized_answers']['tone'] == '温暖'


def test_workflow_keeps_personal_snapshot_after_edit_and_delete(form_ctx):
    c = form_ctx; saved = create_personal(c)
    flow = create_workflow(c, {'kind': 'personal', 'id': saved['id'], 'values': {'audience': '伪造'}})
    snapshot = flow['steps'][0]['config']['form_preset']
    assert snapshot['values']['audience'] == '私人读者'
    PersonalFormPreset.objects.filter(pk=saved['id']).delete()
    steps = [{'key': 'node0', 'order': 0, 'application_id': c['app'].id, 'config': {'form_preset': snapshot}}]
    response = c['client'].patch(f"/api/v1/workflows/{flow['id']}/", {'steps': steps}, format='json')
    assert response.status_code == 200, response.data
    c['draft'].content['guided_prompts'][0]['questions'] = [q for q in c['prompt']['questions'] if q['key'] != 'audience']
    c['draft'].save()
    assert c['client'].patch(f"/api/v1/workflows/{flow['id']}/", {'steps': steps}, format='json').status_code == 400


def test_automatic_brand_freeze_override_and_input_sources(form_ctx):
    c = form_ctx; flow = create_workflow(c, {'kind': 'builtin', 'id': 'warm'}, node_count=3)
    second = BrandProfile.objects.create(organization=c['org'], owner=c['owner'], application=c['brand'].application,
        name='另一个', voice={'keywords': '直接'})
    payload = {'input': {'source': '主题', 'tone': 'normal'}, 'explicit_input_fields': ['source'], 'brand_context': {
        'reference': c['reference'], 'nodes': {'node1': {'mode': 'disabled'}, 'node2': {'mode': 'override', 'reference': {**c['reference'], 'profile_id': str(second.id)}}}}}
    response = c['client'].post(f"/api/v1/workflows/{flow['id']}/start/", payload, format='json', HTTP_IDEMPOTENCY_KEY='preset-start')
    assert response.status_code == 202, response.data
    run = Run.objects.get(pk=response.data['id']); steps = run.definition_snapshot['workflow_steps']
    c['brand'].delete(); second.delete()
    inherited = _render_step_message(steps[0], run.input, {})
    assert '参见下方品牌资料「品牌语气 → 风格关键词」' in inherited
    assert inherited.count('克制') == 1
    assert '温暖' in _render_step_message(steps[1], run.input, {})
    overridden = _render_step_message(steps[2], run.input, {})
    assert '参见下方品牌资料「品牌语气 → 风格关键词」' in overridden
    assert overridden.count('直接') == 1
    steps[0]['effective_config']['brand_snapshot'].pop('field_references')
    legacy = _render_step_message(steps[0], run.input, {})
    assert '参见下方品牌资料' in legacy
    assert legacy.count('克制') == 1
    from rest_framework.exceptions import ValidationError
    with pytest.raises(ValidationError):
        _render_step_message(steps[0], {**run.input, 'source': ''}, {'upstream': {'output': {'result': '不能代替明确清空'}}})
    steps[0]['effective_config']['automation'] = {'answers': {'tone': {'value': 'normal'}}}
    assert '\n普通\n' in _render_step_message(steps[0], run.input, {})
    steps[0]['input_mapping'] = {'source': {'value': '映射的素材'}}
    assert _render_step_message(steps[0], run.input, {}).startswith('映射的素材\n')
    invalid = c['client'].post(f"/api/v1/workflows/{flow['id']}/start/", payload, format='json', HTTP_IDEMPOTENCY_KEY='brand-gone')
    assert invalid.status_code == 404
    run.status = Run.Status.FAILED; run.save(update_fields=['status'])
    retry = c['client'].post(f"/api/v1/workflows/{flow['id']}/retry-step/", {'run_id': str(run.id), 'step_key': 'node0'},
        format='json', HTTP_IDEMPOTENCY_KEY='preset-retry')
    assert retry.status_code == 202, retry.data
    retried = Run.objects.get(pk=retry.data['id'])
    retried_prompt = _render_step_message(retried.definition_snapshot['workflow_steps'][0], retried.input, {})
    assert '参见下方品牌资料「品牌语气 → 风格关键词」' in retried_prompt
    assert retried_prompt.count('克制') == 1


def test_manual_context_matches_preview_and_survives_brand_deletion(form_ctx):
    c = form_ctx; flow = create_workflow(c, {'kind': 'builtin', 'id': 'warm'}, mode='manual')
    started = c['client'].post(f"/api/v1/workflows/{flow['id']}/manual-session/", {'action': 'open', 'brand_context': {'reference': c['reference']}}, format='json')
    assert started.status_code == 201, started.data
    run_id = started.data['id']; context = {'run_id': run_id, 'step_key': 'node0'}
    frozen = c['client'].get(c['base'] + 'workflow-form-context/', context)
    assert frozen.status_code == 200, frozen.data
    preview = c['client'].post(c['base'] + 'compose-prompt/', {'prompt_id': 'write', 'answers': {'source': '主题'},
        'explicit_fields': ['source'], 'preset': {'kind': 'builtin', 'id': 'warm'}, 'brand_reference': c['reference']}, format='json')
    c['brand'].delete()
    restored = c['client'].post(c['base'] + 'compose-prompt/', {'prompt_id': 'write', 'answers': {'source': '主题'},
        'explicit_fields': ['source'], 'workflow_context': context}, format='json')
    assert restored.status_code == 200, restored.data
    assert restored.data['prompt'] == preview.data['prompt']
    c['client'].force_authenticate(c['other'])
    assert c['client'].get(c['base'] + 'workflow-form-context/', context).status_code == 404


def test_all_bundled_presets_have_valid_partial_values():
    root = Path(__file__).resolve().parents[2] / 'app_center'
    total = 0
    for file in root.glob('*/application.yaml'):
        definition = yaml.safe_load(file.read_text())['spec']['definition']
        for prompt in definition.get('guided_prompts', []):
            GuidedPromptDefinition.model_validate(prompt)
            for preset in prompt.get('presets', []):
                validate_preset_values(prompt, preset['values']); total += 1
                assert not {'source', 'article', 'html_path', 'output_directory'} & set(preset['values'])
    assert total == 22


def test_presets_reject_duplicate_ids_and_unknown_fields(form_ctx):
    prompt = deepcopy(form_ctx['prompt']); prompt['presets'] *= 2
    with pytest.raises(ValueError, match='unique'):
        GuidedPromptDefinition.model_validate(prompt)
    prompt = deepcopy(form_ctx['prompt']); prompt['presets'][0]['values'] = {'unknown': 'x'}
    with pytest.raises(ValueError, match='unknown'):
        GuidedPromptDefinition.model_validate(prompt)


def test_startup_defaults_remain_available_below_template_values():
    from apps.applications.form_presets import compose_effective
    prompt = {'key': 'write', 'prompt_template': '{source} / {tone}', 'questions': [
        {'key': 'source', 'label': '主题', 'type': 'text', 'required': True},
        {'key': 'tone', 'label': '语气', 'type': 'text', 'default_value': '应用默认'},
    ]}
    result = compose_effective(prompt=prompt, application_id=1, answers={'source': '启动表单默认主题', 'tone': '启动默认'},
        explicit_fields=[], preset={'prompt_key': 'write', 'values': {'tone': '模板语气'}})
    assert result['prompt'] == '启动表单默认主题 / 模板语气'
    assert result['field_sources'] == {'source': 'default', 'tone': 'template'}
