export type CategoryDomain = 'application' | 'agent';

const ICON_BY_KEY: Record<string, string> = {
  chat: '💬',
  edit: '✍️',
  creative: '✍️',
  copywriting: '✍️',
  video: '🎬',
  design: '🎨',
  audio: '🎵',
  media: '🎞️',
  analytics: '📊',
  livestream: '🎙️',
  ai: '✨',
  general: '✨',
  productivity: '🧰',
  knowledge: '📚',
  workflow: '🔀',
  'workflow-apps': '🔀',
};

const ASCII_IDENTIFIER = /^[a-z][a-z0-9_-]*$/i;

/** Convert backend icon identifiers to display icons without exposing tokens such as "chat" or "edit". */
export function categoryIcon(
  icon: string | undefined,
  slug: string,
  domain: CategoryDomain,
): string {
  const normalizedIcon = icon?.trim();
  if (normalizedIcon && !ASCII_IDENTIFIER.test(normalizedIcon)) return normalizedIcon;
  return ICON_BY_KEY[normalizedIcon?.toLowerCase() || '']
    || ICON_BY_KEY[slug.toLowerCase()]
    || (domain === 'agent' ? '🤖' : '🧩');
}
