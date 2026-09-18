import { afterEach, describe, expect, it } from 'vitest';
import { usePreferencesStore } from '@/stores/usePreferencesStore';
import {
  DEFAULT_NAVIGATION_ICONS,
  HEADER_NAV_ITEMS,
  NAVIGATION_ICON_OPTIONS,
  isHeaderNavigationItemActive,
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
    const originalTasksIcon = usePreferencesStore.getState().navigationIcons.tasks;

    usePreferencesStore.getState().setNavigationIcon('workbench', 'star');

    expect(usePreferencesStore.getState().navigationIcons).toMatchObject({
      workbench: 'star',
      tasks: originalTasksIcon,
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

  it('maps legacy feature routes into the five primary destinations', () => {
    const item = (id: string) => HEADER_NAV_ITEMS.find((value) => value.id === id)!;

    expect(isHeaderNavigationItemActive(item('workbench'), '/')).toBe(true);
    expect(isHeaderNavigationItemActive(item('tasks'), '/runs/run-1')).toBe(true);
    expect(isHeaderNavigationItemActive(item('apps'), '/chat')).toBe(true);
    expect(isHeaderNavigationItemActive(item('build'), '/automations/new')).toBe(true);
    expect(isHeaderNavigationItemActive(item('resources'), '/knowledge')).toBe(true);
    expect(isHeaderNavigationItemActive(item('workbench'), '/apps')).toBe(false);
  });

  it('keeps workbench active when an application was launched from its sidebar', () => {
    const item = (id: string) => HEADER_NAV_ITEMS.find((value) => value.id === id)!;

    expect(isHeaderNavigationItemActive(
      item('workbench'), '/applications/12/chat', '?slug=general-chat&entry=home',
    )).toBe(true);
    expect(isHeaderNavigationItemActive(
      item('apps'), '/applications/12/chat', '?slug=general-chat&entry=home',
    )).toBe(false);
    expect(isHeaderNavigationItemActive(item('workbench'), '/chat', '?entry=home')).toBe(true);
    expect(isHeaderNavigationItemActive(item('apps'), '/chat', '')).toBe(true);
  });
});
