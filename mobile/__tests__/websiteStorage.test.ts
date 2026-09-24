import AsyncStorage from '@react-native-async-storage/async-storage';
import {
  loadWebsiteHistory,
  loadWebsiteUrl,
  saveWebsiteUrl,
} from '../src/websiteStorage';

jest.mock('@react-native-async-storage/async-storage', () =>
  require('@react-native-async-storage/async-storage/jest/async-storage-mock'),
);

afterEach(() => jest.restoreAllMocks());
beforeEach(async () => {
  await AsyncStorage.clear();
});

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

it('keeps normalized, unique servers in most-recent order across reloads', async () => {
  await saveWebsiteUrl('first.example.com');
  await saveWebsiteUrl('http://192.168.1.20:3030/apps?q=1');
  await saveWebsiteUrl('https://first.example.com/');
  expect(await loadWebsiteHistory()).toEqual([
    'https://first.example.com/',
    'http://192.168.1.20:3030/apps?q=1',
  ]);
});

it('migrates the old saved address and recovers from corrupt history', async () => {
  await AsyncStorage.setItem('@agent-studio/website-url', 'legacy.example.com');
  await AsyncStorage.setItem('@agent-studio/website-history', '{bad json');
  expect(await loadWebsiteHistory()).toEqual(['https://legacy.example.com/']);
  await AsyncStorage.setItem(
    '@agent-studio/website-history',
    JSON.stringify([
      42,
      null,
      ['java', 'script:1'].join(''),
      'legacy.example.com',
      'valid.example.com',
    ]),
  );
  expect(await loadWebsiteHistory()).toEqual([
    'https://legacy.example.com/',
    'https://valid.example.com/',
  ]);
});

it('bounds history to the 20 most recently used addresses', async () => {
  for (let index = 0; index < 22; index++)
    await saveWebsiteUrl(`https://server${index}.example.com`);
  const history = await loadWebsiteHistory();
  expect(history).toHaveLength(20);
  expect(history[0]).toBe('https://server21.example.com/');
  expect(history[19]).toBe('https://server2.example.com/');
});
