"""Run explicitly with .venv-dtk; exercises real DTK signing/parsing offline."""
import sys
from pathlib import Path
import unittest
from unittest.mock import patch, AsyncMock
from types import SimpleNamespace
import json
import io
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import test_douyin_video_url as fixtures
import collector
from dtk.transport.base import RawResponse
from dtk.transport.classify import DEFAULT_CLASSIFIER


class CollectorSourceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        collector.configure(level="critical")

    async def fetch(self, endpoint, params, fixture, body_type=bytes):
        identity = collector.make_identity(fixtures.COOKIES, fixtures.UA)
        client = fixtures.RecordingClient(fixture, body_type)
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

    async def test_memoryview_profile_posts_and_detail(self):
        cases = [
            (collector.AUTHOR_PROFILE, {'sec_user_id': 'TEST'}, 'user_profile.json', 'uid'),
            (collector.AUTHOR_POSTS, {'sec_user_id': 'TEST', 'count': 20}, 'user_posts_page1.json', 'items'),
            (collector.CONTENT_DETAIL, {'aweme_id': fixtures.POST_ID}, 'video_normal.json', 'content_id'),
        ]
        for endpoint, params, fixture, key in cases:
            with self.subTest(endpoint=endpoint):
                result, _ = await self.fetch(endpoint, params, fixture, memoryview)
                self.assertTrue(result[key])

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

    async def test_response_failures_are_not_all_cookie_expiry(self):
        identity = collector.make_identity(fixtures.COOKIES, fixtures.UA)
        cases = [
            (403, b'Signature Not Found', 'signature'),
            (403, b'Forbidden', 'risk_control'),
            (401, b'Unauthorized', 'auth'),
            (200, b'<html>captcha</html>', 'challenge'),
            (200, b'', 'empty_response'),
            (200, b'{"status_code":2053}', 'content_unavailable'),
            (403, b'{"status_code":2053}', 'content_unavailable'),
        ]
        for status, body, expected in cases:
            with self.subTest(status=status, expected=expected):
                transport = SimpleNamespace(request=AsyncMock(return_value=RawResponse(status=status, body=body)), classify=DEFAULT_CLASSIFIER.classify)
                with self.assertRaises(collector.BridgeError) as error:
                    await collector.request(collector.CONTENT_DETAIL, {'aweme_id': fixtures.POST_ID}, identity, transport)
                self.assertEqual(str(error.exception), expected)
                self.assertEqual(error.exception.diagnostic['http_status'], status)
                self.assertEqual(error.exception.diagnostic['endpoint'], collector.CONTENT_DETAIL)

    async def test_network_failure_preserves_stage_without_request_secrets(self):
        identity = collector.make_identity(fixtures.COOKIES, fixtures.UA)
        failure = collector.TransportFailure('private-cookie signed-url', identity_id='private-identity',
            url='https://example.test/?token=private-token', elapsed_ms=100)
        transport = SimpleNamespace(request=AsyncMock(side_effect=failure))
        with self.assertRaises(collector.BridgeError) as caught:
            await collector.request(collector.AUTHOR_PROFILE, {'sec_user_id': 'TEST'}, identity, transport)
        self.assertEqual(collector.error_result(caught.exception), {
            'error': 'unavailable', 'diagnostic': {'stage': 'transport',
                'endpoint': collector.AUTHOR_PROFILE, 'error_type': 'TransportFailure'},
        })

    async def test_signer_failure_keeps_stage_and_type(self):
        identity = collector.make_identity(fixtures.COOKIES, fixtures.UA)
        signer = SimpleNamespace(sign=AsyncMock(side_effect=AttributeError('private-signature')))
        with patch.object(collector, 'NativeSigner', return_value=signer):
            with self.assertRaises(collector.BridgeError) as caught:
                await collector.request(collector.AUTHOR_PROFILE, {'sec_user_id': 'TEST'}, identity)
        self.assertEqual(collector.error_result(caught.exception), {
            'error': 'unavailable', 'diagnostic': {'stage': 'sign',
                'endpoint': collector.AUTHOR_PROFILE, 'error_type': 'AttributeError'},
        })

    async def test_shortlink_timeout_keeps_stage(self):
        with patch.object(collector, 'author_id', side_effect=collector.httpx.ConnectTimeout('private-url')):
            with self.assertRaises(collector.BridgeError) as caught:
                await collector.run({'operation': 'profile', 'config': {
                    'cookies': json.dumps(fixtures.COOKIES), 'user_agent': fixtures.UA},
                    'params': {'url': 'https://v.douyin.com/TEST/'}})
        self.assertEqual(collector.error_result(caught.exception), {
            'error': 'timeout', 'diagnostic': {'stage': 'resolve_url',
                'endpoint': collector.AUTHOR_PROFILE, 'error_type': 'ConnectTimeout'},
        })

    def test_transport_timeout_is_not_a_schema_error(self):
        error = collector.TransportFailure('private-url', identity_id='private-identity',
            url='https://example.test/?token=private-token', elapsed_ms=100,
            cause=TimeoutError('private-body'))
        self.assertEqual(collector.error_result(error), {
            'error': 'timeout', 'diagnostic': {'error_type': 'TransportFailure'},
        })

    async def test_parser_failure_retains_http_status(self):
        identity = collector.make_identity(fixtures.COOKIES, fixtures.UA)
        from dtk.core.errors import UpstreamChanged
        transport = SimpleNamespace(request=AsyncMock(return_value=RawResponse(status=200, body=b'{"user":{}}')),
            classify=lambda _: SimpleNamespace(outcome=collector.Outcome.OK))
        with patch.object(type(collector.ADAPTER), 'parse_author', side_effect=UpstreamChanged('private-field')):
            with self.assertRaises(collector.BridgeError) as caught:
                await collector.request(collector.AUTHOR_PROFILE, {'sec_user_id': 'TEST'}, identity, transport)
        self.assertEqual(collector.error_result(caught.exception), {
            'error': 'invalid', 'diagnostic': {'stage': 'parse', 'http_status': 200,
                'endpoint': collector.AUTHOR_PROFILE, 'error_type': 'UpstreamChanged'},
        })

    def test_main_emits_diagnostics_without_exception_payload(self):
        failure = collector.BridgeError('unavailable')
        failure.diagnostic = {'stage': 'transport', 'endpoint': collector.AUTHOR_PROFILE,
            'error_type': 'TransportFailure'}
        output = io.StringIO()
        with patch.object(collector, 'run', AsyncMock(side_effect=failure)), \
                patch.object(collector.sys, 'stdin', io.StringIO('{"config":{"cookies":"private-cookie"}}')), \
                patch.object(collector.sys, 'stdout', output):
            collector.main()
        self.assertEqual(json.loads(output.getvalue()), collector.error_result(failure))
        self.assertNotIn('private-cookie', output.getvalue())

    def test_app_allowlist_covers_pinned_dtk_douyin_media_domains(self):
        from dtk.media.domains import DOUYIN_MEDIA_DOMAINS as source_domains
        from core.douyin_media_urls import DOUYIN_MEDIA_DOMAINS as app_domains
        self.assertTrue(source_domains <= app_domains, source_domains - app_domains)


if __name__ == '__main__':
    unittest.main()
