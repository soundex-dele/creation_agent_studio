import hashlib
import uuid
from datetime import timedelta
from unittest.mock import Mock

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.agents.models import Agent
from apps.conversations.models import Conversation
from apps.enterprise.models import Membership
from modules.execution.models import Run
from ..connector import cycle, deliver
from ..models import Binding, IncomingMessage, OutgoingMessage
from ..protocol import WechatError
from ..services import configure, dispatch_message, store_updates
from .test_wechat import account, connected, message  # noqa: F401


def send(binding, text, *, mid=None, owner="worker"):
    mid = mid or str(IncomingMessage.objects.count() + 100)
    payload = message(mid, item_list=[{"type": 1, "text_item": {"text": text}}])
    store_updates(binding.pk, owner, binding.generation, {"msgs": [payload]})
    item = IncomingMessage.objects.get(binding=binding, message_id=hashlib.sha256(f"{binding.bot_id}:{mid}".encode()).hexdigest())
    dispatch_message(item.pk, owner)
    item.refresh_from_db()
    binding.refresh_from_db()
    return item


def reply(item):
    return "".join(item.replies.order_by("part").values_list("text", flat=True))


def add_agent(binding, name):
    return Agent.objects.create(
        name=name, slug=f"menu-{Agent.objects.count()}", category=binding.agent.category,
        organization=binding.organization, created_by=binding.user, visibility="organization",
    )


@pytest.mark.parametrize("command", ["菜单", "/menu", " 菜单 "])
def test_menu_opens_without_model_or_task(account, monkeypatch, command):
    connected(account)
    create_run = Mock(side_effect=AssertionError("Menu must not invoke a model"))
    monkeypatch.setattr("app_center.wechat_assistant.backend.services.create_conversation_run", create_run)
    item = send(account, command)
    assert "1. 切换智能体" in reply(item)
    assert item.state == "handled" and item.run_id is None
    assert account.menu_state == "main"
    assert timedelta(minutes=4) < account.menu_expires_at - timezone.now() <= timedelta(minutes=5)
    assert not Conversation.objects.exists()
    create_run.assert_not_called()


@pytest.mark.parametrize("choice,expected", [("3", "还没有"), ("4", "当前智能体"), ("5", "待办与审批"), ("0", "菜单已关闭"), ("退出菜单", "菜单已关闭")])
def test_controls_finish_in_chat(account, choice, expected):
    connected(account)
    send(account, "菜单")
    item = send(account, choice)
    assert expected in reply(item)
    assert not account.menu_state and account.menu_expires_at is None and account.menu_data == {}
    assert not Run.objects.exists()
    assert "secret" not in reply(item)


@pytest.mark.parametrize("open_menu,text", [(False, "1"), (True, "帮我写文章")])
def test_chat_fallback(account, open_menu, text):
    connected(account)
    if open_menu:
        send(account, "菜单")
    item = send(account, text)
    assert item.run_id and not account.menu_state


@pytest.mark.parametrize("command", ["菜单", "/menu"])
@pytest.mark.parametrize("run_status", ["running", "waiting_input", "succeeded"])
def test_menu_returns_from_existing_chat_without_creating_another_run(account, monkeypatch, command, run_status):
    connected(account)
    send(account, "菜单")
    send(account, "0")
    chat = send(account, "帮我整理今天的工作")
    updates = {"status": run_status}
    if run_status == "waiting_input":
        updates.update(
            pending_input_kind="answer", pending_input_request_id=uuid.uuid4(),
            pending_input_expires_at=timezone.now() + timedelta(minutes=10),
        )
    Run.objects.filter(pk=chat.run_id).update(**updates)
    conversation_id = account.conversation_id
    create_run = Mock(side_effect=AssertionError("Opening a menu must not create another chat Run"))
    monkeypatch.setattr("app_center.wechat_assistant.backend.services.create_conversation_run", create_run)

    item = send(account, command)

    assert account.menu_state == "main"
    assert account.conversation_id == conversation_id
    assert item.state == "handled" and item.run_id is None
    assert "微信助手 · 功能菜单" in reply(item)
    assert item.replies.get().event_key == "menu"
    assert Run.objects.count() == 1
    assert Run.objects.get(pk=chat.run_id).status == run_status
    create_run.assert_not_called()


def test_invalid_numbers_expiry_and_reopening(account):
    connected(account)
    send(account, "菜单")
    assert "编号无效" in reply(send(account, "9" * 5000))
    assert account.menu_state == "main"
    Binding.objects.filter(pk=account.pk).update(menu_expires_at=timezone.now() - timedelta(seconds=1))
    assert "已过期" in reply(send(account, "2"))
    assert not Conversation.objects.exists() and not account.menu_state
    send(account, "菜单")
    send(account, "1")
    send(account, "/menu")
    assert account.menu_state == "main" and account.menu_data == {}


def test_expired_menu_allows_normal_chat(account):
    connected(account)
    send(account, "菜单")
    Binding.objects.filter(pk=account.pk).update(menu_expires_at=timezone.now() - timedelta(seconds=1))
    assert send(account, "你好").run_id


def test_agent_pagination_snapshot_and_switch(account):
    connected(account)
    configure(account, reset=True)
    account.refresh_from_db()
    old_conversation = account.conversation_id
    for number in range(12):
        add_agent(account, f"A-{number:02}")
    send(account, "菜单")
    send(account, "1")
    expiry = account.menu_expires_at
    first_choice = account.menu_data["agents"][0]
    assert "第一页" in reply(send(account, "上一页"))
    send(account, "下一页")
    assert account.menu_data["page"] == 1 and account.menu_expires_at == expiry
    assert "最后一页" in reply(send(account, "下一页"))
    send(account, "上一页")
    add_agent(account, "000-insert-before-list")
    Agent.objects.filter(pk=first_choice["id"]).update(name="Renamed choice")
    item = send(account, "1")
    assert account.agent_id == first_choice["id"]
    assert account.conversation_id != old_conversation
    assert Conversation.objects.filter(pk=old_conversation).exists()
    assert "Renamed choice" in reply(item)
    assert not account.menu_state and not item.run_id


def test_current_agent_keeps_conversation(account):
    connected(account)
    configure(account, reset=True)
    account.refresh_from_db()
    previous = account.conversation_id
    send(account, "菜单")
    item = send(account, "1")
    assert "（当前）" in reply(item)
    index = next(i for i, option in enumerate(account.menu_data["agents"], 1) if option["id"] == account.agent_id)
    send(account, str(index))
    assert account.conversation_id == previous and not account.menu_state


def test_switch_is_idempotent_and_following_number_is_chat(account):
    connected(account)
    target = add_agent(account, "A-target")
    send(account, "菜单")
    send(account, "1")
    send(account, "1", mid="switch-once")
    previous = account.conversation_id
    send(account, "1", mid="switch-once")
    assert account.agent_id == target.pk and account.conversation_id == previous
    assert Conversation.objects.count() == 1
    # Use the original deployed agent to verify a numeric ordinary chat can run.
    original = Agent.objects.get(slug="wechat-test")
    configure(account, original.pk)
    assert send(account, "4").run_id


def test_no_agents_and_missing_current_agent(account):
    connected(account)
    Agent.objects.filter(pk=account.agent_id).update(is_active=False)
    Binding.objects.filter(pk=account.pk).update(agent=None)
    send(account, "菜单")
    assert "没有可用" in reply(send(account, "1"))
    assert not account.menu_state
    send(account, "菜单")
    assert "当前智能体不可用" in reply(send(account, "2"))
    assert not Conversation.objects.exists()


def test_revoked_choice_does_not_switch(account):
    connected(account)
    target = add_agent(account, "A-target")
    previous = account.agent_id
    send(account, "菜单")
    send(account, "1")
    target_index = next(i for i, option in enumerate(account.menu_data["agents"], 1) if option["id"] == target.pk)
    Agent.objects.filter(pk=target.pk).update(is_active=False)
    assert "已不可用" in reply(send(account, str(target_index)))
    assert account.agent_id == previous and not account.menu_state


@pytest.mark.parametrize("choice", ["1", "2"])
def test_busy_menu_remains_readable_but_cannot_change_conversation(account, choice):
    connected(account)
    task = send(account, "执行任务")
    previous = account.conversation_id
    send(account, "菜单")
    assert "尚未完成" in reply(send(account, choice))
    assert not account.menu_state and account.conversation_id == previous
    send(account, "菜单")
    assert "未完成任务：有" in reply(send(account, "4"))
    send(account, "菜单")
    assert "执行任务" in reply(send(account, "3"))
    assert Run.objects.filter(pk=task.run_id).exists()


def test_task_started_after_agent_list_blocks_selection_and_web_reset(account):
    from apps.conversations.execution import create_conversation_run

    connected(account)
    configure(account, reset=True)
    account.refresh_from_db()
    send(account, "菜单")
    send(account, "1")
    create_conversation_run(account.user, account.conversation, "网页任务", "menu-web-task")
    with pytest.raises(ValidationError, match="当前任务尚未完成"):
        configure(account, reset=True)
    account.refresh_from_db()
    assert account.menu_state == "agents"
    assert "尚未完成" in reply(send(account, "1"))
    assert not account.menu_state


def test_agent_list_does_not_offer_foreign_or_inactive_agents(account):
    connected(account)
    inactive = add_agent(account, "inactive")
    inactive.is_active = False
    inactive.save()
    other = get_user_model().objects.create_user(username="menu-other")
    foreign = add_agent(account, "foreign")
    foreign.organization = other.owned_organizations.get()
    foreign.created_by = other
    foreign.save()
    send(account, "菜单")
    send(account, "1")
    ids = [option["id"] for option in account.menu_data["agents"]]
    assert inactive.pk not in ids and foreign.pk not in ids


def test_recent_tasks_cross_conversations_excludes_other_bindings(account, settings):
    connected(account)
    settings.WECHAT_ASSISTANT_PUBLIC_URL = "https://studio.example"
    for number in range(6):
        task = send(account, f"TASK-{number}")
        Run.objects.filter(pk=task.run_id).update(status="succeeded")
        configure(account, reset=True)
    other = Binding.objects.create(organization=account.organization, application=account.application,
                                   user=get_user_model().objects.create_user(username="task-other"))
    IncomingMessage.objects.create(organization=account.organization, binding=other, generation=other.generation,
                                   message_id="other-task", text="PRIVATE-TASK", run=task.run)
    send(account, "菜单")
    response = reply(send(account, "3"))
    assert "TASK-0" not in response and "PRIVATE-TASK" not in response
    for number in range(1, 6):
        assert f"TASK-{number}" in response
    assert "已完成" in response and "https://studio.example/chat?conversation=" in response
    assert "功能菜单" not in response


def test_duplicate_new_conversation_and_delivery_retry(account):
    connected(account)
    send(account, "菜单")
    item = send(account, "2", mid="new-conversation")
    previous = account.conversation_id
    send(account, "2", mid="new-conversation")
    assert account.conversation_id == previous and Conversation.objects.count() == 1
    assert item.replies.count() == 1
    OutgoingMessage.objects.exclude(incoming=item).update(state="sent")
    client = Mock()
    client.send.side_effect = WechatError(uncertain=True)
    deliver(account, "worker", client)
    stable_id = client.send.call_args.args[-1]
    item.replies.update(next_attempt_at=timezone.now())
    client.send.side_effect = None
    deliver(account, "worker", client)
    assert client.send.call_args.args[-1] == stable_id
    assert Conversation.objects.count() == 1 and not Run.objects.exists()


def test_control_and_reply_commit_atomically(account, monkeypatch):
    from .. import services

    connected(account)
    send(account, "菜单")
    enqueue = services.enqueue
    monkeypatch.setattr(services, "enqueue", Mock(side_effect=RuntimeError("simulated crash")))
    with pytest.raises(RuntimeError, match="simulated crash"):
        send(account, "2", mid="crashed-control")
    account.refresh_from_db()
    assert account.menu_state == "main" and not Conversation.objects.exists()
    pending = account.incoming.get(state="pending")
    assert not pending.replies.exists()
    monkeypatch.setattr(services, "enqueue", enqueue)
    dispatch_message(pending.pk, "worker")
    pending.refresh_from_db()
    assert pending.state == "handled" and pending.replies.count() == 1
    assert Conversation.objects.count() == 1


def test_restart_retains_snapshot(account):
    connected(account)
    send(account, "菜单")
    send(account, "1")
    original = account.menu_data
    Binding.objects.filter(pk=account.pk).update(lease_owner="restarted")
    recovered = Binding.objects.get(pk=account.pk)
    assert recovered.menu_data == original
    send(recovered, "1", owner="restarted")
    assert not recovered.menu_state


@pytest.mark.parametrize("action", ["new-conversation", "", "unbind", "login"])
def test_web_operations_clear_menu(account, action):
    connected(account)
    send(account, "菜单")
    client = APIClient()
    client.force_authenticate(account.user)
    root = f"/api/v1/organizations/{account.organization_id}/applications/{account.application_id}/wechat-assistant/"
    if action == "":
        result = client.put(root, {"agent_id": account.agent_id}, format="json")
    else:
        if action == "login":
            Binding.objects.filter(pk=account.pk).update(enabled=False, status="expired")
        result = client.post(root + action)
    assert result.status_code in (200, 202)
    account.refresh_from_db()
    assert not account.menu_state and not account.menu_data and account.menu_expires_at is None


def test_menu_respects_membership_revocation(account):
    connected(account)
    Membership.objects.filter(user=account.user, organization=account.organization).update(is_active=False)
    item = send(account, "菜单")
    assert item.replies.get().event_key == "rejected" and not account.menu_state


@pytest.mark.django_db(transaction=True)
def test_connector_allows_menu_after_agent_disabled(account):
    connected(account)
    target = add_agent(account, "A-available")
    Agent.objects.filter(pk=account.agent_id).update(is_active=False)
    Binding.objects.filter(pk=account.pk).update(lease_owner="", lease_until=timezone.now())
    factory = Mock()
    factory.return_value.updates.return_value = {"msgs": [message(1, item_list=[{"type": 1, "text_item": {"text": "菜单"}}])]}
    cycle(account.organization_id, account.pk, factory)
    account.refresh_from_db()
    assert account.enabled and account.menu_state == "main"
    factory.return_value.updates.return_value = {"msgs": [message(2, item_list=[{"type": 1, "text_item": {"text": "1"}}])]}
    Binding.objects.filter(pk=account.pk).update(next_poll_at=timezone.now())
    cycle(account.organization_id, account.pk, factory)
    account.refresh_from_db()
    assert account.menu_state == "agents"
    assert account.menu_data["agents"][0]["id"] == target.pk
    factory.return_value.updates.return_value = {"msgs": [message(3, item_list=[{"type": 1, "text_item": {"text": "1"}}])]}
    cycle(account.organization_id, account.pk, factory)
    account.refresh_from_db()
    assert account.agent_id == target.pk and account.conversation_id and not account.menu_state
