from pathlib import Path

import pytest
import yaml
from django.contrib.auth import get_user_model
from django.core.management import call_command
from rest_framework.exceptions import ValidationError

from apps.agents.models import Agent
from apps.applications.models import Application
from app_center.chat_skill_app import provision_content_creation_agent
from app_center.project_promotion.backend.integrations import ExplorationInput
from modules.catalog.guided_prompts import compose_guided_prompt
from modules.catalog.models import AgentDraft


def definition():
    return yaml.safe_load(Path(__file__).with_name('application.yaml').read_text(encoding='utf-8'))['spec']['definition']


def test_optional_ranges_and_required_source():
    prompt = definition()['guided_prompts'][0]
    with pytest.raises(ValidationError):
        compose_guided_prompt(prompt, {}, application_id=1)
    result = compose_guided_prompt(prompt, {'source': '不知道该讲什么'}, application_id=1)
    assert result['normalized_answers'] == dict(source='不知道该讲什么', platform='', content_type='', goal='', direction='', audience='', requirements='')
    assert '1—3' in result['prompt']
    assert '智能体AI工坊' not in result['prompt']


@pytest.mark.parametrize('field', ['platform', 'content_type', 'goal'])
def test_every_choice_composes_and_matches_handoff_contract(field):
    prompt = definition()['guided_prompts'][0]
    question = next(q for q in prompt['questions'] if q['key'] == field)
    for option in question['options']:
        assert ExplorationInput().fields[field].run_validation(option['value']) == option['value']
        result = compose_guided_prompt(prompt, {'source': '素材', field: option['value']}, application_id=1)
        assert result['normalized_answers'][field] == option['label']
    assert compose_guided_prompt(prompt, {'source': '素材', field: ''}, application_id=1)['normalized_answers'][field] == ''


def test_platform_and_format_are_independent():
    result = compose_guided_prompt(definition()['guided_prompts'][0],
        dict(source='操作素材', platform='wechat', content_type='demo', goal='trust'), application_id=1)
    assert '发布平台：公众号' in result['prompt']
    assert '内容形式：操作演示' in result['prompt']
    assert '本次主要目标：建立专业信任' in result['prompt']


@pytest.mark.django_db
def test_install_is_idempotent_and_uses_a_separate_agent():
    user = get_user_model().objects.create_user(username='topic-explorer-owner')
    org = user.owned_organizations.get()
    shared = provision_content_creation_agent(org)
    previous = AgentDraft.objects.get(agent=shared).content
    call_command('sync_app_center', package_id='topic-explorer', organization_id=str(org.pk))
    application = Application.objects.get(organization=org, slug='topic-explorer')
    agent = Agent.objects.get(organization=org, slug='topic-explorer-assistant')
    version = AgentDraft.objects.get(agent=agent).version
    call_command('sync_app_center', package_id='topic-explorer', organization_id=str(org.pk))
    assert application.revisions.count() == application.deployments.count() == 1
    assert application.chat_application is not None
    assert application.draft.content['agent_bindings'][0]['agent_id'] == agent.pk
    assert application.draft.content['skill_bindings'] == []
    assert 'request_user_input' in AgentDraft.objects.get(agent=agent).content['system_prompt']
    assert 'request_user_input' in application.draft.content['guided_prompts'][0]['prompt_template']
    assert AgentDraft.objects.get(agent=agent).version == version
    assert AgentDraft.objects.get(agent=shared).content == previous
    assert agent.pk != shared.pk
