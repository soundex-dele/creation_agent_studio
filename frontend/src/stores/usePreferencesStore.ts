import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export type SendShortcut = 'enter' | 'mod-enter';
export type PermissionMode = 'default' | 'allow_all';

interface PreferencesState {
  sendShortcut: SendShortcut;
  defaultPermissionMode: PermissionMode;
  setSendShortcut: (value: SendShortcut) => void;
  setDefaultPermissionMode: (value: PermissionMode) => void;
  reset: () => void;
}

const defaults = {
  sendShortcut: 'enter' as SendShortcut,
  defaultPermissionMode: 'default' as PermissionMode,
};

export const usePreferencesStore = create<PreferencesState>()(
  persist(
    (set) => ({
      ...defaults,
      setSendShortcut: (sendShortcut) => set({ sendShortcut }),
      setDefaultPermissionMode: (defaultPermissionMode) => set({ defaultPermissionMode }),
      reset: () => set(defaults),
    }),
    {
      name: 'agent-studio-preferences',
      partialize: ({ sendShortcut, defaultPermissionMode }) => ({
        sendShortcut,
        defaultPermissionMode,
      }),
    },
  ),
);
