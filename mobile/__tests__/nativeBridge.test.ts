import {nativeBridgeBootstrap, parseNativeBridgeMessage} from '../src/nativeBridge';

describe('native bridge', () => {
  it('accepts the supported message shapes', () => {
    expect(parseNativeBridgeMessage('{"type":"reload"}')).toEqual({type: 'reload'});
    expect(parseNativeBridgeMessage(
      '{"type":"openExternal","url":"https://example.com"}',
    )).toEqual({type: 'openExternal', url: 'https://example.com'});
    expect(parseNativeBridgeMessage(
      '{"type":"share","title":"Result","message":"Done","url":"https://example.com/r/1"}',
    )).toEqual({
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
});
