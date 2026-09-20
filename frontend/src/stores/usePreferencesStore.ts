import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import {
  DEFAULT_NAVIGATION_ICONS,
  type HeaderNavigationItemId,
  type NavigationIconId,
  type NavigationIconPreferences,
} from '@/components/Header/headerNavigation';

export type SendShortcut = 'enter' | 'mod-enter';
export type PermissionMode = 'default' | 'allow_all';
export type NavigationIconMode = 'outline' | 'emoji' | 'hidden';
export type LayoutMode = 'top-bottom' | 'left-right';

interface PreferencesState {
  layoutMode: LayoutMode;
  setLayoutMode: (value: LayoutMode) => void;
  sendShortcut: SendShortcut;
  defaultPermissionMode: PermissionMode;
  navigationIconMode: NavigationIconMode;
  navigationIcons: NavigationIconPreferences;
  setSendShortcut: (value: SendShortcut) => void;
  setDefaultPermissionMode: (value: PermissionMode) => void;
  setNavigationIconMode: (value: NavigationIconMode) => void;
  setNavigationIcon: (itemId: HeaderNavigationItemId, iconId: NavigationIconId) => void;
  resetNavigationIcons: () => void;
  reset: () => void;
}

const defaults = {
  layoutMode: 'top-bottom' as LayoutMode,
  sendShortcut: 'enter' as SendShortcut,
  defaultPermissionMode: 'default' as PermissionMode,
  navigationIconMode: 'outline' as NavigationIconMode,
  navigationIcons: { ...DEFAULT_NAVIGATION_ICONS },
};

export const usePreferencesStore = create<PreferencesState>()(
  persist(
    (set) => ({
      ...defaults,
      setLayoutMode: (layoutMode) => set({ layoutMode }),
      setSendShortcut: (sendShortcut) => set({ sendShortcut }),
      setDefaultPermissionMode: (defaultPermissionMode) => set({ defaultPermissionMode }),
      setNavigationIconMode: (navigationIconMode) => set({ navigationIconMode }),
      setNavigationIcon: (itemId, iconId) => set((state) => ({
        navigationIcons: { ...state.navigationIcons, [itemId]: iconId },
      })),
      resetNavigationIcons: () => set({ navigationIcons: { ...DEFAULT_NAVIGATION_ICONS } }),
      reset: () => set({ ...defaults, navigationIcons: { ...DEFAULT_NAVIGATION_ICONS } }),
    }),
    {
      name: 'agent-studio-preferences',
      partialize: ({
        layoutMode, sendShortcut, defaultPermissionMode, navigationIconMode, navigationIcons,
      }) => ({
        layoutMode,
        sendShortcut,
        defaultPermissionMode,
        navigationIconMode,
        navigationIcons,
      }),
    },
  ),
);
