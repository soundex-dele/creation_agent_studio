import * as Keychain from 'react-native-keychain';
import {
  clearCredentials,
  loadCredentials,
  saveCredentials,
} from '../src/credentialStorage';

jest.mock('react-native-get-random-values', () => ({}));
jest.mock('react-native-keychain', () => ({
  getGenericPassword: jest.fn(),
  setGenericPassword: jest.fn(),
  resetGenericPassword: jest.fn(),
  SECURITY_LEVEL: { SECURE_SOFTWARE: 1 },
  STORAGE_TYPE: { AES_GCM_NO_AUTH: 'KeystoreAESGCM_NoAuth' },
  ACCESSIBLE: { WHEN_UNLOCKED_THIS_DEVICE_ONLY: 'WhenUnlockedThisDeviceOnly' },
}));

beforeEach(() => jest.clearAllMocks());

it('stores passwords in the keychain using a separate service per server origin', async () => {
  jest
    .mocked(Keychain.setGenericPassword)
    .mockResolvedValue({
      service: '',
      storage: Keychain.STORAGE_TYPE.AES_GCM_NO_AUTH,
    });
  await saveCredentials('https://one.example.com/app', {
    username: 'alice',
    password: 'test-password',
  });
  await saveCredentials('http://one.example.com:8080', {
    username: 'bob',
    password: 'other-password',
  });
  expect(Keychain.setGenericPassword).toHaveBeenNthCalledWith(
    1,
    'alice',
    'test-password',
    {
      service: 'agent-studio-login:https://one.example.com',
      accessible: 'WhenUnlockedThisDeviceOnly',
      securityLevel: 1,
    },
  );
  expect(Keychain.setGenericPassword).toHaveBeenNthCalledWith(
    2,
    'bob',
    'other-password',
    {
      service: 'agent-studio-login:http://one.example.com:8080',
      accessible: 'WhenUnlockedThisDeviceOnly',
      securityLevel: 1,
    },
  );
});

it('loads and clears only the requested server', async () => {
  jest.mocked(Keychain.getGenericPassword).mockResolvedValueOnce({
    username: 'alice',
    password: 'saved',
    service: '',
    storage: Keychain.STORAGE_TYPE.AES_GCM_NO_AUTH,
  });
  expect(await loadCredentials('https://one.example.com')).toEqual({
    username: 'alice',
    password: 'saved',
  });
  jest.mocked(Keychain.getGenericPassword).mockResolvedValueOnce(false);
  expect(await loadCredentials('https://two.example.com')).toBeNull();
  await clearCredentials('https://two.example.com');
  expect(Keychain.resetGenericPassword).toHaveBeenCalledWith({
    service: 'agent-studio-login:https://two.example.com',
  });
});

it('reports failed writes instead of pretending the password was saved', async () => {
  jest.mocked(Keychain.setGenericPassword).mockResolvedValue(false);
  await expect(
    saveCredentials('https://one.example.com', {
      username: 'alice',
      password: 'test',
    }),
  ).rejects.toThrow();
});
