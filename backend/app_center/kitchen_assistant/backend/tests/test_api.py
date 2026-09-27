from copy import deepcopy

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from apps.applications.models import Application, ApplicationCategory
from apps.enterprise.models import Membership
from ..models import KitchenState
from ..serializers import State
from ..views import initial_state


@pytest.fixture
def context(db):
    owner = get_user_model().objects.create_user(username="kitchen-owner")
    user = get_user_model().objects.create_user(username="kitchen-user")
    org = owner.owned_organizations.get()
    Membership.objects.create(organization=org, user=user, role=Membership.Role.VIEWER)
    category = ApplicationCategory.objects.create(name="Kitchen", slug="kitchen")
    application = Application.objects.create(organization=org, category=category, name="厨房助手", slug="kitchen-assistant", created_by=owner, kind=Application.Kind.CUSTOM, visibility=Application.Visibility.ORGANIZATION)
    client = APIClient()
    client.force_authenticate(user)
    return client, f"/api/v1/organizations/{org.id}/applications/{application.id}/kitchen-assistant/state", owner, user, application


def test_seed_is_valid():
    serializer = State(data=initial_state())
    assert serializer.is_valid(), serializer.errors
    assert len(serializer.data["recipes"]) >= 3
    assert serializer.data["inventory"] == []


def test_persistence_and_conflict(context):
    client, url, _, user, app = context
    first = client.get(url)
    assert first.status_code == 200
    stale = deepcopy(first.data)
    payload = deepcopy(first.data)
    payload["data"]["selectedRecipeIds"] = [payload["data"]["recipes"][0]["id"]]
    payload["data"]["servings"] = 4
    saved = client.put(url, payload, format="json")
    assert saved.status_code == 200, saved.data
    assert saved.data["revision"] == 1
    assert client.get(url).data == saved.data
    assert client.put(url, stale, format="json").status_code == 409
    assert client.get(url).data["data"]["servings"] == 4
    row = KitchenState.objects.get(owner=user, application=app)
    assert row.organization_id == app.organization_id


def test_private_to_each_user_including_admin(context):
    client, url, owner, user, _ = context
    payload = client.get(url).data
    payload["data"]["recipes"][0]["name"] = "私房菜"
    client.put(url, payload, format="json")
    client.force_authenticate(owner)
    assert client.get(url).data["data"]["recipes"][0]["name"] != "私房菜"
    client.force_authenticate(user)
    assert client.get(url).data["data"]["recipes"][0]["name"] == "私房菜"


def test_auth_application_and_organization_access(context):
    client, url, _, user, app = context
    assert APIClient().get(url).status_code in (401, 403)
    assert client.get(url.replace(str(app.organization_id), str(user.owned_organizations.get().id))).status_code == 404
    outsider = get_user_model().objects.create_user(username="kitchen-outsider")
    client.force_authenticate(outsider)
    assert client.get(url).status_code in (403, 404)
    client.force_authenticate(user)
    app.is_active = False
    app.save()
    assert client.get(url).status_code == 404
    app.is_active = True
    app.visibility = Application.Visibility.RESTRICTED
    app.save()
    assert client.get(url).status_code == 404


@pytest.mark.parametrize("mutation", [
    lambda s: s.update(servings=0),
    lambda s: s.update(selectedRecipeIds=["missing"]),
    lambda s: s["recipes"][0].update(servings=0),
    lambda s: s["recipes"][0].update(steps=[]),
    lambda s: s["recipes"][0]["ingredients"][0].update(amount=-1),
    lambda s: s["recipes"][0]["steps"][0].update(ingredientIds=["missing"]),
    lambda s: s["recipes"].append(deepcopy(s["recipes"][0])),
    lambda s: s.update(weeklyMenu=[["missing"]]),
])
def test_invalid_state_never_overwrites(context, mutation):
    client, url, *_ = context
    original = client.get(url).data
    payload = deepcopy(original)
    mutation(payload["data"])
    assert client.put(url, payload, format="json").status_code == 400
    assert client.get(url).data == original


def test_cooking_progress_roundtrip_and_bounds(context):
    client, url, *_ = context
    payload = client.get(url).data
    recipe = payload["data"]["recipes"][0]
    key = recipe["id"]
    payload["data"]["selectedRecipeIds"] = [key]
    payload["data"]["cooking"] = dict(startedAt="2026-09-27T00:00:00Z", recipeIds=[key], currentId=key, steps={key: 0}, completedIds=[], timers={key: 1790467260000})
    saved = client.put(url, payload, format="json")
    assert saved.status_code == 200, saved.data
    assert client.get(url).data["data"]["cooking"]["timers"][key] == 1790467260000
    invalid = deepcopy(saved.data)
    invalid["data"]["cooking"]["steps"][key] = len(recipe["steps"])
    assert client.put(url, invalid, format="json").status_code == 400
    invalid = deepcopy(saved.data)
    invalid["data"]["selectedRecipeIds"] = []
    assert client.put(url, invalid, format="json").status_code == 400


def patch_state(client, url, revision, changes=None, records=None, operation_id=None):
    import uuid
    return client.patch(url, dict(schemaVersion=2, revision=revision, changes=changes or {}, appendRecords=records or [], operationId=operation_id or str(uuid.uuid4())), format="json")


def sample_record(index):
    return dict(id=f"record-{index}", recipeNames=["番茄炒蛋"], startedAt="2026-09-27T00:00:00Z", finishedAt="2026-09-27T00:10:00Z", servings=2, rating=0, tasteNotes="", healthSummary="")


def test_partial_patch_and_idempotent_retry(context):
    import uuid
    client, url, *_ = context
    first = client.get(url).data
    operation_id = str(uuid.uuid4())
    saved = patch_state(client, url, first["revision"], {"servings": 4}, [sample_record(1)], operation_id)
    assert saved.status_code == 200, saved.data
    # The first response can be lost; retrying cannot duplicate history or mutate twice.
    retry = patch_state(client, url, first["revision"], {"servings": 4}, [sample_record(1)], operation_id)
    assert retry.data == saved.data
    assert retry.data["recordCount"] == 1
    assert retry.data["data"]["recipes"] == first["data"]["recipes"]
    assert patch_state(client, url, 0, {"servings": 6}).status_code == 409
    assert patch_state(client, url, 1, {"owner": 123}).status_code == 400


def test_history_beyond_500_is_paginated_and_private(context):
    from ..models import KitchenRecord
    client, url, owner, user, app = context
    client.get(url)
    state = KitchenState.objects.get(owner=user, application=app)
    KitchenRecord.objects.bulk_create([
        KitchenRecord(organization=app.organization, state=state, record_id=f"record-{i}", data=sample_record(i), finished_at="2026-09-27T00:10:00Z") for i in range(500)
    ])
    saved = patch_state(client, url, 0, {"servings": 3}, [sample_record(500)])
    assert saved.status_code == 200, saved.data
    assert saved.data["recordCount"] == 501
    assert len(saved.data["data"]["records"]) == 20
    state.refresh_from_db()
    assert state.data["records"] == []
    history_url = url.replace("/state", "/records")
    page = client.get(history_url).data
    assert page["count"] == 501 and len(page["results"]) == 20
    assert len(client.get(history_url, {"page": 26}).data["results"]) == 1
    record_url = f"{history_url}/record-500"
    edit = client.patch(record_url, {"revision": 0, "rating": 4, "tasteNotes": "好吃"}, format="json")
    assert edit.status_code == 200 and edit.data["rating"] == 4
    assert client.patch(record_url, {"revision": 0, "rating": 2}, format="json").status_code == 409
    client.force_authenticate(owner)
    assert client.get(history_url).data["count"] == 0
    assert client.patch(record_url, {"revision": 1, "rating": 1}, format="json").status_code == 404
    assert client.delete(record_url + "?revision=1").status_code == 404
    client.force_authenticate(user)
    assert client.delete(record_url + "?revision=0").status_code == 409
    assert client.delete(record_url + "?revision=1").status_code == 204
    assert client.get(history_url).data["count"] == 500


def test_data_migration_preserves_legacy_history_and_is_repeatable(context):
    import importlib
    from types import SimpleNamespace
    from django.apps import apps
    from django.db import connection
    from ..models import KitchenRecord
    client, url, _, user, app = context
    client.get(url)
    state = KitchenState.objects.get(owner=user, application=app)
    state.data["records"] = [sample_record(i) for i in range(501)]
    state.save()
    migration = importlib.import_module("app_center.kitchen_assistant.backend.migrations.0004_history_data_and_rls")
    editor = SimpleNamespace(connection=connection)
    migration.move_history(apps, editor)
    migration.move_history(apps, editor)
    assert KitchenRecord.objects.filter(state=state).count() == 501
    state.refresh_from_db()
    assert state.data["records"] == []
    migration.restore_history(apps, editor)
    state.refresh_from_db()
    assert len(state.data["records"]) == 501


def test_legacy_menu_and_paused_timers(context):
    client, url, _, user, app = context
    payload = client.get(url).data
    row = KitchenState.objects.get(owner=user, application=app)
    row.data["weeklyMenu"] = [["r1", "r2"]]
    row.save()
    loaded = client.get(url).data
    assert loaded["data"]["weeklyMenu"][0]["dinner"] == ["r1", "r2"]
    cooking = dict(startedAt="2026-09-27T00:00:00Z", recipeIds=["r1"], currentId="r1", steps={"r1": 0}, completedIds=[], timers={}, pausedTimers={"r1": 120})
    saved = patch_state(client, url, payload["revision"], {"selectedRecipeIds": ["r1"], "cooking": cooking})
    assert saved.status_code == 200, saved.data
    assert saved.data["data"]["cooking"]["pausedTimers"] == {"r1": 120}
    cooking["timers"] = {"r1": 999999999}
    assert patch_state(client, url, saved.data["revision"], {"cooking": cooking}).status_code == 400
