from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4
import json

import pytest
from django.core.management import call_command
from rest_framework.exceptions import Throttled
from modules.execution.models import Run
from apps.knowledge.providers import ProviderUnavailable
from app_center.kitchen_assistant import runtime
from .. import ai
from ..models import KitchenAITask, KitchenState
from ..serializers import Recipe, State
from ..views import initial_state, normalize
from .test_api import context, patch_state, sample_record


class Sink:
    cancelled = False
    def emit(self, *args): pass


@pytest.fixture
def ai_context(context, monkeypatch):
    client, url, owner, user, app = context
    snapshot = client.get(url).data
    def start(**kw):
        return Run.objects.create(organization_id=kw['organization_id'], owner=kw['actor'],
            source_type='application', source_id=str(kw['application_id']), executor_kind='media', executor_key='kitchen-assistant', input=kw['input_data']), False
    monkeypatch.setattr(ai, 'start_application_run', start)
    return context, snapshot


def create_task(ctx, kind='question', key=None, **extra):
    context, snapshot = ctx
    client, url, *_ = context
    response = client.post(url.replace('/state', '/ai/tasks'), dict(kind=kind, instruction='请给出烹饪建议', revision=snapshot['revision'], requestKey=key or str(uuid4()), **extra), format='json')
    assert response.status_code in (200, 202), response.data
    return KitchenAITask.objects.select_related('state__owner', 'state__organization', 'run').get(pk=response.data['id'])


def execute(task):
    return runtime.execute(dict(run_id=str(task.run_id), organization_id=str(task.organization_id), input={'task_id': str(task.pk)}), Sink())


def test_catalog_count_categories_and_validation(context):
    client, url, *_ = context
    response = client.get(url.replace('/state','/catalog'))
    assert response.status_code == 200 and len(response.data) == 30
    assert len({r['catalogId'] for r in response.data}) == 30
    for category, count in [('早餐',6),('荤菜',8),('蔬菜',6),('汤类',4),('主食',6)]:
        assert sum(r['category']==category for r in response.data)==count
    for recipe in response.data:
        validator = Recipe(data=recipe)
        assert validator.is_valid(), validator.errors
    assert len(client.get(url).data['data']['recipes'])==3


def test_v1_read_upgrade_retains_dates_timers_and_history(context):
    client, url, _, user, app = context
    client.get(url)
    state=KitchenState.objects.get(owner=user, application=app)
    state.data.pop('schemaVersion'); state.data.pop('preferences')
    state.data['servings']=4
    state.data['weeklyMenu']=[dict(date='2026-10-01', lunch=['r1'], dinner=['r2'])]
    state.data['selectedRecipeIds']=['r1']
    state.data['cooking']=dict(startedAt='2026-09-27T00:00:00Z',recipeIds=['r1'],currentId='r1',steps={'r1':0},completedIds=[],timers={'r1':1790467260000})
    state.save()
    loaded=client.get(url).data['data']
    assert loaded['schemaVersion']==2
    assert loaded['weeklyMenu'][0]['breakfast']==[]
    assert loaded['weeklyMenu'][0]['settings']['lunch']['servings']==4
    assert loaded['cooking']['timers']['r1']==1790467260000
    assert loaded['cooking']['recipeSnapshots'][0]['name']=='番茄炒蛋'
    validator=State(data=loaded);assert validator.is_valid(),validator.errors
    response=client.patch(url,dict(revision=0,operationId=str(uuid4()),changes={'weeklyMenu':[]}),format='json')
    assert response.status_code==409 and response.data['code']=='schema_upgrade_required'
    assert client.get(url).data['data']['weeklyMenu']==loaded['weeklyMenu']


def test_multi_timer_roundtrip_and_invalid_reference(context):
    client,url,*_=context
    data=client.get(url).data['data'];r=data['recipes'][0]
    cooking=dict(startedAt='2026-09-27T00:00:00Z',recipeIds=[r['id']],currentId=r['id'],steps={r['id']:1},completedIds=[],timers={'t1':1790467260000,'t2':1790467300000},pausedTimers={},timerMeta={'t1':dict(recipeId=r['id'],stepId=r['steps'][0]['id']),'t2':dict(recipeId=r['id'],stepId=r['steps'][1]['id'])},recipeSnapshots=[r],servings=3,prepared=[])
    saved=patch_state(client,url,0,{'selectedRecipeIds':[r['id']],'cooking':cooking})
    assert saved.status_code==200,saved.data
    assert len(saved.data['data']['cooking']['timers'])==2
    cooking['timerMeta']['t1']['stepId']='missing'
    assert patch_state(client,url,1,{'cooking':cooking}).status_code==400


def test_history_filters_and_snapshot_survive_recipe_deletion(context):
    client,url,*_=context
    data=client.get(url).data['data']
    record=sample_record(1);record['recipeSnapshots']=[data['recipes'][0]]
    assert patch_state(client,url,0,{},[record]).status_code==200
    assert patch_state(client,url,1,{'recipes':[]}).status_code==200
    history=url.replace('/state','/records')
    page=client.get(history,{'search':'番茄','start':'2026-09-27','end':'2026-09-27'}).data
    assert page['count']==1 and page['results'][0]['recipeSnapshots'][0]['name']=='番茄炒蛋'
    assert client.get(history,{'search':'面条'}).data['count']==0
    assert client.get(history,{'start':'2027-01-01'}).data['count']==0
    assert client.get(history,{'start':'invalid'}).status_code==400


def test_ai_idempotency_owner_isolation_and_cross_application(ai_context):
    context,snapshot=ai_context;client,url,owner,user,app=context
    task=create_task(ai_context,key='same')
    assert create_task(ai_context,key='same').pk==task.pk
    root=url.replace('/state','/ai/tasks')
    assert client.post(root,dict(kind='recipe',instruction='other',revision=0,requestKey='same'),format='json').status_code==409
    client.force_authenticate(owner)
    assert client.get(root).data==[]
    assert client.get(f'{root}/{task.pk}').status_code==404
    assert client.post(f'{root}/{task.pk}/cancel').status_code==404
    from apps.applications.models import Application
    other=Application.objects.create(organization=app.organization,category=app.category,name='其他应用',slug='other-app',created_by=owner,kind='custom',visibility='organization')
    client.force_authenticate(user)
    other_root=root.replace(f'/applications/{app.id}/',f'/applications/{other.id}/')
    assert client.get(f'{other_root}/{task.pk}').status_code==404
    assert client.get(root.replace(str(app.organization_id),str(user.owned_organizations.get().id))).status_code==404


def test_ai_runtime_success_and_followup_never_mutate_state(ai_context,monkeypatch):
    task=create_task(ai_context,recipeId='r1')
    before=deepcopy(task.state.data)
    monkeypatch.setattr(runtime,'call_model',lambda *_:{'answer':'中小火，留意食材状态。'})
    execute(task);task.refresh_from_db();task.state.refresh_from_db()
    assert task.status=='succeeded' and task.result['answer']
    assert task.state.data==before and task.state.revision==0
    follow=create_task(ai_context,parentId=str(task.pk))
    assert follow.snapshot['conversation'][0]['answer']==task.result['answer']
    assert task.snapshot['activeRecipe']['id']=='r1'


def test_cancel_during_model_call_discards_result(ai_context,monkeypatch):
    task=create_task(ai_context)
    def model(*_):
        KitchenAITask.objects.filter(pk=task.pk).update(cancel_requested=True,status='cancelled')
        return {'answer':'迟到的回答'}
    monkeypatch.setattr(runtime,'call_model',model)
    assert execute(task)=={}
    task.refresh_from_db();assert task.status=='cancelled' and task.result=={}


@pytest.mark.parametrize('answer',[{},[],{'answer':''},{'answer':123}])
def test_invalid_output_fails_without_writing_state(ai_context,monkeypatch,answer):
    task=create_task(ai_context);monkeypatch.setattr(runtime,'call_model',lambda *_:answer)
    with pytest.raises(RuntimeError):execute(task)
    task.refresh_from_db();assert task.status=='failed' and task.result=={}
    task.state.refresh_from_db();assert task.state.revision==0


def test_recipe_draft_missing_values_and_server_generated_ids():
    recipe=deepcopy(initial_state()['recipes'][0]);recipe['servings']=None;recipe['durationMinutes']=None;recipe['ingredients'][0]['amount']=None;recipe['steps'][0]['durationMinutes']=None
    task=SimpleNamespace(kind='recipe')
    result=ai.validate_output(task,{'recipe':recipe})
    assert result['recipe']['servings'] is None and result['recipe']['ingredients'][0]['amount'] is None
    assert 'servings' in result['missing'] and 'steps.0.durationMinutes' in result['missing']
    assert result['recipe']['id']!=recipe['id']
    assert result['recipe']['steps'][0]['ingredientIds'][0]==result['recipe']['ingredients'][0]['id']
    assert not Recipe(data=result['recipe']).is_valid()
    recipe['steps'][0]['ingredientIds']=['missing']
    with pytest.raises(ValueError):ai.validate_output(task,{'recipe':recipe})


def test_menu_validation_locks_invalid_ids_and_current_preference_recheck(ai_context,monkeypatch):
    context,snapshot=ai_context;client,url,*_=context
    task=create_task(ai_context,kind='menu',startDate='2026-10-01')
    menu=deepcopy(task.snapshot['weeklyMenu'])
    for day in menu:day['lunch']=['r1']
    monkeypatch.setattr(runtime,'call_model',lambda *_:{'menu':menu})
    execute(task);task.refresh_from_db()
    response=client.patch(url,dict(schemaVersion=2,revision=0,operationId=str(uuid4()),aiTaskId=str(task.pk),changes={'weeklyMenu':menu}),format='json')
    assert response.status_code==200,response.data
    assert response.data['data']['weeklyMenu'][0]['lunch']==['r1']
    prefs={**snapshot['data']['preferences'],'avoid':['鸡蛋']}
    assert patch_state(client,url,1,{'preferences':prefs}).status_code==200
    response=client.patch(url,dict(schemaVersion=2,revision=2,operationId=str(uuid4()),aiTaskId=str(task.pk),changes={'weeklyMenu':menu}),format='json')
    assert response.status_code==400
    invalid=deepcopy(menu);invalid[0]['dinner']=['missing']
    with pytest.raises(ValueError):ai.validate_output(task,{'menu':invalid})
    task.snapshot['weeklyMenu'][0]['lunch']=['r2'];task.snapshot['weeklyMenu'][0]['settings']['lunch']['locked']=True
    validated=ai.validate_output(task,{'menu':menu})
    assert validated['menu'][0]['lunch']==['r2']


@pytest.mark.parametrize('mode',['missing','timeout','quota','invalid_json'])
def test_provider_failures_are_explicit_and_do_not_retry(ai_context,monkeypatch,mode):
    import requests
    task=create_task(ai_context)
    calls=[]
    def provider(*_):
        if mode=='missing':raise ProviderUnavailable()
        return SimpleNamespace(base_url='https://model.invalid/v1',timeout_seconds=1,name='test'),'key','model'
    monkeypatch.setattr(runtime,'_provider',provider)
    def quota(*_):
        if mode=='quota':raise Throttled()
    monkeypatch.setattr(runtime,'enforce_member_token_quota',quota)
    def post(*args,**kwargs):
        calls.append(kwargs)
        if mode=='timeout':raise requests.Timeout()
        return SimpleNamespace(raise_for_status=lambda:None,json=lambda:{'choices':[{'message':{'content':'not json'}}],'usage':{}})
    monkeypatch.setattr(runtime.requests,'post',post)
    monkeypatch.setattr(runtime,'record_usage',lambda **_:None)
    with pytest.raises(RuntimeError):execute(task)
    task.refresh_from_db();assert task.status=='failed'
    assert len(calls)==(0 if mode in ['missing','quota'] else 1)


def test_real_platform_run_submission(context):
    client,url,owner,user,app=context
    call_command('sync_app_center',package_id='kitchen-assistant',organization_id=str(app.organization_id))
    root=url.replace('/state','/ai/tasks')
    response=client.post(root,dict(kind='question',instruction='小火怎么判断',revision=0,requestKey=str(uuid4())),format='json')
    assert response.status_code==202,response.data
    task=KitchenAITask.objects.get(pk=response.data['id'])
    assert task.run.executor_key=='kitchen-assistant' and task.run.max_attempts==1
    assert client.post(f'{root}/{task.pk}/cancel').status_code==200
    task.refresh_from_db();assert task.cancel_requested and task.status=='cancelled'


def test_history_name_migration_backfills_without_modifying_records(context):
    import importlib
    from django.apps import apps
    from django.db import connection
    from ..models import KitchenRecord
    client,url,_,user,app=context
    client.get(url)
    state=KitchenState.objects.get(owner=user,application=app)
    row=KitchenRecord.objects.create(organization=app.organization,state=state,record_id='old',data=sample_record(99),finished_at='2026-09-27T00:10:00Z')
    original=deepcopy(row.data)
    migration=importlib.import_module('app_center.kitchen_assistant.backend.migrations.0006_kitchenrecord_recipe_names')
    migration.backfill_names(apps,SimpleNamespace(connection=connection))
    migration.backfill_names(apps,SimpleNamespace(connection=connection))
    row.refresh_from_db();assert row.recipe_names=='番茄炒蛋' and row.data==original
    assert client.get(url.replace('/state','/records'),{'search':'番茄'}).data['count']==1


def test_duplicate_runtime_delivery_does_not_call_model_twice(ai_context,monkeypatch):
    task=create_task(ai_context);calls=[]
    def model(*_):calls.append(1);return {'answer':'建议'}
    monkeypatch.setattr(runtime,'call_model',model)
    execute(task);execute(task)
    assert calls==[1]


def test_ai_state_conflict_and_cancelled_task_cannot_be_applied(ai_context,monkeypatch):
    context,snapshot=ai_context;client,url,*_=context
    task=create_task(ai_context,kind='menu',startDate='2026-10-01')
    menu=deepcopy(task.snapshot['weeklyMenu'])
    monkeypatch.setattr(runtime,'call_model',lambda *_:{'menu':menu})
    execute(task)
    assert patch_state(client,url,0,{'servings':3}).status_code==200
    response=client.patch(url,dict(schemaVersion=2,revision=0,operationId=str(uuid4()),aiTaskId=str(task.pk),changes={'weeklyMenu':menu}),format='json')
    assert response.status_code==409
    KitchenAITask.objects.filter(pk=task.pk).update(status='cancelled')
    response=client.patch(url,dict(schemaVersion=2,revision=1,operationId=str(uuid4()),aiTaskId=str(task.pk),changes={'weeklyMenu':menu}),format='json')
    assert response.status_code==404
