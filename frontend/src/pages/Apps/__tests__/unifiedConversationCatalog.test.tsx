// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import HomeApplicationsSidebar from '@/components/Sidebar/HomeApplicationsSidebar';
import AppsPage from '../AppsPage';
import type { AppItem } from '@/types';

const cowork: AppItem = { id: 'cowork', applicationId: 99, name: 'CoWork', description: '旧应用',
  category: 'productivity', rendererKey: 'cowork', icon: 'folder', tags: ['文件夹'], kind: 'custom' };
const state = { apps: [cowork], isLoading: false, error: null, categories: [],
  selectedCategory: null as string | null, searchQuery: '',
  loadApps: vi.fn(), loadCategories: vi.fn(), setSearchQuery: vi.fn(), selectCategory: vi.fn() };
vi.mock('@/stores/useAppStore', () => ({ useAppStore: () => state }));
vi.mock('@/stores/useAuthStore', () => ({ useAuthStore: (select: (state: unknown) => unknown) => select({ user: { id: 1 } }) }));
vi.mock('@/stores/usePreferencesStore', () => ({ usePreferencesStore: (select: (state: unknown) => unknown) => select({ layoutMode: 'top-bottom' }) }));

let host: HTMLDivElement;
let root: Root;
function Location() { const location = useLocation(); return <output>{location.pathname}{location.search}</output>; }
const render = async (home = false) => act(async () => root.render(
  <MemoryRouter>{home ? <HomeApplicationsSidebar /> : <AppsPage />}<Location /></MemoryRouter>,
));

beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  window.matchMedia = vi.fn().mockImplementation(query => ({ matches: false, media: query,
    addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() }));
  window.localStorage.clear();
  state.apps = [cowork]; state.selectedCategory = null; state.searchQuery = '';
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount()); host.remove();
  window.localStorage.clear(); vi.restoreAllMocks(); vi.unstubAllGlobals();
});

it('shows one home entry and preserves the old conversation preference ahead of cowork', async () => {
  localStorage.setItem('home-applications:1', JSON.stringify({
    order: ['cowork', 'platform-conversation'], hidden: ['cowork'],
  }));
  await render(true);
  expect(host.querySelectorAll('.home-app-item')).toHaveLength(1);
  expect(host.querySelector('.home-app-copy strong')?.textContent).toBe('对话');
  await act(async () => host.querySelector<HTMLButtonElement>('.home-app-item')!.click());
  expect(host.querySelector('output')?.textContent).toBe('/chat?entry=home');
  expect(JSON.parse(localStorage.getItem('home-applications:1')!)).toEqual({
    order: ['platform-conversation'], hidden: [],
  });
});

it('shows one catalog card and migrates cowork favorites and recent usage', async () => {
  localStorage.setItem('application-preferences:1', JSON.stringify({
    favorites: ['cowork'], recent: { cowork: 100 },
  }));
  const open = vi.spyOn(window, 'open').mockReturnValue(null);
  await render();
  expect(host.querySelectorAll('.app-card')).toHaveLength(1);
  expect(host.querySelector('[aria-label="取消收藏对话"]')).not.toBeNull();
  expect(JSON.parse(localStorage.getItem('application-preferences:1')!)).toEqual({
    favorites: ['platform-conversation'], recent: { 'platform-conversation': 100 },
  });
  await act(async () => host.querySelector<HTMLElement>('.app-card')!.click());
  expect(open).toHaveBeenCalledWith('/chat?entry=apps&standalone=1', '_blank', 'noopener,noreferrer');
});

it.each(['文件夹', 'cowork', '对话'])('keeps the unified entry searchable by %s in its catalog category', async query => {
  state.selectedCategory = 'productivity'; state.searchQuery = query;
  await render();
  expect(host.querySelectorAll('.app-card')).toHaveLength(1);
  expect(host.querySelector('.app-card-name')?.textContent).toBe('对话');
});
