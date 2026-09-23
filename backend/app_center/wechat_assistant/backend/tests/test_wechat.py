import hashlib
import json
import logging
import uuid
from datetime import timedelta
from unittest.mock import Mock

import httpx
import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import IntegrityError, transaction, connection
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework.exceptions import ValidationError

from apps.agents.models import Agent, AgentCategory
from apps.applications.models import Application
from apps.conversations.models import Conversation
from apps.enterprise.models import Membership, QuotaPolicy
from modules.catalog.models import AgentRevision, AgentDeployment
from modules.catalog.services import canonical_content_hash
from modules.execution.models import Run
from ..connector import claim, cycle, deliver, login_step, process_pending
from ..models import Binding, IncomingMessage, OutgoingMessage
from ..protocol import WechatClient, WechatError, seal, unseal, trusted_base, BASE_URL
from ..services import collect_results, configure, dispatch_message, enqueue, start_login, store_updates, unbind


@pytest.fixture
def account(db, tmp_path, settings):
    settings.AGENT_WORKSPACE_ROOT = str(tmp_path / "workspaces")
    user = get_user_model().objects.create_user(username="wechat-owner")
    org = user.owned_organizations.get()
    call_command("sync_app_center", package="wechat-assistant", organization_id=str(org.id))
    app = Application.objects.get(organization=org, slug="wechat-assistant")
    category, _ = AgentCategory.objects.get_or_create(slug="wechat-tests", defaults={"name": "Wechat tests"})
    agent = Agent.objects.create(name="Text agent", slug="wechat-test", category=category, organization=org, created_by=user, visibility="organization")
    definition = {"system_prompt": "Test text assistant"}
    revision = AgentRevision.objects.create(organization=org, agent=agent, revision_no=1, content=definition, content_hash=canonical_content_hash(definition), created_by=user)
    AgentDeployment.objects.create(organization=org, agent=agent, revision=revision, updated_by=user)
    binding = Binding.objects.create(organization=org, application=app, user=user, agent=agent)
    return binding


def connected(binding, owner="worker"):
    binding.bot_id = "bot-one"
    binding.peer_id = "peer-one"
    binding.credentials = seal({"token": "secret-bot-token", "base_url": BASE_URL})
    binding.enabled = True
    binding.status = "connected"
    binding.save()
    assert claim(binding.pk, owner)
    binding.refresh_from_db()
    return binding


def message(mid=1, **kwargs):
    return {"message_id": mid, "message_type": 1, "from_user_id": "peer-one", "to_user_id": "bot-one", "context_token": "secret-context", "item_list": [{"type": 1, "text_item": {"text": "hello"}}], **kwargs}


def ingest(binding, msgs=None, owner="worker"):
    store_updates(binding.pk, owner, binding.generation, {"msgs": [message()] if msgs is None else msgs, "get_updates_buf": "cursor-1"})
    return IncomingMessage.objects.filter(binding=binding).first()


def test_protocol_headers_and_text_body():
    seen = []
    def respond(request):
        seen.append(request)
        return httpx.Response(200, json={"ret": 0})
    client = WechatClient(token="secret", transport=httpx.MockTransport(respond))
    client.send("peer", "context", "hello", "stable-id")
    assert seen[0].headers["Authorization"] == "Bearer secret"
    payload = json.loads(seen[0].content)
    assert payload["msg"]["context_token"] == "context"
    assert payload["msg"]["client_id"] == "stable-id"
    assert payload["base_info"]["bot_agent"] == "AgentStudio/1.0.0"


@pytest.mark.parametrize("url", ["http://ilinkai.weixin.qq.com", "https://evil.test", "https://ilinkai.weixin.qq.com.evil.test", "https://u:p@ilinkai.weixin.qq.com", "https://ilinkai.weixin.qq.com:123", "https://ilinkai.weixin.qq.com:bad", "https://127.0.0.1", "https://ilinkai.weixin.qq.com/path"])
def test_untrusted_hosts_rejected(url):
    with pytest.raises(WechatError):
        trusted_base(url)


def test_errors_never_include_server_secrets():
    client = WechatClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"errcode": -14, "errmsg": "secret"})))
    with pytest.raises(WechatError) as err:
        client.updates("")
    assert err.value.expired
    assert "secret" not in str(err.value)


def test_qr_and_verification_parameters_are_not_logged(caplog):
    client = WechatClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"status": "wait"})))
    with caplog.at_level(logging.INFO, logger="httpx"):
        client.login_status("secret-qr-marker", "129876")
    assert "secret-qr-marker" not in caplog.text
    assert "129876" not in caplog.text


def test_login_and_no_credentials_in_api(account):
    client = APIClient(); client.force_authenticate(account.user)
    root = f"/api/v1/organizations/{account.organization_id}/applications/{account.application_id}/wechat-assistant/"
    result = client.post(root + "login")
    assert result.status_code == 202, result.data
    account.refresh_from_db()
    assert claim(account.pk, "worker")
    factory = Mock()
    factory.return_value.qrcode.return_value = {"qrcode": "secret-qr", "qrcode_img_content": "https://weixin.qq.com/scan"}
    login_step(account, "worker", factory)
    account.refresh_from_db()
    assert account.status == "wait"
    factory.return_value.login_status.return_value = {"status": "need_verifycode"}
    login_step(account, "worker", factory)
    account.refresh_from_db()
    assert account.status == "need_verifycode"
    result = client.post(root + "verify", {"login_id": str(account.login_id), "code": "123456"}, format="json")
    assert result.status_code == 202
    account.refresh_from_db()
    factory.return_value.login_status.return_value = {"status": "confirmed", "bot_token": "secret-bot-token", "ilink_bot_id": "bot-one", "ilink_user_id": "peer-one", "baseurl": BASE_URL}
    login_step(account, "worker", factory)
    factory.return_value.login_status.assert_called_with("secret-qr", "123456")
    account.refresh_from_db()
    assert account.enabled
    assert unseal(account.credentials)["token"] == "secret-bot-token"
    result = client.get(root)
    assert result.status_code == 200
    assert "secret" not in json.dumps(result.data)
    assert "credentials" not in result.data
    assert result.data["qr_content"] == ""


def test_login_expiry_redirect_and_stale_confirmation(account):
    snapshot = start_login(account)
    assert claim(account.pk, "worker")
    factory = Mock()
    factory.return_value.qrcode.return_value = {"qrcode": "qr", "qrcode_img_content": "https://weixin.qq.com/qr"}
    login_step(snapshot, "worker", factory)
    account.refresh_from_db()
    factory.return_value.login_status.return_value = {"status": "scaned_but_redirect", "redirect_host": "a.ilinkai.weixin.qq.com"}
    login_step(account, "worker", factory)
    account.refresh_from_db()
    assert unseal(account.login_data)["base_url"] == "https://a.ilinkai.weixin.qq.com"
    snapshot = account
    unbind(account)
    factory.return_value.login_status.return_value = {"status": "confirmed", "bot_token": "x", "ilink_bot_id": "bot", "ilink_user_id": "p", "baseurl": BASE_URL}
    login_step(snapshot, "worker", factory)
    account.refresh_from_db()
    assert not account.enabled
    account = start_login(account)
    account.login_expires_at = timezone.now() - timedelta(seconds=1); account.save()
    login_step(account, "worker", factory)
    account.refresh_from_db()
    assert account.status == "expired"


def test_api_personal_isolation_and_configuration(account):
    client = APIClient(); client.force_authenticate(account.user)
    root = f"/api/v1/organizations/{account.organization_id}/applications/{account.application_id}/wechat-assistant/"
    result = client.put(root, {"agent_id": account.agent_id}, format="json")
    assert result.status_code == 200, result.data
    other = get_user_model().objects.create_user(username="other-wechat")
    Membership.objects.create(user=other, organization=account.organization, role="viewer")
    client.force_authenticate(other)
    assert client.get(root).status_code in (204, 404)
    assert client.post(root + "unbind").status_code == 404
    other_org = other.owned_organizations.get()
    wrong_root = root.replace(str(account.organization_id), str(other_org.id))
    assert client.get(wrong_root).status_code == 404


def test_first_configuration_creates_binding(account):
    account.delete()
    user = get_user_model().objects.get(username="wechat-owner")
    org = user.owned_organizations.get(); app = Application.objects.get(organization=org, slug="wechat-assistant")
    agent = Agent.objects.get(organization=org, slug="wechat-test")
    client = APIClient(); client.force_authenticate(user)
    root = f"/api/v1/organizations/{org.id}/applications/{app.id}/wechat-assistant/"
    assert client.get(root).status_code == 204
    result = client.put(root, {"agent_id": agent.id}, format="json")
    assert result.status_code == 200, result.data
    assert result.data["conversation_id"]


def test_global_bot_uniqueness(account):
    connected(account)
    other = get_user_model().objects.create_user(username="second-owner")
    with pytest.raises(IntegrityError), transaction.atomic():
        Binding.objects.create(organization=other.owned_organizations.get(), application=account.application, user=other, bot_id=account.bot_id)


def test_dedup_private_sender_and_cursor(account):
    connected(account)
    bad = [message(2, from_user_id="stranger"), message(3, group_id="group"), message(4, message_type=2), message(5, to_user_id="different-bot")]
    ingest(account, [message(), message(), *bad])
    assert IncomingMessage.objects.count() == 1
    account.refresh_from_db(); assert account.cursor == "cursor-1"
    assert "secret-context" not in IncomingMessage.objects.get().context_token


def test_full_text_run_replay_busy_and_terminal_delivery(account):
    connected(account)
    item = ingest(account)
    dispatch_message(item.id, "worker")
    item.refresh_from_db(); assert item.run_id
    dispatch_message(item.id, "worker")
    assert Run.objects.filter(source_type="conversation").count() == 1
    account.refresh_from_db()
    assert account.conversation.agent_locked
    with pytest.raises(ValidationError):
        configure(account, reset=True)
    ingest(account, [message(2)])
    second = IncomingMessage.objects.get(message_id=hashlib.sha256(b"bot-one:2").hexdigest())
    dispatch_message(second.id, "worker")
    assert second.replies.get().event_key == "busy"
    run = item.run
    run.status = "succeeded"; run.output_summary = {"result": "答案" * 1100}; run.save()
    collect_results(account.pk, "worker", account.generation)
    collect_results(account.pk, "worker", account.generation)
    assert item.replies.filter(event_key="terminal").count() == 3
    client = Mock()
    deliver(account, "worker", client)
    assert OutgoingMessage.objects.filter(state="sent").count() == 4
    assert client.send.call_count == 4
    assert "".join(r.text for r in item.replies.order_by("part")) == "答案" * 1100
    # Next turn resumes the same persistent conversation and its history.
    ingest(account, [message(3)])
    third = IncomingMessage.objects.get(message_id=hashlib.sha256(b"bot-one:3").hexdigest())
    dispatch_message(third.id, "worker"); third.refresh_from_db()
    assert third.conversation_id == item.conversation_id


def test_non_text_and_revoked_agent_do_not_run(account):
    connected(account)
    item = ingest(account, [message(item_list=[{"type": 2}])])
    dispatch_message(item.id, "worker")
    assert item.replies.get().event_key == "unsupported"
    assert not Run.objects.filter(source_type="conversation").exists()
    account.agent.is_active = False; account.agent.save()
    ingest(account, [message(2)])
    second = IncomingMessage.objects.get(message_id=hashlib.sha256(b"bot-one:2").hexdigest())
    dispatch_message(second.id, "worker")
    assert second.replies.get().event_key == "rejected"
    assert not Run.objects.filter(source_type="conversation").exists()


def test_waiting_input_notifies_once_then_resumes(account):
    connected(account); item = ingest(account); dispatch_message(item.id, "worker"); item.refresh_from_db()
    Run.objects.filter(pk=item.run_id).update(status="waiting_input", pending_input_kind="answer", pending_input_request_id=uuid.uuid4(), pending_input_expires_at=timezone.now() + timedelta(minutes=10))
    collect_results(account.pk, "worker", account.generation)
    collect_results(account.pk, "worker", account.generation)
    assert item.replies.count() == 1
    assert "localhost" not in item.replies.get().text
    Run.objects.filter(pk=item.run_id).update(status="succeeded", pending_input_kind="", pending_input_request_id=None, pending_input_expires_at=None, output_summary={"result": "done"})
    collect_results(account.pk, "worker", account.generation)
    assert item.replies.count() == 2


def test_retry_keeps_client_id_and_does_not_reexecute(account):
    connected(account); item = ingest(account); dispatch_message(item.id, "worker"); item.refresh_from_db()
    enqueue(item, "test", "reply")
    client = Mock(); client.send.side_effect = WechatError(uncertain=True)
    deliver(account, "worker", client)
    reply = item.replies.get(); assert reply.state == "retry"; assert reply.attempts == 1
    stable_id = client.send.call_args.args[-1]
    OutgoingMessage.objects.filter(pk=reply.pk).update(next_attempt_at=timezone.now())
    client.send.side_effect = None
    deliver(account, "worker", client)
    assert client.send.call_args.args[-1] == stable_id
    assert Run.objects.filter(source_type="conversation").count() == 1


def test_unbind_fences_inflight_response_and_retains_history(account):
    connected(account); item = ingest(account); dispatch_message(item.id, "worker"); item.refresh_from_db()
    enqueue(item, "test", "reply")
    unbind(account)
    store_updates(account.pk, "worker", account.generation, {"msgs": [message(2)], "get_updates_buf": "late"})
    deliver(account, "worker", Mock())
    account.refresh_from_db()
    assert not account.credentials and not account.enabled
    assert item.replies.get().state == "discarded"
    assert IncomingMessage.objects.count() == 1
    assert Conversation.objects.filter(pk=item.conversation_id).exists()
    assert Run.objects.filter(pk=item.run_id, status="queued").exists()


def test_lease_and_resume_persisted_inbox(account):
    connected(account)
    assert not claim(account.pk, "second")
    item = ingest(account)
    Binding.objects.filter(pk=account.pk).update(lease_until=timezone.now() - timedelta(seconds=1))
    assert claim(account.pk, "second")
    process_pending(account, "worker")
    item.refresh_from_db(); assert not item.run_id
    process_pending(account, "second")
    item.refresh_from_db(); assert item.run_id


def test_sync_idempotent_and_discovery(account):
    call_command("validate_app_center")
    call_command("sync_app_center", package="wechat-assistant", organization_id=str(account.organization_id))
    assert Application.objects.filter(organization=account.organization, slug="wechat-assistant").count() == 1


@pytest.mark.parametrize("resource", ["user", "organization", "application", "membership"])
def test_revoked_access_stops_dispatch(account, resource):
    connected(account)
    item = ingest(account)
    if resource == "membership":
        Membership.objects.filter(user=account.user, organization=account.organization).update(is_active=False)
    else:
        obj = getattr(account, resource)
        obj.is_active = False
        obj.save(update_fields=["is_active"])
    dispatch_message(item.id, "worker")
    item.refresh_from_db()
    assert item.run_id is None
    assert item.replies.get().event_key == "rejected"


def test_same_bot_reauthorization_preserves_pending_and_cursor(account):
    connected(account)
    item = ingest(account)
    old_generation = account.generation
    Binding.objects.filter(pk=account.pk).update(enabled=False, status="expired")
    account = start_login(account)
    factory = Mock()
    factory.return_value.qrcode.return_value = {"qrcode": "qr", "qrcode_img_content": "https://weixin.qq.com/scan"}
    login_step(account, "worker", factory)
    account.refresh_from_db()
    factory.return_value.login_status.return_value = {"status": "confirmed", "bot_token": "renewed-token", "ilink_bot_id": "bot-one", "ilink_user_id": "peer-one", "baseurl": BASE_URL}
    login_step(account, "worker", factory)
    account.refresh_from_db()
    assert account.generation == old_generation
    assert account.cursor == "cursor-1"
    ingest(account)
    assert IncomingMessage.objects.count() == 1
    dispatch_message(item.pk, "worker")
    item.refresh_from_db()
    assert item.run_id


def test_reply_retry_limit_survives_crash(account):
    connected(account); item = ingest(account); enqueue(item, "terminal", "done")
    reply = item.replies.get()
    OutgoingMessage.objects.filter(pk=reply.pk).update(state="sending", attempts=5)
    client = Mock()
    deliver(account, "worker", client)
    client.send.assert_not_called()
    reply.refresh_from_db()
    assert reply.state == "failed"


def test_quota_rejection_is_handled_without_background_reexecution(account):
    connected(account)
    QuotaPolicy.objects.update_or_create(organization=account.organization, defaults={"max_concurrent_runs": 0})
    item = ingest(account)
    dispatch_message(item.id, "worker")
    item.refresh_from_db()
    assert item.state == "handled" and item.run_id is None
    assert item.replies.get().event_key == "quota"


@pytest.mark.django_db(transaction=True)
def test_mock_transport_cycle_survives_restart(account, monkeypatch):
    # Real HTTP serialization with a fake upstream; DB state persists across cycles.
    connected(account)
    Binding.objects.filter(pk=account.pk).update(lease_owner="", lease_until=timezone.now())
    requests = []
    def respond(request):
        assert not connection.in_atomic_block, "HTTP must not hold a database transaction"
        requests.append(request)
        if request.url.path.endswith("getupdates"):
            return httpx.Response(200, json={"ret": 0, "msgs": [message()], "get_updates_buf": "next"})
        return httpx.Response(200, json={"ret": 0})
    factory = lambda base, token="": WechatClient(base, token, transport=httpx.MockTransport(respond))
    cycle(account.organization_id, account.pk, factory)
    item = IncomingMessage.objects.get(); assert item.run_id
    Run.objects.filter(pk=item.run_id).update(status="succeeded", output_summary={"result": "transport reply"})
    cycle(account.organization_id, account.pk, factory)
    sent = [r for r in requests if r.url.path.endswith("sendmessage")]
    assert len(sent) == 1
    assert json.loads(sent[0].content)["msg"]["item_list"][0]["text_item"]["text"] == "transport reply"
    assert IncomingMessage.objects.count() == 1
