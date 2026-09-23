from datetime import timedelta
from unittest.mock import Mock

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient

from apps.applications.models import Application
from apps.enterprise.models import Membership
from app_center.ideas_todos.backend.models import Idea, Todo
from modules.execution.models import Run
from ..models import Binding
from ..services import dispatch_message
from .test_wechat import account, connected  # noqa: F401
from .test_menu import send, reply


@pytest.fixture
def entries(account):
    call_command("sync_app_center", package="ideas-todos", organization_id=str(account.organization_id))
    app = Application.objects.get(organization=account.organization, slug="ideas-todos")
    connected(account)
    return app


@pytest.mark.parametrize("command,model,kind", [("添加想法", Idea, "ideas"), ("添加待办", Todo, "todos")])
def test_multiline_add_is_shared_with_web_and_idempotent(account, entries, monkeypatch, command, model, kind):
    create_run = Mock(side_effect=AssertionError("No model calls for entry commands"))
    monkeypatch.setattr("app_center.wechat_assistant.backend.services.create_conversation_run", create_run)
    item = send(account, command + "\r\n 第一条 \r\n\r\n第二条\n第三条", mid="batch")
    assert "已添加 3 条" in reply(item)
    assert model.objects.filter(application=entries, organization=account.organization, owner=account.user).count() == 3
    assert set(model.objects.values_list("title", flat=True)) == {"第一条", "第二条", "第三条"}
    dispatch_message(item.pk, "worker")
    assert model.objects.count() == 3 and not item.run_id and not account.menu_state
    client = APIClient()
    client.force_authenticate(account.user)
    response = client.get(f"/api/v1/organizations/{account.organization_id}/applications/{entries.pk}/ideas-todos/{kind}")
    assert response.status_code == 200 and response.data["count"] == 3
    if model is Todo:
        assert not model.objects.exclude(is_completed=False, priority=2, due_date=None).exists()
    create_run.assert_not_called()


@pytest.mark.parametrize("text", ["添加想法：灵感", "添加想法:灵感", "添加想法 灵感", "添加想法\n灵感"])
def test_inline_formats(account, entries, text):
    send(account, text)
    assert Idea.objects.get().title == "灵感"


@pytest.mark.parametrize("number,state,model", [("6", "add_idea", Idea), ("7", "add_todo", Todo)])
def test_menu_capture_survives_reload(account, entries, number, state, model):
    send(account, "菜单")
    assert "每个非空行" in reply(send(account, number))
    recovered = Binding.objects.get(pk=account.pk)
    assert recovered.menu_state == state
    send(recovered, "第一行\n第二行")
    assert model.objects.count() == 2 and not recovered.menu_state


@pytest.mark.parametrize("command,model", [("添加想法", Idea), ("添加待办", Todo)])
def test_bare_command_capture_and_cancel(account, entries, command, model):
    send(account, command)
    assert account.menu_expires_at > timezone.now()
    send(account, "0")
    assert not account.menu_state and not model.objects.exists()
    send(account, command)
    send(account, "菜单")
    assert account.menu_state == "main" and not model.objects.exists()
    send(account, command)
    send(account, "退出菜单")
    assert not account.menu_state and not model.objects.exists()


def test_expired_capture_does_not_save_or_run(account, entries):
    send(account, "添加想法")
    Binding.objects.filter(pk=account.pk).update(menu_expires_at=timezone.now() - timedelta(seconds=1))
    assert "本次内容未保存" in reply(send(account, "这是过期的内容"))
    assert not account.menu_state and not Idea.objects.exists() and not Run.objects.exists()


def test_changing_command_with_invalid_content_does_not_keep_old_capture(account, entries):
    send(account, "添加想法")
    assert "本次未保存" in reply(send(account, "添加待办\n" + "长" * 201))
    assert not account.menu_state and not Idea.objects.exists() and not Todo.objects.exists()
    send(account, "添加待办\n修正的内容")
    assert Todo.objects.get().title == "修正的内容" and not Idea.objects.exists()


@pytest.mark.parametrize("command,expected", [("查询想法", "还没有想法"), ("查询待办", "暂无未完成待办")])
def test_empty_query_ends_capture(account, entries, command, expected):
    send(account, "添加想法")
    assert expected in reply(send(account, command))
    assert not account.menu_state and not Idea.objects.exists() and not Todo.objects.exists()


@pytest.mark.parametrize("command,model", [("添加想法", Idea), ("添加待办", Todo)])
def test_batch_validation_is_all_or_nothing_and_can_retry(account, entries, command, model):
    send(account, command)
    assert "第 2 条" in reply(send(account, "有效\n" + "长" * 201))
    assert not model.objects.exists() and account.menu_state
    assert "本次未保存" in reply(send(account, "\n".join(["条目"] * 101)))
    assert not model.objects.exists()
    assert "已添加 2 条" in reply(send(account, "同样内容\n同样内容"))
    assert model.objects.count() == 2


@pytest.mark.parametrize("command,model", [("查询想法", Idea), ("查询待办", Todo)])
def test_query_paginates_private_records(account, entries, command, model):
    for i in range(12):
        model.objects.create(application=entries, organization=account.organization, owner=account.user, title=f"自己的条目{i:02}")
    other = get_user_model().objects.create_user(username="entry-other")
    model.objects.create(application=entries, organization=account.organization, owner=other, title="OTHER-OWNER")
    model.objects.create(application=entries, organization=other.owned_organizations.get(), owner=account.user, title="OTHER-ORG")
    model.objects.create(application=account.application, organization=account.organization, owner=account.user, title="OTHER-APP")
    first = reply(send(account, command))
    second = reply(send(account, command + " 2"))
    assert "共 12 条" in first and "第 1/2 页" in first and "第 2/2 页" in second
    assert first.count("自己的条目") == 10 and second.count("自己的条目") == 2
    assert "OTHER-" not in first + second and not account.menu_state
    assert "页码超出范围" in reply(send(account, command + " 3"))
    assert not Run.objects.exists()


def test_query_menu_pending_and_sorting(account, entries):
    values = dict(application=entries, organization=account.organization, owner=account.user)
    Idea.objects.create(**values, title="置顶想法", is_pinned=True)
    Idea.objects.create(**values, title="最新想法")
    Todo.objects.create(**values, title="已完成待办", is_completed=True)
    Todo.objects.create(**values, title="无日期待办", priority=3)
    Todo.objects.create(**values, title="有日期待办", due_date="2026-10-01")
    send(account, "菜单")
    ideas = reply(send(account, "8"))
    assert ideas.index("置顶想法") < ideas.index("最新想法")
    send(account, "菜单")
    todos = reply(send(account, "9"))
    assert "已完成待办" not in todos
    assert todos.index("有日期待办") < todos.index("无日期待办")


@pytest.mark.parametrize("payload", ["0", "-1", "abc", "1\n2", "9" * 5000])
def test_invalid_query_is_not_a_chat(account, entries, payload):
    assert "查询格式" in reply(send(account, "查询想法 " + payload))
    assert not Run.objects.exists()


def test_unavailable_application(account):
    connected(account)
    assert "尚未启用" in reply(send(account, "添加想法\n一条"))
    assert not Idea.objects.exists()


@pytest.mark.parametrize("resource", ["application", "membership", "application_permission"])
def test_revoked_access_before_capture_cannot_save(account, entries, resource):
    send(account, "添加想法")
    if resource == "application":
        entries.is_active = False
        entries.save()
    elif resource == "membership":
        Membership.objects.filter(user=account.user, organization=account.organization).update(is_active=False)
    else:
        Membership.objects.filter(user=account.user, organization=account.organization).update(role=Membership.Role.VIEWER)
        entries.created_by = get_user_model().objects.create_user(username="app-owner")
        entries.visibility = Application.Visibility.RESTRICTED
        entries.save()
    item = send(account, "不能保存")
    assert not Idea.objects.exists() and not item.run_id
    assert "已添加" not in reply(item)


def test_entries_work_while_busy_and_without_agent(account, entries):
    send(account, "执行一个任务")
    send(account, "添加待办\n正在忙也能记录")
    assert Todo.objects.count() == 1
    Binding.objects.filter(pk=account.pk).update(agent=None)
    assert "正在忙也能记录" in reply(send(account, "查询待办"))
    assert Run.objects.count() == 1


def test_saving_and_reply_are_atomic(account, entries, monkeypatch):
    from .. import services

    enqueue = services.enqueue
    monkeypatch.setattr(services, "enqueue", Mock(side_effect=RuntimeError("reply crash")))
    with pytest.raises(RuntimeError, match="reply crash"):
        send(account, "添加想法\n第一条\n第二条", mid="atomic-batch")
    assert not Idea.objects.exists()
    monkeypatch.setattr(services, "enqueue", enqueue)
    pending = account.incoming.get(state="pending")
    dispatch_message(pending.pk, "worker")
    assert Idea.objects.count() == 2
    dispatch_message(pending.pk, "worker")
    assert Idea.objects.count() == 2


def test_similar_prose_is_not_treated_as_command(account, entries):
    assert send(account, "添加想法有什么用").run_id
