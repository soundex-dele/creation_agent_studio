export type NativeBridgeMessage =
  | {type: 'openExternal'; url: string}
  | {type: 'reload'}
  | {type: 'share'; title?: string; message: string; url?: string};

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

export function parseNativeBridgeMessage(raw: string): NativeBridgeMessage | null {
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return null;
  }

  if (!isRecord(value) || typeof value.type !== 'string') return null;

  if (value.type === 'reload') return {type: 'reload'};

  if (value.type === 'openExternal' && typeof value.url === 'string') {
    return {type: 'openExternal', url: value.url};
  }

  if (value.type === 'share' && typeof value.message === 'string') {
    return {
      type: 'share',
      message: value.message,
      ...(typeof value.title === 'string' ? {title: value.title} : {}),
      ...(typeof value.url === 'string' ? {url: value.url} : {}),
    };
  }

  return null;
}

export function nativeBridgeBootstrap(platform: string): string {
  const platformLiteral = JSON.stringify(platform);
  return `
    (function () {
      window.AgentStudioNative = Object.freeze({
        available: true,
        platform: ${platformLiteral},
        postMessage: function (message) {
          window.ReactNativeWebView.postMessage(JSON.stringify(message));
        }
      });
      window.dispatchEvent(new CustomEvent('agentstudio:native-ready', {
        detail: { platform: ${platformLiteral} }
      }));
    })();
    true;
  `;
}
