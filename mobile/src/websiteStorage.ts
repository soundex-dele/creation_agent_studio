import AsyncStorage from '@react-native-async-storage/async-storage';

import { normalizeWebsiteUrl } from './websiteUrl';

const WEBSITE_URL_KEY = '@agent-studio/website-url';

export async function loadWebsiteUrl(): Promise<string | null> {
  const savedUrl = await AsyncStorage.getItem(WEBSITE_URL_KEY);
  return savedUrl ? normalizeWebsiteUrl(savedUrl) : null;
}

export async function saveWebsiteUrl(url: string): Promise<void> {
  const normalizedUrl = normalizeWebsiteUrl(url);
  if (!normalizedUrl) throw new Error('Invalid website URL');
  await AsyncStorage.setItem(WEBSITE_URL_KEY, normalizedUrl);
}
