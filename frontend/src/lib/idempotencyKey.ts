let fallbackSequence = 0;

/**
 * Generate an idempotency key in both secure and insecure browser contexts.
 * `crypto.randomUUID()` is unavailable when a phone opens the app through a
 * plain-HTTP LAN address, so requests must not depend on it being present.
 */
export function createIdempotencyKey(prefix = 'request'): string {
  try {
    const uuid = globalThis.crypto?.randomUUID?.();
    if (uuid) return uuid;
  } catch {
    // Some browsers expose crypto but reject randomUUID outside a secure context.
  }

  fallbackSequence = (fallbackSequence + 1) % Number.MAX_SAFE_INTEGER;
  return [
    prefix,
    Date.now().toString(36),
    fallbackSequence.toString(36),
    Math.random().toString(36).slice(2, 12),
  ].join('-');
}
