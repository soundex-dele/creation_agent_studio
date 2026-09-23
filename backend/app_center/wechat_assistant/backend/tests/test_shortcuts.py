from datetime import timedelta
from unittest.mock import Mock

import pytest
from django.utils import timezone

from app_center.ideas_todos.backend.models import Idea, Todo
from apps.conversations.models import Conversation
from modules.execution.models import Run
from ..models import Binding
from .test_wechat import account, connected  # noqa: F401
from .test_entry_commands import entries  # noqa: F401
from .test_menu import add_agent, reply, send


def test_shortcut_opens_agent_list_without_opening_main_menu(account):
    connected(account)
    item = send(account, "菜单1")
    assert account.menu_state == "agents"
    assert "选择智能体" in reply(item) and "功能菜单" not in reply(item)
    assert not item.run_id and not Conversation.objects.exists()


def test_shortcut_selects_agent_with_inline_input_once(account):
    connected(account)
    target = add_agent(account, "A-shortcut")
    item = send(account, "菜单1\n1", mid="agent-shortcut")
    assert account.agent_id == target.pk and account.conversation_id
    assert "A-shortcut" in reply(item) and not account.menu_state
    assert item.replies.count() == 1 and not item.run_id
    send(account, "菜单1\n1", mid="agent-shortcut")
    assert Conversation.objects.count() == 1


@pytest.mark.parametrize("value", ["100", "随便一个", "1\n2", "菜单7\n不能当成待办"])
def test_invalid_inline_agent_input_stays_in_selection(account, value):
    connected(account)
    item = send(account, "菜单1\n" + value)
    assert "智能体选择无效" in reply(item)
    assert account.menu_state == "agents"
    assert not Run.objects.exists() and not Conversation.objects.exists() and not Todo.objects.exists()


@pytest.mark.parametrize("number,model", [("6", Idea), ("7", Todo)])
def test_shortcut_adds_every_line_as_literal_content(account, entries, number, model, monkeypatch):
    create_run = Mock(side_effect=AssertionError("Shortcuts must not invoke the model"))
    monkeypatch.setattr("app_center.wechat_assistant.backend.services.create_conversation_run", create_run)
    text = f"菜单{number}\n第一条\n\n0\n查询想法\n菜单1"
    item = send(account, text, mid="inline-batch")
    assert "已添加 4 条" in reply(item)
    assert set(model.objects.values_list("title", flat=True)) == {"第一条", "0", "查询想法", "菜单1"}
    assert not account.menu_state
    send(account, text, mid="inline-batch")
    assert model.objects.count() == 4
    create_run.assert_not_called()


@pytest.mark.parametrize("number,state,model", [("6", "add_idea", Idea), ("7", "add_todo", Todo)])
def test_shortcut_without_inline_content_prompts_for_input(account, entries, number, state, model):
    item = send(account, f"菜单{number}\n\n")
    assert "每个非空行" in reply(item) and account.menu_state == state
    send(account, "后续内容一\n后续内容二")
    assert model.objects.count() == 2 and not account.menu_state


@pytest.mark.parametrize("number,expected", [
    ("0", "菜单已关闭"), ("2", "已新建会话"), ("3", "还没有微信发起的任务"),
    ("4", "当前智能体"), ("5", "快捷用法"), ("8", "还没有想法"), ("9", "暂无未完成待办"),
])
def test_no_input_actions_ignore_extra_lines(account, entries, number, expected):
    item = send(account, f"菜单{number}\n菜单7\n不应添加或聊天\n2")
    assert expected in reply(item) and not account.menu_state
    assert not item.run_id and not Idea.objects.exists() and not Todo.objects.exists()
    assert Conversation.objects.count() == (1 if number == "2" else 0)


@pytest.mark.parametrize("previous", ["添加想法", "添加待办", "菜单1"])
def test_shortcut_overrides_previous_state_even_when_expired(account, entries, previous):
    send(account, previous)
    Binding.objects.filter(pk=account.pk).update(menu_expires_at=timezone.now() - timedelta(minutes=1))
    item = send(account, " 菜单 7 \r\n\r\n 新待办 \r\n 第二条 ")
    assert "已添加 2 条待办" in reply(item)
    assert set(Todo.objects.values_list("title", flat=True)) == {"新待办", "第二条"}
    assert not Idea.objects.exists() and not account.menu_state


def test_shortcut_keeps_batch_validation_atomic(account, entries):
    item = send(account, "菜单6\n有效\n" + "长" * 201)
    assert "本次未保存" in reply(item) and not Idea.objects.exists()
    assert not item.run_id


def test_shortcuts_respect_busy_state(account, entries):
    send(account, "执行任务")
    for number in ("1", "2"):
        assert "尚未完成" in reply(send(account, f"菜单{number}\n1"))
    assert "已添加 1 条" in reply(send(account, "菜单7\n忙碌时记录"))
    assert "忙碌时记录" in reply(send(account, "菜单9\n忽略输入"))
    assert Run.objects.count() == 1


def test_shortcut_checks_application_permission(account, entries):
    entries.is_active = False
    entries.save()
    assert "尚未启用" in reply(send(account, "菜单6\n不应保存"))
    assert not Idea.objects.exists() and not Run.objects.exists()


@pytest.mark.parametrize("number", ["10", "99999999999999999999999999"])
def test_unknown_shortcut_does_not_become_capture_content(account, entries, number):
    send(account, "添加想法")
    assert "快捷菜单编号无效" in reply(send(account, f"菜单{number}\n不保存"))
    assert not Idea.objects.exists() and not Run.objects.exists()
    assert account.menu_state == "add_idea"


def test_similar_text_still_uses_chat(account):
    connected(account)
    assert send(account, "菜单1有什么功能").run_id
