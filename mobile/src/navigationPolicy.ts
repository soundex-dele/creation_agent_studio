export type NavigationDecision = 'internal' | 'external' | 'blocked';

const EXTERNAL_PROTOCOLS = new Set(['http:', 'https:', 'mailto:', 'tel:']);

function normalizedOrigin(value: string): string | null {
  try {
    return new URL(value).origin;
  } catch {
    return null;
  }
}

export function classifyNavigation(
  targetUrl: string,
  appOrigin: string,
  trustedAuthOrigins: readonly string[] = [],
): NavigationDecision {
  if (targetUrl === 'about:blank') return 'internal';

  let target: URL;
  try {
    target = new URL(targetUrl);
  } catch {
    return 'blocked';
  }

  const allowedOrigins = new Set(
    [appOrigin, ...trustedAuthOrigins]
      .map(normalizedOrigin)
      .filter((origin): origin is string => origin !== null),
  );

  if (allowedOrigins.has(target.origin)) return 'internal';
  if (EXTERNAL_PROTOCOLS.has(target.protocol)) return 'external';
  return 'blocked';
}

export function resolveDeepLink(
  incomingUrl: string,
  appOrigin: string,
  customScheme = 'agentstudio',
): string | null {
  let incoming: URL;
  try {
    incoming = new URL(incomingUrl);
  } catch {
    return null;
  }

  if (incoming.origin === normalizedOrigin(appOrigin)) return incoming.toString();

  if (incoming.protocol !== `${customScheme}:`) return null;

  const requestedPath = incoming.searchParams.get('path');
  if (!requestedPath?.startsWith('/') || requestedPath.startsWith('//')) return null;

  const destination = new URL(requestedPath, appOrigin);
  return destination.origin === normalizedOrigin(appOrigin)
    ? destination.toString()
    : null;
}

export function isSafeExternalUrl(targetUrl: string): boolean {
  try {
    return EXTERNAL_PROTOCOLS.has(new URL(targetUrl).protocol);
  } catch {
    return false;
  }
}
