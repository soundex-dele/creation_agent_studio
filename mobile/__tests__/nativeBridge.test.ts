import {
  nativeBridgeBootstrap,
  parseNativeBridgeMessage,
} from '../src/nativeBridge';
const { runInNewContext } = require('vm');

describe('native bridge', () => {
  it('accepts the supported message shapes', () => {
    expect(parseNativeBridgeMessage('{"type":"reload"}')).toEqual({
      type: 'reload',
    });
    expect(
      parseNativeBridgeMessage(
        '{"type":"openExternal","url":"https://example.com"}',
      ),
    ).toEqual({ type: 'openExternal', url: 'https://example.com' });
    expect(
      parseNativeBridgeMessage(
        '{"type":"share","title":"Result","message":"Done","url":"https://example.com/r/1"}',
      ),
    ).toEqual({
      type: 'share',
      title: 'Result',
      message: 'Done',
      url: 'https://example.com/r/1',
    });
  });

  it('rejects malformed and unsupported messages', () => {
    expect(parseNativeBridgeMessage('not-json')).toBeNull();
    expect(parseNativeBridgeMessage('{"type":"share"}')).toBeNull();
    expect(parseNativeBridgeMessage('{"type":"unknown"}')).toBeNull();
  });

  it('builds a platform-specific bootstrap', () => {
    const script = nativeBridgeBootstrap('ios');
    expect(script).toContain('AgentStudioNative');
    expect(script).toContain('"ios"');
  });

  it('exchanges credentials only through the top-frame private channel', async () => {
    const token = 'a'.repeat(64);
    const postMessage = jest.fn();
    const window: any = {
      location: { origin: 'https://server.example.com' },
      ReactNativeWebView: { postMessage },
      dispatchEvent: jest.fn(),
    };
    window.top = window;
    const context = { window, setTimeout, clearTimeout, CustomEvent: class {} };
    runInNewContext(
      nativeBridgeBootstrap('android', token, window.location.origin),
      context,
    );
    const promise = window.AgentStudioNative.credentials('load');
    const message = JSON.parse(postMessage.mock.calls[0][0]);
    expect(parseNativeBridgeMessage(JSON.stringify(message))).toEqual(
      expect.objectContaining({ type: 'credentials', action: 'load', token }),
    );
    // Wrong-token replies cannot resolve a legitimate pending request.
    window.AgentStudioNative.completeCredentialRequest(
      'wrong',
      message.requestId,
      { credentials: { username: 'wrong' } },
    );
    window.AgentStudioNative.completeCredentialRequest(
      token,
      message.requestId,
      { credentials: { username: 'alice', password: 'test-secret' } },
    );
    await expect(promise).resolves.toEqual({
      username: 'alice',
      password: 'test-secret',
    });
    expect(window.AgentStudioNative.token).toBeUndefined();
    const iframe = { ...window, top: window, AgentStudioNative: undefined };
    runInNewContext(
      nativeBridgeBootstrap('android', token, window.location.origin),
      { ...context, window: iframe },
    );
    expect(iframe.AgentStudioNative).toBeUndefined();
    const external = {
      ...window,
      location: { origin: 'https://external.example.com' },
      AgentStudioNative: undefined,
    };
    external.top = external;
    runInNewContext(
      nativeBridgeBootstrap('android', token, window.location.origin),
      { ...context, window: external },
    );
    expect(external.AgentStudioNative?.credentials).toBeUndefined();
  });
});
