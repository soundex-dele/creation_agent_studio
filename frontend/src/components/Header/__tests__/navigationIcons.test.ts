import { afterEach, describe, expect, it } from 'vitest';
import { usePreferencesStore } from '@/stores/usePreferencesStore';
import {
  DEFAULT_NAVIGATION_ICONS,
  HEADER_NAV_ITEMS,
  NAVIGATION_ICON_OPTIONS,
} from '../headerNavigation';
import { NAVIGATION_ICON_COMPONENTS } from '../navigationIconComponents';

describe('navigation icon preferences', () => {
  afterEach(() => {
    usePreferencesStore.getState().resetNavigationIcons();
  });

  it('provides a registered default icon for every header destination', () => {
    expect(new Set(NAVIGATION_ICON_OPTIONS.map((option) => option.id)).size)
      .toBe(NAVIGATION_ICON_OPTIONS.length);

    for (const item of HEADER_NAV_ITEMS) {
      expect(DEFAULT_NAVIGATION_ICONS[item.id]).toBe(item.defaultIcon);
      expect(NAVIGATION_ICON_COMPONENTS[item.defaultIcon]).toBeTruthy();
    }
  });

  it('updates one destination without changing the others and can reset', () => {
    const originalChatIcon = usePreferencesStore.getState().navigationIcons.chat;

    usePreferencesStore.getState().setNavigationIcon('home', 'star');

    expect(usePreferencesStore.getState().navigationIcons).toMatchObject({
      home: 'star',
      chat: originalChatIcon,
    });

    usePreferencesStore.getState().resetNavigationIcons();
    expect(usePreferencesStore.getState().navigationIcons).toEqual(DEFAULT_NAVIGATION_ICONS);
  });

  it('switches among outline, emoji, and hidden modes', () => {
    expect(usePreferencesStore.getState().navigationIconMode).toBe('outline');

    usePreferencesStore.getState().setNavigationIconMode('emoji');
    expect(usePreferencesStore.getState().navigationIconMode).toBe('emoji');

    usePreferencesStore.getState().setNavigationIconMode('hidden');
    expect(usePreferencesStore.getState().navigationIconMode).toBe('hidden');

    usePreferencesStore.getState().reset();
    expect(usePreferencesStore.getState().navigationIconMode).toBe('outline');
  });
});
