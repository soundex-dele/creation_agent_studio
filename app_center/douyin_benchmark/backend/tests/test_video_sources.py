from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
import requests
from .test_douyin import ctx, claim, content, post
from ..models import Task, Work
from ..provider import normalize_work, video_urls, work_web_url, CollectionError
from ..media import download_video, checked_media_url
from ...runtime import execute

VIDEO_ID = "7536599534051626299"
PLAY_URL = "https://v3.douyinvod.com/real-file.mp4?token=test-only"


def video():
    return {**content(), "content_id": VIDEO_ID, "web_url": f"https://www.douyin.com/video/{VIDEO_ID}",
        "media": {"video": {"url": PLAY_URL, "urls": [PLAY_URL], "watermark": False},
                  "streams": [{"url": "https://v3.douyinvod.com/watermarked.mp4", "watermark": True}]}}


def test_file_urls_and_source_pages_are_distinct():
    item = normalize_work(video())
    assert item["platform_id"] == VIDEO_ID
    assert item["url"] == f"https://www.douyin.com/?modal_id={VIDEO_ID}"
    assert item["_media_urls"] == [PLAY_URL]
    assert video_urls({"kind": "video", "web_url": item["url"]}) == []
    album = normalize_work({**video(), "kind": "image_album"})
    assert album["url"] == f"https://www.douyin.com/?modal_id={VIDEO_ID}"
    assert album["_media_urls"] == []
    assert work_web_url({**album, "url": "https://evil.example"}) == album["url"]


@pytest.mark.parametrize("kind,slug", [("video", "video"), ("image_album", "note")])
def test_historical_source_links_use_web_modal(kind, slug):
    platform_id = "7449986776569040166"
    assert work_web_url({"platform_id": platform_id, "kind": kind,
        "url": f"https://www.douyin.com/{slug}/{platform_id}"}) == (
        f"https://www.douyin.com/?modal_id={platform_id}")


@pytest.mark.parametrize("platform_id", [None, "", "１２３", "123&modal_id=456", "1e19"])
def test_source_links_require_an_exact_numeric_id(platform_id):
    assert work_web_url({"platform_id": platform_id, "url": PLAY_URL}) == ""


def test_collected_media_survives_without_entering_analysis_evidence(ctx, monkeypatch):
    monkeypatch.setattr("app_center.douyin_benchmark.runtime.DTKClient", lambda **kw: SimpleNamespace(
        profile=lambda url: {"platform_id": "author", "name": "读书"},
        pages=lambda *args: iter([([normalize_work(video())], True)])))
    execute(*claim(ctx.task))
    work = Work.objects.get(account=ctx.account)
    assert work.media_urls == [PLAY_URL]
    assert "token=test-only" not in str(work.metadata)
    assert "token=test-only" not in str(ctx.task.snapshots.get().data)
    result = ctx.client.get(ctx.url + "/works").data["items"][0]
    assert result["video_url"] == PLAY_URL and result["url"] != PLAY_URL
    # Old snapshots and analysis evidence must be corrected at read time too.
    snapshot = ctx.task.snapshots.get()
    snapshot.data["url"] = f"https://www.douyin.com/video/{VIDEO_ID}"
    snapshot.save(update_fields=["data"])
    assert ctx.client.get(ctx.url + "/works").data["items"][0]["url"] == f"https://www.douyin.com/?modal_id={VIDEO_ID}"
    analysis = post(ctx, {"kind": "account"}, key="account-analysis")
    assert analysis.status_code == 201
    assert analysis.data["sources"][0]["url"] == f"https://www.douyin.com/?modal_id={VIDEO_ID}"
    task = Task.objects.get(pk=post(ctx, {"kind": "breakdown", "work_id": str(work.pk)}).data["id"])
    assert task.input["media_urls"] == [PLAY_URL]
    assert "token=test-only" not in str(task.input["metadata"])
    # Existing stored candidates must also use the new preference without recollection.
    work.media_urls = ["https://v26-web.douyinvod.com/a", "https://v11-weba.douyinvod.com/b"]
    work.save(update_fields=["media_urls"])
    assert ctx.client.get(ctx.url + "/works").data["items"][0]["video_url"] == work.media_urls[1]
    ctx.client.force_authenticate(ctx.reader)
    assert ctx.client.get(ctx.url + "/works").status_code == 404


def test_download_uses_list_media_without_requerying_detail(monkeypatch):
    download = Mock(return_value=Path("/test/video.mp4"))
    monkeypatch.setattr("app_center.douyin_benchmark.backend.media.download", download)
    client = SimpleNamespace(media_headers=lambda: {}, detail=Mock(side_effect=CollectionError("risk_control")))
    assert download_video([PLAY_URL], client, VIDEO_ID, "key", lambda: None) == Path("/test/video.mp4")
    client.detail.assert_not_called()
    assert download.call_args.args[0] == PLAY_URL


def test_expired_media_is_renewed_and_cancellation_is_not_retried(monkeypatch):
    download = Mock(side_effect=[requests.HTTPError("signed URL must stay private"), Path("/test/video.mp4")])
    monkeypatch.setattr("app_center.douyin_benchmark.backend.media.download", download)
    client = SimpleNamespace(media_headers=lambda: {}, detail=Mock(return_value=video()))
    assert download_video([PLAY_URL], client, VIDEO_ID, "key", lambda: None) == Path("/test/video.mp4")
    client.detail.assert_called_once_with(VIDEO_ID)
    client.detail.reset_mock()
    download.side_effect = InterruptedError("cancelled")
    with pytest.raises(InterruptedError):
        download_video([PLAY_URL], client, VIDEO_ID, "key", lambda: None)
    client.detail.assert_not_called()


def test_detail_id_must_match_and_failures_do_not_leak_signed_urls(monkeypatch):
    client = SimpleNamespace(media_headers=lambda: {}, detail=Mock(return_value={**video(), "content_id": "123"}))
    with pytest.raises(ValueError, match="ID 不匹配"):
        download_video([], client, VIDEO_ID, "key", lambda: None)
    client.detail.return_value = video()
    monkeypatch.setattr("app_center.douyin_benchmark.backend.media.download", Mock(side_effect=requests.HTTPError(PLAY_URL)))
    with pytest.raises(ValueError) as error:
        download_video([], client, VIDEO_ID, "key", lambda: None)
    assert "token=test-only" not in str(error.value)


def test_http_cdn_address_from_dtk_is_supported_with_private_ip_block(monkeypatch):
    monkeypatch.setattr("app_center.douyin_benchmark.backend.media.socket.getaddrinfo", lambda *a, **k: [(None, None, None, None, ("8.8.8.8", 80))])
    assert checked_media_url("http://v3.douyinvod.com/video") == "http://v3.douyinvod.com/video"
    monkeypatch.setattr("app_center.douyin_benchmark.backend.media.socket.getaddrinfo", lambda *a, **k: [(None, None, None, None, ("127.0.0.1", 80))])
    with pytest.raises(ValueError):
        checked_media_url("http://v3.douyinvod.com/video")


def test_diagnostic_only_displays_known_endpoint_and_http_status():
    error = CollectionError("signature", {"endpoint": "douyin.content_detail", "http_status": 403, "body": PLAY_URL})
    assert "视频详情，HTTP 403" in str(error)
    assert "token=" not in str(error)
    assert "token=" not in str(CollectionError("signature", {"endpoint": PLAY_URL, "http_status": 403}))


def test_v11_is_selected_before_storage_and_download_limits(monkeypatch):
    preferred = "https://v11-weba.douyinvod.com/video?sign=preserve%2Bme"
    other = [f"https://v26-web.douyinvod.com/{i}" for i in range(10)]
    detail = {**video(), "media": {"video": {"url": other[0], "urls": other + [preferred], "watermark": False}}}
    assert video_urls(detail) == [preferred, *other[:7]]
    download = Mock(return_value=Path("/test/video.mp4"))
    monkeypatch.setattr("app_center.douyin_benchmark.backend.media.download", download)
    client = SimpleNamespace(media_headers=lambda: {}, detail=Mock())
    download_video(other + [preferred], client, VIDEO_ID, "key", lambda: None)
    assert download.call_args.args[0] == preferred
    client.detail.assert_not_called()


def test_other_cdn_remains_a_fallback_if_preferred_cdn_fails(monkeypatch):
    preferred = "https://v11-weba.douyinvod.com/video"
    fallback = "https://v26-web.douyinvod.com/video"
    download = Mock(side_effect=[requests.HTTPError("unavailable"), Path("/test/video.mp4")])
    monkeypatch.setattr("app_center.douyin_benchmark.backend.media.download", download)
    client = SimpleNamespace(media_headers=lambda: {}, detail=Mock())
    assert download_video([fallback, preferred], client, VIDEO_ID, "key", lambda: None) == Path("/test/video.mp4")
    assert [call.args[0] for call in download.call_args_list] == [preferred, fallback]
    client.detail.assert_not_called()
