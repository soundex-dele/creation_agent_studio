export type NativeBridgeMessage =
  | {
      type: 'credentials';
      action: 'load' | 'clear';
      requestId: string;
      token: string;
    }
  | {
      type: 'credentials';
      action: 'save';
      requestId: string;
      token: string;
      username: string;
      password: string;
    }
  | { type: 'openExternal'; url: string }
  | { type: 'reload' }
  | { type: 'share'; title?: string; message: string; url?: string };

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

export function parseNativeBridgeMessage(
  raw: string,
): NativeBridgeMessage | null {
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return null;
  }

  if (!isRecord(value) || typeof value.type !== 'string') return null;

  if (value.type === 'credentials') {
    if (
      typeof value.requestId !== 'string' ||
      value.requestId.length > 128 ||
      typeof value.token !== 'string' ||
      value.token.length !== 64
    )
      return null;
    const base = {
      type: 'credentials' as const,
      requestId: value.requestId,
      token: value.token,
    };
    if (value.action === 'load' || value.action === 'clear')
      return { ...base, action: value.action };
    if (
      value.action === 'save' &&
      typeof value.username === 'string' &&
      value.username.length > 0 &&
      value.username.length <= 1024 &&
      typeof value.password === 'string' &&
      value.password.length > 0 &&
      value.password.length <= 4096
    ) {
      return {
        ...base,
        action: 'save',
        username: value.username,
        password: value.password,
      };
    }
    return null;
  }

  if (value.type === 'reload') return { type: 'reload' };

  if (value.type === 'openExternal' && typeof value.url === 'string') {
    return { type: 'openExternal', url: value.url };
  }

  if (value.type === 'share' && typeof value.message === 'string') {
    return {
      type: 'share',
      message: value.message,
      ...(typeof value.title === 'string' ? { title: value.title } : {}),
      ...(typeof value.url === 'string' ? { url: value.url } : {}),
    };
  }

  return null;
}

export function nativeBridgeBootstrap(
  platform: string,
  credentialToken = '',
  appOrigin = '',
): string {
  const platformLiteral = JSON.stringify(platform);
  return `
    (function () {
      if (window.top !== window || window.AgentStudioNative) return;
      var token = ${JSON.stringify(credentialToken)};
      var origin = ${JSON.stringify(appOrigin)};
      var pending = Object.create(null);
      var sequence = 0;
      var documentId = Date.now().toString(36) + Math.random().toString(36).slice(2);
      window.AgentStudioNative = Object.freeze({
        available: true,
        platform: ${platformLiteral},
        credentials: token && window.location.origin === origin ? function (action, values) {
          return new Promise(function (resolve, reject) {
            if (window.location.origin !== origin) { reject(new Error('Wrong server')); return; }
            var requestId = documentId + '-' + (++sequence);
            var timer = setTimeout(function () {
              delete pending[requestId];
              reject(new Error('Credential request timed out'));
            }, 8000);
            pending[requestId] = function (result) {
              clearTimeout(timer);
              if (result.error) reject(new Error(result.error));
              else resolve(result.credentials || null);
            };
            window.ReactNativeWebView.postMessage(JSON.stringify({
              type: 'credentials', action: action, requestId: requestId, token: token,
              username: values && values.username, password: values && values.password
            }));
          });
        } : undefined,
        completeCredentialRequest: function (responseToken, requestId, result) {
          if (responseToken !== token || window.location.origin !== origin) return;
          var complete = pending[requestId];
          delete pending[requestId];
          if (complete) complete(result);
        },
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
