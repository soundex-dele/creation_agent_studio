import {
  connectionAddress,
  describeWebViewError,
  isRecoverableWebViewError,
} from '../src/webViewErrors';

it('explains Android connection failure without treating missing error domain as an invalid URL', () => {
  const detail = describeWebViewError(
    'android',
    -6,
    'net::ERR_CONNECTION_REFUSED',
    'http://192.168.137.1:3030/',
  );
  expect(detail).toContain('无法连接服务器');
  expect(detail).toContain('端口');
  expect(detail).not.toContain('undefined');
  expect(
    describeWebViewError('android', -6, '', 'http://127.0.0.1:3030/'),
  ).toContain('USB 端口转发');
});

it('only retries transient connectivity failures and keeps authentication/certificate failures explicit', () => {
  expect(isRecoverableWebViewError('android', -6)).toBe(true);
  expect(isRecoverableWebViewError('android', -11)).toBe(false);
  expect(isRecoverableWebViewError('android', -4)).toBe(false);
  expect(isRecoverableWebViewError('ios', -1009)).toBe(true);
});

it('does not expose credentials or signed query parameters in the error address', () => {
  expect(
    connectionAddress(
      'https://user:password@example.com:8443/apps?token=secret#key',
    ),
  ).toBe('https://example.com:8443/apps');
});
