import 'react-native-get-random-values';
import * as Keychain from 'react-native-keychain';

export interface SavedCredentials {
  username: string;
  password: string;
}

export function createCredentialToken(): string {
  const crypto = (
    globalThis as unknown as {
      crypto: { getRandomValues: (values: Uint8Array) => Uint8Array };
    }
  ).crypto;
  return Array.from(crypto.getRandomValues(new Uint8Array(32)), byte =>
    byte.toString(16).padStart(2, '0'),
  ).join('');
}

function service(origin: string): string {
  const url = new URL(origin);
  if (!['http:', 'https:'].includes(url.protocol))
    throw new Error('Invalid server');
  return `agent-studio-login:${url.origin}`;
}

export async function loadCredentials(
  origin: string,
): Promise<SavedCredentials | null> {
  const saved = await Keychain.getGenericPassword({ service: service(origin) });
  return saved ? { username: saved.username, password: saved.password } : null;
}

export async function saveCredentials(
  origin: string,
  credentials: SavedCredentials,
): Promise<void> {
  const saved = await Keychain.setGenericPassword(
    credentials.username,
    credentials.password,
    {
      service: service(origin),
      accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
      securityLevel: Keychain.SECURITY_LEVEL.SECURE_SOFTWARE,
    },
  );
  if (!saved) throw new Error('Unable to save credentials');
}

export async function clearCredentials(origin: string): Promise<void> {
  await Keychain.resetGenericPassword({ service: service(origin) });
}
