"""Run explicitly with .venv-dtk; exercises real DTK signing/parsing offline."""
import sys
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import test_douyin_video_url as fixtures
import collector


class CollectorSourceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        collector.configure(level="critical")

    async def fetch(self, endpoint, params, fixture):
        identity = collector.make_identity(fixtures.COOKIES, fixtures.UA)
        client = fixtures.RecordingClient(fixture)
        transport = collector.WreqTransport(client_factory=lambda options: client)
        try:
            result = await collector.request(endpoint, params, identity, transport)
            url, kwargs = client.calls[0]
            query = parse_qs(urlsplit(url).query)
            self.assertTrue(query['a_bogus'][0])
            self.assertTrue(query['x-secsdk-web-signature'][0])
            self.assertEqual(kwargs['cookies'], fixtures.COOKIES)
            self.assertEqual(kwargs['headers']['User-Agent'], fixtures.UA)
            return result, query
        finally:
            await transport.close()

    async def test_profile_and_pagination(self):
        result, _ = await self.fetch(collector.AUTHOR_PROFILE, {'sec_user_id': 'TEST'}, 'user_profile.json')
        self.assertTrue(result['uid'])
        first, _ = await self.fetch(collector.AUTHOR_POSTS, {'sec_user_id': 'TEST', 'count': 20}, 'user_posts_page1.json')
        self.assertTrue(first['items'])
        self.assertTrue(first['cursor'])
        second, query = await self.fetch(collector.AUTHOR_POSTS, {'sec_user_id': 'TEST', 'count': 20, 'cursor': first['cursor']}, 'user_posts_page1.json')
        self.assertNotEqual(query['max_cursor'], ['0'])
        self.assertEqual(first['items'][0]['content_id'], second['items'][0]['content_id'])

    async def test_detail(self):
        result, _ = await self.fetch(collector.CONTENT_DETAIL, {'aweme_id': fixtures.POST_ID}, 'video_normal.json')
        self.assertEqual(result['content_id'], fixtures.POST_ID)
        self.assertTrue(result['media']['video']['url'])
        self.assertIsNotNone(result['stats']['digg_count'])

    async def test_risk_control(self):
        with self.assertRaises((collector.BridgeError, collector.DtkError)):
            await self.fetch(collector.AUTHOR_POSTS, {'sec_user_id': 'TEST'}, 'risk_control_captcha.json')

    async def test_profile_link_is_resolved_without_html_request(self):
        identity = collector.make_identity(fixtures.COOKIES, fixtures.UA)
        self.assertEqual(await collector.author_id('https://www.douyin.com/user/MS4wTEST', identity), 'MS4wTEST')

    async def test_shortlink_sends_no_cookies(self):
        calls = []
        def handler(request):
            calls.append(request)
            self.assertNotIn('cookie', request.headers)
            return collector.httpx.Response(302, headers={'location': 'https://www.douyin.com/user/MS4wTEST'})
        identity = collector.make_identity(fixtures.COOKIES, fixtures.UA)
        real_client = collector.httpx.AsyncClient
        with patch.object(collector.httpx, 'AsyncClient', side_effect=lambda **kwargs: real_client(transport=collector.httpx.MockTransport(handler), **kwargs)):
            self.assertEqual(await collector.author_id('https://v.douyin.com/TEST/', identity), 'MS4wTEST')
        self.assertEqual(len(calls), 1)

    async def test_validate_rejects_control_characters(self):
        import json
        with self.assertRaises(collector.BridgeError):
            await collector.run({'operation': 'validate', 'config': {'cookies': json.dumps({'UIFID_TEMP': 'test', 'ttwid': 'bad\r\nvalue'}), 'user_agent': fixtures.UA}})


if __name__ == '__main__':
    unittest.main()
