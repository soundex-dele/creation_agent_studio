interface AuthSessionBridge {
  accessToken: () => string | null;
  refresh: () => Promise<void>;
  clear: () => void;
}

let bridge: AuthSessionBridge = {
  accessToken: () => null,
  refresh: async () => { throw new Error('Auth session is not initialized'); },
  clear: () => localStorage.removeItem('auth-storage'),
};

let refreshInFlight: Promise<void> | null = null;

export const registerAuthSession = (next: AuthSessionBridge): void => {
  bridge = next;
};

export const getAccessToken = (): string | null => bridge.accessToken();
export const refreshAccessToken = (): Promise<void> => {
  if (!refreshInFlight) {
    refreshInFlight = bridge.refresh().finally(() => {
      refreshInFlight = null;
    });
  }
  return refreshInFlight;
};
export const clearAuthSession = (): void => bridge.clear();
