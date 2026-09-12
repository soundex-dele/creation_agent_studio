interface AuthSessionBridge {
  accessToken: () => string | null;
  refresh: () => Promise<void>;
  clear: () => void;
}

const persistedAccessToken = (): string | null => {
  try {
    const persisted = JSON.parse(localStorage.getItem('auth-storage') || '{}');
    return persisted?.state?.token || null;
  } catch {
    return null;
  }
};

let bridge: AuthSessionBridge = {
  accessToken: persistedAccessToken,
  refresh: async () => { throw new Error('Auth session is not initialized'); },
  clear: () => localStorage.removeItem('auth-storage'),
};

export const registerAuthSession = (next: AuthSessionBridge): void => {
  bridge = next;
};

export const getAccessToken = (): string | null => bridge.accessToken();
export const refreshAccessToken = (): Promise<void> => bridge.refresh();
export const clearAuthSession = (): void => bridge.clear();
