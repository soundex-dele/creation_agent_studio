from types import SimpleNamespace
from unittest.mock import Mock, MagicMock
import pytest
from .. import media
from ..provider import CollectionError, platform_media_url

ORIGIN = "https://v11-weba.douyinvod.com/original?sign=do-not-log"
MIRROR = "https://v5-dy-ov-experiment.zjcdn.com/media?sign=do-not-log-either"


def response(status, *, location=None, body=b"video-bytes"):
    value = MagicMock()
    value.__enter__.return_value = value
    value.is_redirect = status in (301, 302, 303, 307, 308)
    value.headers = {"Location": location} if location else {"Content-Length": str(len(body))}
    value.iter_content.return_value = iter([body])
    return value


@pytest.fixture
def network(monkeypatch, settings, tmp_path):
    settings.DOUYIN_MEDIA_ROOT = tmp_path
    session = Mock()
    monkeypatch.setattr(media.requests, "Session", lambda: session)
    monkeypatch.setattr(media.socket, "getaddrinfo", lambda *a, **k: [(None, None, None, None, ("8.8.8.8", 443))])
    return session


def test_known_dtk_regional_redirect_is_downloaded(network):
    network.get.side_effect = [response(302, location=MIRROR), response(200)]
    path = media.download(ORIGIN, "test/source.mp4", lambda: None)
    assert path.read_bytes() == b"video-bytes"
    assert [call.args[0] for call in network.get.call_args_list] == [ORIGIN, MIRROR]
    assert all(call.kwargs["allow_redirects"] is False for call in network.get.call_args_list)
    network.close.assert_called_once()


@pytest.mark.parametrize("target", [
    "https://douyinvod.com.evil.example/video?token=never-display",
    "https://v11-weba.douyinvod.com@evil.example/video?token=never-display",
    "file:///etc/passwd", "https://127.0.0.1/video?token=never-display",
    "https://v5.zjcdn.com:8443/video?token=never-display",
])
def test_unsafe_redirect_is_blocked_before_request(network, target):
    network.get.return_value = response(302, location=target)
    with pytest.raises(media.MediaAddressError) as error:
        media.download(ORIGIN, "test/source.mp4", lambda: None)
    assert "重定向" in str(error.value)
    assert "never-display" not in str(error.value) and "do-not-log" not in str(error.value)
    network.get.assert_called_once()
    assert not media.path_for("test/source.mp4").exists()


def test_private_dns_after_allowed_redirect_remains_blocked(network, monkeypatch):
    def resolve(host, *args, **kwargs):
        return [(None, None, None, None, ("127.0.0.1" if host.endswith("zjcdn.com") else "8.8.8.8", 443))]
    monkeypatch.setattr(media.socket, "getaddrinfo", resolve)
    network.get.return_value = response(302, location=MIRROR)
    with pytest.raises(media.MediaAddressError, match="非公共地址"):
        media.download(ORIGIN, "test/source.mp4", lambda: None)
    network.get.assert_called_once()


def test_refused_mirror_uses_next_candidate_without_requesting_bad_host(network):
    second = "https://v11-weba.douyinvod.com/second"
    network.get.side_effect = [response(302, location="https://outside.example/video?private=signed"), response(200)]
    client = SimpleNamespace(media_headers=lambda: {}, detail=Mock())
    path = media.download_video([ORIGIN, second], client, "123", "test/source.mp4", lambda: None)
    assert path.read_bytes() == b"video-bytes"
    assert [call.args[0] for call in network.get.call_args_list] == [ORIGIN, second]
    client.detail.assert_not_called()


def test_all_mirrors_blocked_retains_safe_host_diagnostic(network):
    network.get.return_value = response(302, location="https://outside.example/video?private=signed")
    client = SimpleNamespace(media_headers=lambda: {}, detail=Mock(side_effect=CollectionError("auth")))
    with pytest.raises(media.MediaAddressError) as error:
        media.download_video([ORIGIN], client, "123", "test/source.mp4", lambda: None)
    assert "outside.example" in str(error.value)
    assert "private=signed" not in str(error.value)


def test_size_limit_is_not_treated_as_mirror_failure(network):
    large = response(200)
    large.headers["Content-Length"] = str(media.MAX_BYTES + 1)
    network.get.return_value = large
    client = SimpleNamespace(media_headers=lambda: {}, detail=Mock())
    with pytest.raises(ValueError, match="500 MB"):
        media.download_video([ORIGIN, MIRROR], client, "123", "test/source.mp4", lambda: None)
    network.get.assert_called_once()
    client.detail.assert_not_called()


def test_domain_boundaries_and_url_bytes_remain_intact():
    assert platform_media_url(MIRROR) == MIRROR
    for url in ("https://evilzjcdn.com/video", "https://zjcdn.com.evil.example/video", "https://@zjcdn.com/video"):
        assert platform_media_url(url) == ""


def test_redirect_loop_is_bounded_and_diagnostic_contains_no_signed_url(network):
    network.get.return_value = response(302, location=ORIGIN)
    with pytest.raises(media.MediaAddressError, match="重定向次数") as error:
        media.download(ORIGIN, "test/source.mp4", lambda: None)
    assert network.get.call_count == 5
    assert "do-not-log" not in str(error.value)
