import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import {
  getThemePreset,
  isSelectableThemeId,
  type ThemeId,
} from '@/components/Theme/themePresets';

export type ThemeMode = ThemeId;

interface ThemeState {
  theme: ThemeMode;
  setTheme: (theme: ThemeMode) => void;
  toggleTheme: () => void;
  isDark: () => boolean;
}

export function applyThemeToDOM(theme: ThemeMode): void {
  const root = document.documentElement;
  const preset = getThemePreset(theme);
  root.classList.toggle('dark', preset.mode === 'dark');
  root.setAttribute('data-theme', theme);
  root.style.setProperty('--color-bg-void', preset.colors.bgVoid);
  root.style.setProperty('--color-bg-surface', preset.colors.bgSurface);
  root.style.setProperty('--color-bg-card', preset.colors.bgCard);
  root.style.setProperty('--color-bg-elevated', preset.colors.bgElevated);
  root.style.setProperty('--color-border', preset.colors.border);
  root.style.setProperty('--color-border-lit', preset.colors.borderLit);
  root.style.setProperty('--color-text', preset.colors.text);
  root.style.setProperty('--color-text-sec', preset.colors.textSecondary);
  root.style.setProperty('--color-text-dim', preset.colors.textDim);
  root.style.setProperty('--color-primary', preset.colors.primary);
  root.style.setProperty('--shadow-sm', preset.colors.shadowSm);
  root.style.setProperty('--shadow-md', preset.colors.shadowMd);
  root.style.setProperty('--shadow-lg', preset.colors.shadowLg);
}

export const useThemeStore = create<ThemeState>()(
  persist(
    (set, get) => ({
      theme: 'dark',

      setTheme: (theme: ThemeMode) => {
        set({ theme });
        applyThemeToDOM(theme);
      },

      toggleTheme: () => {
        const current = getThemePreset(get().theme);
        const next: ThemeMode = current.mode === 'dark' ? 'light' : 'dark';
        set({ theme: next });
        applyThemeToDOM(next);
      },

      isDark: () => getThemePreset(get().theme).mode === 'dark',
    }),
    {
      name: 'theme-storage',
      partialize: (state) => ({ theme: state.theme }),
      merge: (persisted, current) => {
        const savedTheme = (persisted as Partial<ThemeState> | undefined)?.theme;
        return { ...current, theme: isSelectableThemeId(savedTheme) ? savedTheme : 'dark' };
      },
      onRehydrateStorage: () => (state) => {
        if (state) {
          applyThemeToDOM(state.theme);
        }
      },
    }
  )
);
