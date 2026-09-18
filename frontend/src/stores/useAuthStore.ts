import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { api } from '@/services/api';
import { registerAuthSession } from '@/services/authSession';

interface User {
  id: string;
  username: string;
  email: string;
  role: 'admin' | 'auditor' | 'member';
  avatar?: string;
  bio?: string;
  created_at: string;
}

interface AuthState {
  user: User | null;
  token: string | null;
  isAuthenticated: boolean;
  login: (username: string, password: string) => Promise<void>;
  licenseLogin: (license?: string) => Promise<void>;
  register: (data: RegisterData) => Promise<void>;
  completeSso: (exchange: string) => Promise<void>;
  logout: () => Promise<void>;
  clearAuth: () => void;
  refreshAccessToken: () => Promise<void>;
  updateUser: (data: Partial<User>) => void;
}

interface RegisterData {
  username: string;
  email: string;
  password: string;
  password_confirm: string;
  role?: string;
}

interface AuthTokens {
  access: string;
}

interface AuthResponse {
  user: User;
  tokens: AuthTokens;
}

interface RefreshResponse {
  access: string;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      user: null,
      token: null,
      isAuthenticated: false,

      login: async (username: string, password: string) => {
        const response = await api.post<AuthResponse>('/auth/login/', { username, password });
        const { user, tokens } = response;

        set({
          user,
          token: tokens.access,
          isAuthenticated: true,
        });
      },

      licenseLogin: async (license?: string) => {
        const response = await api.post<AuthResponse>('/auth/license/login/', {
          license: license?.trim() || undefined,
        });
        const { user, tokens } = response;
        set({ user, token: tokens.access, isAuthenticated: true });
      },

      register: async (data: RegisterData) => {
        const response = await api.post<AuthResponse>('/auth/register/', data);
        const { user, tokens } = response;

        set({
          user,
          token: tokens.access,
          isAuthenticated: true,
        });
      },

      completeSso: async (exchange: string) => {
        const response = await api.post<AuthResponse>('/enterprise/sso/exchange', { exchange });
        const { user, tokens } = response;
        set({ user, token: tokens.access, isAuthenticated: true });
      },

      clearAuth: () => {
        // Synchronously wipe local auth state. Used right before a full-page
        // redirect to login — must NOT depend on a network round-trip, since the
        // navigation would abort it and strand the stale/blacklisted tokens in
        // localStorage.
        set({
          user: null,
          token: null,
          isAuthenticated: false,
        });
      },

      logout: async () => {
        // Clear local state first so an aborted request can't strand tokens.
        get().clearAuth();
        try {
          await api.post('/auth/logout/', {});
        } catch (error) {
          console.error('Logout error:', error);
        }
      },

      refreshAccessToken: async () => {
        try {
          const response = await api.post<RefreshResponse>('/auth/token/refresh/', {});

          set({
            token: response.access,
            isAuthenticated: true,
          });
        } catch (error) {
          // Refresh failed (token invalid/expired/blacklisted). Clear local
          // state; the axios 401 handler is responsible for redirecting to login.
          get().clearAuth();
          throw error;
        }
      },

      updateUser: (data: Partial<User>) => {
        const { user } = get();
        if (user) {
          set({ user: { ...user, ...data } });
        }
      },
    }),
    {
      name: 'auth-storage',
      partialize: (state) => ({
        user: state.user,
        isAuthenticated: state.isAuthenticated,
      }),
    }
  )
);

registerAuthSession({
  accessToken: () => useAuthStore.getState().token,
  refresh: () => useAuthStore.getState().refreshAccessToken(),
  clear: () => useAuthStore.getState().clearAuth(),
});
