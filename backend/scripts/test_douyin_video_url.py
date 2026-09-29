"""Offline source-integration checks; no DTK server or Douyin account required."""

import json
import importlib.util
import sys
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

# The main application uses Python 3.11; this optional source integration has
# its own 3.12/3.13 runtime. Don't abort unrelated backend test discovery.
if not (3, 12) <= sys.version_info[:2] < (3, 14):
    raise unittest.SkipTest("DTK source integration requires the Python 3.12/3.13 runtime")
if any(importlib.util.find_spec(name) is None for name in ("httpx", "wreq", "pydantic", "structlog")):
    raise unittest.SkipTest("Install douyin_video_url.requirements.txt in the DTK runtime")

import httpx
import douyin_video_url as script
from dtk.core.errors import InvalidParam
from dtk.transport.wreq_transport import WreqTransport

FIXTURES = script.SOURCE.parent / "tests/fixtures/douyin"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
COOKIES = {"ttwid": "test-only", "UIFID_TEMP": "test-uifid", "s_v_web_id": "verify_test"}
POST_ID = "7000000000000000001"


class RecordingClient:
    def __init__(self, fixture):
        self.body = (FIXTURES / fixture).read_bytes()
        self.calls = []

    async def request(self, method, url, **kwargs):
        self.calls.append((url, kwargs))
        body = self.body

        class Response:
            status = 200
            headers = {"content-type": "application/json"}

            async def bytes(self):
                return body

        return Response()


class SourceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        script.configure(level="critical")
        self.identity = script.make_identity(COOKIES, UA)

    async def fetch_fixture(self, name):
        client = RecordingClient(name)
        transport = WreqTransport(client_factory=lambda options: client)
        try:
            result = await script.fetch_video(POST_ID, self.identity, transport=transport)
            return result, client.calls
        finally:
            await transport.close()

    async def test_real_signer_transport_and_parser(self):
        result, calls = await self.fetch_fixture("video_normal.json")
        self.assertEqual(result["content_id"], POST_ID)
        self.assertEqual(len(calls), 1)
        url, kwargs = calls[0]
        self.assertEqual(urlsplit(url).hostname, "www.douyin.com")
        self.assertEqual(urlsplit(url).path, "/aweme/v1/web/aweme/detail/")
        query = parse_qs(urlsplit(url).query)
        self.assertEqual(query["aweme_id"], [POST_ID])
        self.assertTrue(query["a_bogus"][0])
        self.assertTrue(query["x-secsdk-web-signature"][0])
        self.assertEqual(query["uifid"], [COOKIES["UIFID_TEMP"]])
        self.assertEqual(query["verifyFp"], [COOKIES["s_v_web_id"]])
        self.assertEqual(kwargs["cookies"], COOKIES)
        self.assertEqual(kwargs["headers"]["User-Agent"], UA)
        self.assertNotIn("query", kwargs)  # Signatures must not be re-encoded.
        payload = json.loads((FIXTURES / "video_normal.json").read_text())
        self.assertEqual(result["url"], payload["aweme_detail"]["video"]["play_addr"]["url_list"][0])
        for watermarked in payload["aweme_detail"]["video"]["download_addr"]["url_list"]:
            self.assertNotIn(watermarked, result["urls"])

    async def test_risk_control_is_an_error(self):
        with self.assertRaises(script.VideoUrlError):
            await self.fetch_fixture("risk_control_captcha.json")

    async def test_empty_response_is_an_error(self):
        with self.assertRaises(script.VideoUrlError):
            await self.fetch_fixture("risk_control_empty.json")

    async def test_album_rejected(self):
        with self.assertRaisesRegex(script.VideoUrlError, "图集"):
            await self.fetch_fixture("video_image_album.json")

    async def test_private_video_has_no_download(self):
        with self.assertRaisesRegex(script.VideoUrlError, "没有可用"):
            await self.fetch_fixture("video_private.json")

    async def test_full_url_and_id_need_no_network(self):
        self.assertEqual(await script.resolve_id(POST_ID, self.identity, 10), POST_ID)
        self.assertEqual(await script.resolve_id(
            f"分享 https://www.douyin.com/video/{POST_ID}", self.identity, 10), POST_ID)
        with self.assertRaises(InvalidParam):
            await script.resolve_id("123", self.identity, 10)

    async def test_short_link_redirect_and_cookie_isolation(self):
        calls = []
        def handler(request):
            calls.append(request)
            return httpx.Response(302, headers={
                "Location": f"https://www.iesdouyin.com/share/video/{POST_ID}/"})
        real_client = httpx.AsyncClient
        def factory(**kwargs):
            return real_client(**kwargs, transport=httpx.MockTransport(handler))
        with patch.object(script.httpx, "AsyncClient", side_effect=factory):
            result = await script.resolve_id("分享 https://v.douyin.com/example/", self.identity, 10)
        self.assertEqual(result, POST_ID)
        self.assertEqual(len(calls), 1)
        self.assertNotIn("cookie", calls[0].headers)

    async def test_external_redirect_rejected(self):
        def handler(request):
            return httpx.Response(302, headers={"Location": "https://example.com/video/1"})
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with patch.object(script.httpx, "AsyncClient", return_value=client):
            with self.assertRaises(script.DtkError):
                await script.resolve_id("https://v.douyin.com/example/", self.identity, 10)

    def test_cookie_formats_and_missing_signature_identity(self):
        for text in [json.dumps(COOKIES), "; ".join(f"{k}={v}" for k, v in COOKIES.items()),
                     json.dumps([{"name": k, "value": v} for k, v in COOKIES.items()])]:
            self.assertEqual(script.load_cookies(text), COOKIES)
        with self.assertRaisesRegex(script.VideoUrlError, "UIFID"):
            script.load_cookies("ttwid=only")

    def test_watermarked_only_not_selected(self):
        with self.assertRaisesRegex(script.VideoUrlError, "无水印"):
            script.video_urls({"kind": "video", "media": {"streams": [
                {"url": "https://cdn.example/watermark.mp4", "watermark": True}]}})

    def test_cookie_header_with_raw_json_and_equals(self):
        header = ('Cookie: browser_info={"width":1920,"height":1080}; '
                  'UIFID_TEMP=test-uifid; token=abc==; escaped=%7B%22x%22%3A1%7D')
        cookies = script.load_cookies(header)
        self.assertEqual(cookies["UIFID_TEMP"], "test-uifid")
        self.assertEqual(cookies["browser_info"], '{"width":1920,"height":1080}')
        self.assertEqual(cookies["token"], "abc==")
        self.assertEqual(cookies["escaped"], "%7B%22x%22%3A1%7D")

    def test_unparsed_cookie_is_not_reported_as_missing_uifid(self):
        with self.assertRaisesRegex(script.VideoUrlError, "未解析到 Cookie"):
            script.load_cookies("not-a-cookie")


if __name__ == "__main__":
    unittest.main()
