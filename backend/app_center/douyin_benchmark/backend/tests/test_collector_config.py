import json
from unittest.mock import Mock
import pytest
from .test_douyin import ctx  # shared tenant/application fixture
from ..collector_config import cipher, invoke, LocalDTKClient
from ..models import CollectorConfig
from ..provider import CollectionError
from core.observability import ProcessingFormatter, log_context

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
COOKIE = "ttwid=private-test-only; UIFID_TEMP=test-uifid; s_v_web_id=verify_test"


def test_settings_encrypted_private_keep_clear(ctx):
    url = ctx.root + "/collector-config"
    assert ctx.client.get(url).data["configured"] is False
    response = ctx.client.put(url, {"user_agent": UA, "cookies": COOKIE}, format="json")
    assert response.status_code == 200, response.data
    config = CollectorConfig.objects.get(owner=ctx.owner)
    assert "private-test-only" not in config.encrypted_cookies
    assert cipher().decrypt(config.encrypted_cookies.encode()).decode() == COOKIE
    for result in [response, ctx.client.get(url), ctx.client.get(ctx.root + "/connection")]:
        assert "private-test-only" not in json.dumps(result.data, default=str)
        assert "cookies" not in result.data
    assert ctx.client.get(ctx.root + "/connection").data["connected"] is True
    assert ctx.client.put(url, {"user_agent": UA, "cookies": "", "screen": "1440x900"}, format="json").status_code == 200
    config.refresh_from_db()
    assert config.screen == "1440x900" and cipher().decrypt(config.encrypted_cookies.encode()).decode() == COOKIE
    ctx.client.force_authenticate(ctx.reader)
    assert ctx.client.get(url).data["configured"] is False
    assert ctx.client.delete(url).status_code == 204
    assert CollectorConfig.objects.filter(pk=config.pk).exists()
    ctx.client.force_authenticate(ctx.owner)
    assert ctx.client.delete(url).status_code == 204
    assert ctx.client.get(ctx.root + "/connection").data["code"] == "not_configured"


def test_invalid_config_preserves_saved_value(ctx):
    url = ctx.root + "/collector-config"
    assert ctx.client.put(url, {"user_agent": UA, "cookies": COOKIE}, format="json").status_code == 200
    before = CollectorConfig.objects.get().encrypted_cookies
    for body in [{"user_agent": "Safari", "cookies": COOKIE}, {"user_agent": UA, "cookies": "ttwid=secret-invalid"},
                 {"user_agent": UA, "cookies": COOKIE, "timezone": "invalid"}]:
        response = ctx.client.put(url, body, format="json")
        assert response.status_code == 400
        assert "secret-invalid" not in str(response.data) and "private-test-only" not in str(response.data)
    assert CollectorConfig.objects.get().encrypted_cookies == before


def test_local_requests_use_current_personal_config(ctx, monkeypatch):
    ctx.client.put(ctx.root + "/collector-config", {"user_agent": UA, "cookies": COOKIE}, format="json")
    call = Mock(return_value={"platform": "douyin", "uid": "1", "sec_uid": "author", "nickname": "name"})
    monkeypatch.setattr("app_center.douyin_benchmark.backend.collector_config.invoke", call)
    client = LocalDTKClient(account=ctx.account)
    assert client.media_headers() == {"User-Agent": UA, "Referer": "https://www.douyin.com/"}
    assert client.profile(ctx.account.source_url)["platform_id"] == "author"
    assert call.call_args.args[0] == "profile" and call.call_args.args[1]["cookies"] == COOKIE
    CollectorConfig.objects.all().delete()
    with pytest.raises(CollectionError, match="采集设置"):
        client.detail("123")


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
