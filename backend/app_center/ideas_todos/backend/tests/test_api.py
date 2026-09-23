import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.applications.models import Application, ApplicationAccessGrant, ApplicationCategory
from apps.enterprise.models import Membership

from ..models import Idea, Todo


@pytest.fixture
def context(db):
    User = get_user_model()
    owner = User.objects.create_user(username="ideas-owner")
    user = User.objects.create_user(username="ideas-user")
    other = User.objects.create_user(username="ideas-other")
    org = owner.owned_organizations.get()
    for member in (user, other):
        Membership.objects.create(organization=org, user=member, role=Membership.Role.VIEWER)
    category = ApplicationCategory.objects.create(name="Ideas productivity", slug="ideas-productivity")
    application = Application.objects.create(
        organization=org, category=category, name="想法&待办", slug="ideas-todos",
        created_by=owner, kind=Application.Kind.CUSTOM, visibility=Application.Visibility.ORGANIZATION,
    )
    client = APIClient()
    client.force_authenticate(user)
    return {
        "org": org, "owner": owner, "user": user, "other": other,
        "app": application, "client": client,
        "root": f"/api/v1/organizations/{org.id}/applications/{application.id}/ideas-todos",
    }


def create(context, kind, **data):
    response = context["client"].post(f"{context['root']}/{kind}", {"title": "记录", **data}, format="json")
    assert response.status_code == 201, response.data
    return response.data


@pytest.mark.parametrize("kind", ["ideas", "todos"])
def test_crud_and_required_title(context, kind):
    client, url = context["client"], f"{context['root']}/{kind}"
    for title in ("", "   ", "x" * 201):
        assert client.post(url, {"title": title}, format="json").status_code == 400
    item = create(context, kind, title="第一条")
    detail = f"{url}/{item['id']}"
    assert client.get(detail).data["title"] == "第一条"
    assert client.patch(detail, {"title": "修改后"}, format="json").data["title"] == "修改后"
    assert client.get(url).data["count"] == 1
    assert client.delete(detail).status_code == 204
    assert client.get(detail).status_code == 404
    assert client.get(url).data["count"] == 0


def test_ideas_pin_search_tags_and_pagination(context):
    first = create(context, "ideas", title="灵感", body="公园观察", tags=["生活", "生活", "写作"])
    assert first["tags"] == ["生活", "写作"]
    for index in range(21):
        create(context, "ideas", title=f"其他 {index}")
    url = f"{context['root']}/ideas"
    client = context["client"]
    assert client.patch(f"{url}/{first['id']}", {"is_pinned": True}, format="json").status_code == 200
    page = client.get(url).data
    assert page["count"] == 22 and len(page["results"]) == 20 and page["next"]
    assert page["results"][0]["id"] == first["id"]
    assert len(client.get(url, {"page": 2}).data["results"]) == 2
    assert client.get(url, {"search": "公园", "tag": "生活"}).data["count"] == 1
    assert client.get(url, {"tag": "不存在"}).data["count"] == 0
    assert client.patch(f"{url}/{first['id']}", {"is_pinned": False}, format="json").data["is_pinned"] is False
    assert client.post(url, {"title": "test", "tags": ["x" * 41]}, format="json").status_code == 400


def test_todo_dates_order_search_priority_and_completion(context):
    client, url = context["client"], f"{context['root']}/todos"
    no_date = create(context, "todos", title="无日期", priority=3)
    later = create(context, "todos", due_date="2026-10-02", priority=3)
    low = create(context, "todos", due_date="2026-10-01", priority=1)
    high = create(context, "todos", title="重点", description="提交报告", due_date="2026-10-01", priority=3)
    default = create(context, "todos", title="默认")
    assert default["priority"] == 2 and default["due_date"] is None
    ids = [item["id"] for item in client.get(url).data["results"]]
    assert ids == [high["id"], low["id"], later["id"], no_date["id"], default["id"]]
    assert client.get(url, {"status": "today", "today": "2026-10-01"}).data["count"] == 2
    assert client.get(url, {"status": "overdue", "today": "2026-10-02"}).data["count"] == 2
    assert client.get(url, {"search": "报告", "priority": 3}).data["count"] == 1
    assert client.get(url, {"status": "today"}).status_code == 400
    assert client.get(url, {"status": "bad"}).status_code == 400
    assert client.post(url, {"title": "bad", "due_date": "bad"}, format="json").status_code == 400
    assert client.post(url, {"title": "bad", "priority": 4}, format="json").status_code == 400
    detail = f"{url}/{high['id']}"
    completed = client.patch(detail, {"is_completed": True}, format="json").data
    assert completed["completed_at"]
    assert client.patch(detail, {"is_completed": True}, format="json").data["completed_at"] == completed["completed_at"]
    assert client.get(url).data["count"] == 4
    assert client.get(url, {"status": "completed"}).data["count"] == 1
    assert client.get(url, {"status": "all"}).data["count"] == 5
    assert client.get(url, {"status": "today", "today": "2026-10-01"}).data["count"] == 1
    restored = client.patch(detail, {"is_completed": False, "due_date": None}, format="json").data
    assert restored["completed_at"] is None and restored["due_date"] is None


@pytest.mark.parametrize("kind,model", [("ideas", Idea), ("todos", Todo)])
def test_owner_is_server_assigned_and_private_even_to_org_owner(context, kind, model):
    item = create(context, kind, owner=context["other"].id, organization="fake", application=99999)
    record = model.objects.get(pk=item["id"])
    assert record.owner == context["user"] and record.organization == context["org"] and record.application == context["app"]
    detail = f"{context['root']}/{kind}/{item['id']}"
    context["client"].patch(detail, {"owner": context["other"].id}, format="json")
    record.refresh_from_db()
    assert record.owner == context["user"]
    for other in (context["other"], context["owner"]):
        client = APIClient()
        client.force_authenticate(other)
        assert client.get(f"{context['root']}/{kind}").data["count"] == 0
        assert client.get(detail).status_code == 404
        assert client.patch(detail, {"title": "偷改"}, format="json").status_code == 404
        assert client.delete(detail).status_code == 404


@pytest.mark.parametrize("kind", ["ideas", "todos"])
def test_organization_application_and_auth_boundaries(context, kind):
    item = create(context, kind)
    client = context["client"]
    other_org = context["user"].owned_organizations.get()
    other_app = Application.objects.create(
        organization=other_org, category=context["app"].category,
        name="Other", slug="ideas-todos", created_by=context["user"],
    )
    other_root = f"/api/v1/organizations/{other_org.id}/applications/{other_app.id}/ideas-todos"
    assert client.get(f"{other_root}/{kind}").data["count"] == 0
    assert client.get(f"{other_root}/{kind}/{item['id']}").status_code == 404
    wrong_app = context["root"].replace(f"applications/{context['app'].id}", f"applications/{other_app.id}")
    assert client.get(f"{wrong_app}/{kind}").status_code == 404
    assert client.post(f"{wrong_app}/{kind}", {"title": "wrong"}, format="json").status_code == 404
    assert APIClient().get(f"{context['root']}/{kind}").status_code in (401, 403)
    outsider = get_user_model().objects.create_user(username=f"outsider-{kind}")
    client.force_authenticate(outsider)
    assert client.get(f"{context['root']}/{kind}").status_code in (403, 404)


def test_application_access_and_inactive_state(context):
    client, url, application = context["client"], f"{context['root']}/ideas", context["app"]
    application.is_active = False
    application.save()
    assert client.get(url).status_code == 404
    assert client.post(url, {"title": "bad"}, format="json").status_code == 404
    application.is_active = True
    application.visibility = Application.Visibility.RESTRICTED
    application.save()
    assert client.get(url).status_code == 404
    grant = ApplicationAccessGrant.objects.create(application=application, user=context["user"], role="viewer")
    assert client.post(url, {"title": "bad"}, format="json").status_code == 404
    grant.role = "user"
    grant.save()
    assert client.post(url, {"title": "allowed"}, format="json").status_code == 201
    application.slug = "unrelated-app"
    application.save()
    assert client.get(url).status_code == 404


@pytest.mark.parametrize("kind", ["ideas", "todos"])
def test_single_tenant_alias_keeps_user_records_private(context, settings, kind):
    settings.SINGLE_TENANT_MODE = True
    settings.SINGLE_TENANT_ORGANIZATION_ID = str(context["org"].id)
    url = f"/api/v1/applications/{context['app'].id}/ideas-todos/{kind}"
    created = context["client"].post(url, {"title": "个人记录"}, format="json")
    assert created.status_code == 201, created.data
    assert context["client"].get(url).data["count"] == 1
    other_client = APIClient()
    other_client.force_authenticate(context["other"])
    assert other_client.get(url).data["count"] == 0
    assert other_client.get(f"{url}/{created.data['id']}").status_code == 404
