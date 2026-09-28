/** UUID v4 for record IDs and API operation IDs, including plain-HTTP LAN use. */
export function createUuid(): string {
  try {
    const uuid = globalThis.crypto?.randomUUID?.();
    if (uuid) return uuid;
  } catch {
    // Some mobile browsers expose randomUUID but restrict it to secure contexts.
  }

  // Unlike randomUUID, getRandomValues is available in insecure contexts too.
  const bytes = new Uint8Array(16);
  if (!globalThis.crypto?.getRandomValues) {
    throw new Error('当前浏览器无法生成操作标识，请更换浏览器后重试。');
  }
  globalThis.crypto.getRandomValues(bytes);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
