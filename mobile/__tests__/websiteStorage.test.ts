import AsyncStorage from '@react-native-async-storage/async-storage';
import { loadWebsiteUrl, saveWebsiteUrl } from '../src/websiteStorage';

jest.mock('@react-native-async-storage/async-storage', () =>
  require('@react-native-async-storage/async-storage/jest/async-storage-mock'),
);

afterEach(() => jest.restoreAllMocks());

it('normalizes and persists a full website address', async () => {
  await saveWebsiteUrl('example.com:8443/apps?entry=mobile#home');
  expect(await loadWebsiteUrl()).toBe(
    'https://example.com:8443/apps?entry=mobile#home',
  );
});

it('ignores invalid data in storage rather than opening an unsafe URL', async () => {
  jest.spyOn(AsyncStorage, 'getItem').mockResolvedValueOnce('file:///tmp/test');
  expect(await loadWebsiteUrl()).toBeNull();
});

it('does not overwrite a saved website with invalid input', async () => {
  await saveWebsiteUrl('https://example.com/');
  await expect(saveWebsiteUrl('not a url')).rejects.toThrow();
  expect(await loadWebsiteUrl()).toBe('https://example.com/');
});
