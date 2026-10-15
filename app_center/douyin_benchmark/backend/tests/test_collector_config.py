import json
import importlib
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from django.apps import apps
from django.db import connection
from .test_douyin import ctx  # shared tenant/application fixture
from ..collector_config import config_for, invoke, LocalDTKClient
from ..models import Account, CollectorConfig, Subscription, Task
from ..provider import CollectionError
from core.observability import ProcessingFormatter, log_context

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
COOKIE = "ttwid=private-test-only; UIFID_TEMP=test-uifid; s_v_web_id=verify_test"


@pytest.mark.parametrize('single_tenant', [False, True])
def test_settings_shared_between_users_keep_clear(ctx, settings, single_tenant):
    if single_tenant:
        settings.SINGLE_TENANT_MODE = True
        settings.SINGLE_TENANT_ORGANIZATION_ID = str(ctx.org.pk)
        ctx.root = f'/api/v1/applications/{ctx.app.pk}/douyin-benchmark'
    url = ctx.root + "/collector-config"
    assert ctx.client.get(url).data["configured"] is False
    assert ctx.client.get(url).data["cookies"] == ""
    response = ctx.client.put(url, {"user_agent": UA, "cookies": COOKIE}, format="json")
    assert response.status_code == 200, response.data
    config = CollectorConfig.objects.get(owner=ctx.owner)
    assert config.cookies == COOKIE
    for result in [response, ctx.client.get(url)]:
        assert result.data["cookies"] == COOKIE
        assert result.data["has_cookies"] is True
        assert result["Cache-Control"] == "no-store"
    connection = ctx.client.get(ctx.root + "/connection")
    assert "private-test-only" not in json.dumps(connection.data, default=str)
    assert "cookies" not in connection.data
    assert ctx.client.get(ctx.root + "/connection").data["connected"] is True
    assert ctx.client.put(url, {"user_agent": UA, "cookies": "", "screen": "1440x900"}, format="json").status_code == 200
    config.refresh_from_db()
    assert config.screen == "1440x900" and config.cookies == COOKIE
    replacement = 'UIFID_TEMP=replacement-cookie'
    assert ctx.client.put(url, {"user_agent": UA, "cookies": replacement}, format="json").data["cookies"] == replacement
    assert ctx.client.get(url).data["cookies"] == replacement
    ctx.client.force_authenticate(ctx.reader)
    assert ctx.client.get(url).data["configured"] is True
    assert ctx.client.get(url).data["cookies"] == replacement
    assert ctx.client.get(ctx.root + "/connection").data["connected"] is True
    updated_ua = UA.replace('130.0.0.0', '131.0.0.0')
    assert ctx.client.put(url, {"user_agent": updated_ua, "cookies": ""}, format="json").status_code == 200
    assert CollectorConfig.objects.filter(application=ctx.app).count() == 1
    ctx.client.force_authenticate(ctx.owner)
    data = ctx.client.get(url).data
    assert data['user_agent'] == updated_ua and data['cookies'] == replacement
    ctx.client.force_authenticate(ctx.reader)
    assert ctx.client.delete(url).status_code == 204
    assert ctx.client.get(url).data["cookies"] == ""
    assert not CollectorConfig.objects.filter(pk=config.pk).exists()
    ctx.client.force_authenticate(ctx.owner)
    assert ctx.client.delete(url).status_code == 204
    assert ctx.client.get(url).data["cookies"] == ""
    assert ctx.client.get(ctx.root + "/connection").data["code"] == "not_configured"


def test_existing_cookies_migration_roundtrip(ctx, settings):
    migration = importlib.import_module('app_center.douyin_benchmark.backend.migrations.0010_collector_cookies_plaintext')
    config = CollectorConfig.objects.create(organization=ctx.org, application=ctx.app, owner=ctx.owner,
                                           user_agent=UA, cookies=COOKIE)
    schema_editor = SimpleNamespace(connection=connection)
    migration.encrypt_cookies(apps, schema_editor)
    config.refresh_from_db()
    assert config.cookies != COOKIE
    assert 'private-test-only' not in config.cookies
    migration.decrypt_cookies(apps, schema_editor)
    config.refresh_from_db()
    assert config.cookies == COOKIE
    settings.SECRET_KEY = 'new-key-after-migration'
    assert ctx.client.get(ctx.root + '/collector-config').data['cookies'] == COOKIE


def test_existing_cookies_migration_rejects_unreadable_values(ctx):
    migration = importlib.import_module('app_center.douyin_benchmark.backend.migrations.0010_collector_cookies_plaintext')
    config = CollectorConfig.objects.create(organization=ctx.org, application=ctx.app, owner=ctx.owner,
                                           user_agent=UA, cookies='unreadable-old-value')
    with pytest.raises(RuntimeError, match='original SECRET_KEY'):
        migration.decrypt_cookies(apps, SimpleNamespace(connection=connection))
    config.refresh_from_db()
    assert config.cookies == 'unreadable-old-value'


def test_invalid_config_preserves_saved_value(ctx):
    url = ctx.root + "/collector-config"
    assert ctx.client.put(url, {"user_agent": UA, "cookies": COOKIE}, format="json").status_code == 200
    before = CollectorConfig.objects.get().cookies
    for body in [{"user_agent": "Safari", "cookies": COOKIE}, {"user_agent": UA, "cookies": "ttwid=secret-invalid"},
                 {"user_agent": UA, "cookies": COOKIE, "timezone": "invalid"}]:
        response = ctx.client.put(url, body, format="json")
        assert response.status_code == 400
        assert "secret-invalid" not in str(response.data) and "private-test-only" not in str(response.data)
    assert CollectorConfig.objects.get().cookies == before


def test_local_requests_from_different_users_use_shared_config(ctx, monkeypatch):
    ctx.client.put(ctx.root + "/collector-config", {"user_agent": UA, "cookies": COOKIE}, format="json")
    call = Mock(return_value={"platform": "douyin", "uid": "1", "sec_uid": "author", "nickname": "name"})
    monkeypatch.setattr("app_center.douyin_benchmark.backend.collector_config.invoke", call)
    client = LocalDTKClient(account=ctx.account)
    assert client.media_headers() == {"User-Agent": UA, "Referer": "https://www.douyin.com/"}
    assert client.profile(ctx.account.source_url)["platform_id"] == "author"
    assert call.call_args.args[0] == "profile" and call.call_args.args[1]["cookies"] == COOKIE
    other = Account.objects.create(organization=ctx.org, application=ctx.app, owner=ctx.reader,
                                   source_url='https://www.douyin.com/user/OTHER')
    other_client = LocalDTKClient(account=other)
    other_client.profile(other.source_url)
    assert call.call_args.args[1]['cookies'] == COOKIE
    assert call.call_args.args[1]['user_agent'] == UA
    # Sharing collector credentials does not share users' account libraries.
    ctx.client.force_authenticate(ctx.reader)
    assert ctx.client.get(ctx.url).status_code == 404
    CollectorConfig.objects.all().delete()
    with pytest.raises(CollectionError, match="采集设置"):
        client.detail("123")


def test_shared_config_does_not_cross_application_or_organization(ctx):
    from apps.applications.models import Application
    config = CollectorConfig.objects.create(organization=ctx.org, application=ctx.app, owner=ctx.owner,
                                           user_agent=UA, cookies=COOKIE)
    other_app = Application.objects.create(organization=ctx.org, category=ctx.app.category, name='Other',
                                          slug='other-collector-test', created_by=ctx.owner, kind='custom', visibility='organization')
    assert config_for(other_app) is None
    other_org = ctx.reader.owned_organizations.get()
    assert config_for(Application(organization=other_org, pk=ctx.app.pk)) is None
    assert config_for(ctx.app).pk == config.pk
    ctx.client.force_authenticate(None)
    assert ctx.client.get(ctx.root + '/collector-config').status_code in (401, 403)


def test_shared_config_survives_last_editor_deletion(ctx):
    config = CollectorConfig.objects.create(organization=ctx.org, application=ctx.app, owner=ctx.reader,
                                           user_agent=UA, cookies=COOKIE)
    # The fixture user owns an organization, whose FK intentionally protects deletion.
    ctx.reader.owned_organizations.all().delete()
    ctx.reader.delete()
    config.refresh_from_db()
    assert config.owner_id is None and config.cookies == COOKIE


def test_shared_config_supports_other_users_subscriptions_and_clear(ctx):
    from django.utils import timezone
    from ..subscriptions import dispatch_due
    CollectorConfig.objects.create(organization=ctx.org, application=ctx.app, owner=ctx.owner,
                                   user_agent=UA, cookies=COOKIE)
    own_subscription = Subscription.objects.create(organization=ctx.org, application=ctx.app, owner=ctx.owner,
                                                   account=ctx.account, enabled=True, next_run_at=timezone.now())
    other = Account.objects.create(organization=ctx.org, application=ctx.app, owner=ctx.reader,
                                   source_url='https://www.douyin.com/user/OTHER')
    ctx.client.force_authenticate(ctx.reader)
    response = ctx.client.post(ctx.root + '/subscriptions', {'account': str(other.pk), 'enabled': True}, format='json')
    assert response.status_code == 201, response.data
    subscription = Subscription.objects.get(pk=response.data['id'])
    dispatch_due()
    task = Task.objects.get(input__subscription_id=str(subscription.pk))
    assert task.owner_id == ctx.reader.pk
    ctx.client.force_authenticate(ctx.owner)
    assert ctx.client.delete(ctx.root + '/collector-config').status_code == 204
    for row in (own_subscription, subscription):
        row.refresh_from_db()
        assert not row.enabled and row.next_run_at is None
    task.run.refresh_from_db()
    assert task.run.status in ('cancelled', 'cancelling')


def test_subprocess_protocol_and_cancel(monkeypatch):
    process = Mock(returncode=0)
    process.communicate.return_value = ('{"data":{"valid":true}}', None)
    process.poll.return_value = 0
    popen = Mock(return_value=process)
    monkeypatch.setattr("app_center.douyin_benchmark.backend.collector_config.subprocess.Popen", popen)
    assert invoke("validate", {"cookies": COOKIE}) == {"valid": True}
    assert COOKIE not in str(popen.call_args)
    assert json.loads(process.communicate.call_args_list[0].kwargs["input"])["config"]["cookies"] == COOKIE
    process.poll.return_value = None
    cancelled = Mock(side_effect=[None, RuntimeError("cancelled")])
    with pytest.raises(RuntimeError, match="cancelled"):
        invoke("validate", {"cookies": COOKIE}, check=cancelled)
    process.kill.assert_called_once()


def test_missing_runtime_is_explicit(settings):
    settings.DOUYIN_DTK_PYTHON = "/missing/douyin/python"
    with pytest.raises(CollectionError) as exc:
        invoke("validate", {"cookies": COOKIE})
    assert exc.value.code == "runtime"


@pytest.mark.parametrize('diagnostic, expected', [
    ({'stage': 'transport', 'endpoint': 'douyin.author_profile', 'error_type': 'TransportFailure',
      'body': COOKIE, 'url': 'https://example.test/?token=private-token'},
     {'stage': 'transport', 'endpoint': 'douyin.author_profile', 'error_type': 'TransportFailure'}),
    ({'stage': COOKIE, 'endpoint': COOKIE, 'error_type': COOKIE, 'http_status': True}, {}),
    ({'stage': [], 'endpoint': {}, 'error_type': [], 'http_status': 999}, {}),
    ({'stage': 'response', 'endpoint': 'douyin.author_profile', 'http_status': 503},
     {'stage': 'response', 'endpoint': 'douyin.author_profile', 'http_status': 503}),
])
def test_subprocess_failure_logs_only_safe_diagnostics(monkeypatch, caplog, diagnostic, expected):
    process = Mock(returncode=0)
    process.communicate.return_value = (json.dumps({'error': 'unavailable', 'diagnostic': diagnostic}), None)
    process.poll.return_value = 0
    monkeypatch.setattr('app_center.douyin_benchmark.backend.collector_config.subprocess.Popen', Mock(return_value=process))
    with log_context(run_id='diagnostic-run'), pytest.raises(CollectionError) as caught:
        invoke('profile', {'cookies': COOKIE})
    assert caught.value.code == 'unavailable'
    assert caught.value.diagnostic == expected
    records = [record for record in caplog.records if record.getMessage().startswith('collector.failed')]
    assert len(records) == 1
    assert records[0].run_id == 'diagnostic-run'
    output = '\n'.join(ProcessingFormatter().format(record) for record in caplog.records)
    assert 'collector.failed code=unavailable' in output
    for key, value in expected.items():
        log_key = 'upstream_error_type' if key == 'error_type' else key
        assert f'{log_key}={value}' in output
    assert 'private-test-only' not in output and 'private-token' not in output


@pytest.mark.parametrize('code, attempts', [('unavailable', 2), ('timeout', 2), ('auth', 1), ('invalid', 1)])
def test_local_failure_retries_remain_bounded(monkeypatch, code, attempts):
    prefix = 'app_center.douyin_benchmark.backend.collector_config.'
    monkeypatch.setattr(prefix + 'config_for', lambda *_: None)
    monkeypatch.setattr(prefix + 'private_config', lambda *_: {'cookies': COOKIE})
    monkeypatch.setattr(prefix + 'time.sleep', lambda *_: None)
    call = Mock(side_effect=CollectionError(code))
    monkeypatch.setattr(prefix + 'invoke', call)
    with pytest.raises(CollectionError) as caught:
        LocalDTKClient().profile('https://www.douyin.com/user/TEST/')
    assert caught.value.code == code
    assert call.call_count == attempts
