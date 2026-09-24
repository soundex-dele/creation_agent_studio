import AsyncStorage from '@react-native-async-storage/async-storage';

import { normalizeWebsiteUrl } from './websiteUrl';

const WEBSITE_URL_KEY = '@agent-studio/website-url';
const WEBSITE_HISTORY_KEY = '@agent-studio/website-history';
const HISTORY_LIMIT = 20;

export function recentWebsiteUrls(urls: unknown[]): string[] {
  return [
    ...new Set(
      urls.flatMap(value => {
        const url =
          typeof value === 'string' ? normalizeWebsiteUrl(value) : null;
        return url ? [url] : [];
      }),
    ),
  ].slice(0, HISTORY_LIMIT);
}

export async function loadWebsiteHistory(): Promise<string[]> {
  const [savedHistory, lastUrl] = await Promise.all([
    AsyncStorage.getItem(WEBSITE_HISTORY_KEY),
    loadWebsiteUrl(),
  ]);
  let history: unknown = [];
  try {
    history = savedHistory ? JSON.parse(savedHistory) : [];
  } catch {
    // Recover from malformed history and migrate the legacy single address.
  }
  return recentWebsiteUrls([
    lastUrl,
    ...(Array.isArray(history) ? history : []),
  ]);
}

export async function loadWebsiteUrl(): Promise<string | null> {
  const savedUrl = await AsyncStorage.getItem(WEBSITE_URL_KEY);
  return savedUrl ? normalizeWebsiteUrl(savedUrl) : null;
}

export async function saveWebsiteUrl(url: string): Promise<void> {
  const normalizedUrl = normalizeWebsiteUrl(url);
  if (!normalizedUrl) throw new Error('Invalid website URL');
  const history = recentWebsiteUrls([
    normalizedUrl,
    ...(await loadWebsiteHistory()),
  ]);
  await AsyncStorage.setItem(WEBSITE_HISTORY_KEY, JSON.stringify(history));
  await AsyncStorage.setItem(WEBSITE_URL_KEY, normalizedUrl);
}
