/** Normalize user-entered website addresses without discarding paths or queries. */
export function normalizeWebsiteUrl(input: string): string | null {
  const value = input.trim();
  if (!value || /\s/.test(value)) return null;

  let candidate = value;
  if (value.startsWith('//')) {
    candidate = `https:${value}`;
  } else if (!/^https?:\/\//i.test(value)) {
    const hostWithPort =
      /^(?:localhost|[^/?#:]+\.[^/?#:]+|\[[\da-f:]+\]):\d+(?:[/?#]|$)/i.test(
        value,
      );
    if (/^[a-z][a-z\d+.-]*:/i.test(value) && !hostWithPort) return null;
    candidate = `https://${value}`;
  }

  try {
    const url = new URL(candidate);
    if (
      !['http:', 'https:'].includes(url.protocol) ||
      !url.hostname ||
      url.username ||
      url.password
    )
      return null;
    return url.toString();
  } catch {
    return null;
  }
}
