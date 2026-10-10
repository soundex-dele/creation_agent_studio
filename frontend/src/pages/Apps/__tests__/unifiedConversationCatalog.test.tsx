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
const drawing: AppItem = { ...cowork, id: 'drawing', applicationId: 2, name: '绘图', rendererKey: 'ai-drawing' };
const research: AppItem = { ...cowork, id: 'research', applicationId: 3, name: '研究', rendererKey: 'research-assistant' };
const session = { userId: 1, layoutMode: 'top-bottom' };
const state = { apps: [cowork], isLoading: false, error: null, categories: [],
  selectedCategory: null as string | null, searchQuery: '',
  loadApps: vi.fn(), loadCategories: vi.fn(), setSearchQuery: vi.fn(), selectCategory: vi.fn() };
vi.mock('@/stores/useAppStore', () => ({ useAppStore: () => state }));
vi.mock('@/stores/useAuthStore', () => ({ useAuthStore: (select: (state: unknown) => unknown) => select({ user: { id: session.userId } }) }));
vi.mock('@/stores/usePreferencesStore', () => ({ usePreferencesStore: (select: (state: unknown) => unknown) => select({ layoutMode: session.layoutMode }) }));

let host: HTMLDivElement;
let root: Root;
function Location() { const location = useLocation(); return <output>{location.pathname}{location.search}</output>; }
const render = async (home = false, entry = '/') => act(async () => root.render(
  <MemoryRouter initialEntries={[entry]}>{home ? <HomeApplicationsSidebar /> : <AppsPage />}<Location /></MemoryRouter>,
));

beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  vi.spyOn(window, 'open').mockReturnValue(null);
  window.matchMedia = vi.fn().mockImplementation(query => ({ matches: false, media: query,
    addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() }));
  window.localStorage.clear();
  state.apps = [cowork]; state.selectedCategory = null; state.searchQuery = '';
  state.error = null; state.isLoading = false;
  session.userId = 1; session.layoutMode = 'top-bottom';
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount()); host.remove();
  window.localStorage.clear(); vi.restoreAllMocks(); vi.unstubAllGlobals();
});

it('migrates recent cowork usage to the unified conversation entry and records reopening', async () => {
  localStorage.setItem('application-preferences:1', JSON.stringify({ favorites: [], recent: { cowork: 100 } }));
  await render(true);
  expect(host.querySelectorAll('.home-app-item')).toHaveLength(1);
  expect(host.querySelector('.home-app-copy strong')?.textContent).toBe('对话');
  await act(async () => host.querySelector<HTMLButtonElement>('.home-app-item')!.click());
  expect(window.open).toHaveBeenCalledWith('/chat?entry=apps&standalone=1', '_blank', 'noopener,noreferrer');
  expect(host.querySelector('output')?.textContent).toBe('/');
  const saved = JSON.parse(localStorage.getItem('application-preferences:1')!);
  expect(saved.recent.cowork).toBeUndefined();
  expect(saved.recent['platform-conversation']).toBeGreaterThan(100);
});

it('shows only available used apps in most-recent order regardless of old home configuration', async () => {
  state.apps = [cowork, drawing, research];
  localStorage.setItem('home-applications:1', JSON.stringify({ order: ['drawing'], hidden: ['research'] }));
  localStorage.setItem('application-preferences:1', JSON.stringify({
    favorites: ['drawing'], recent: { drawing: 100, research: 200, removed: 300 },
  }));
  await render(true);
  const names = () => Array.from(host.querySelectorAll('.home-app-copy strong'), node => node.textContent);
  expect(names()).toEqual(['研究', '绘图']);
  expect(host.querySelector('.sidebar-title')?.textContent).toBe('最近使用');
  expect(host.querySelector('[aria-label="配置首页应用"]')).toBeNull();
  await act(async () => host.querySelector<HTMLButtonElement>('[aria-label="绘图（在新窗口打开）"]')!.click());
  expect(names()).toEqual(['绘图', '研究']);
  expect(window.open).toHaveBeenCalledWith('/applications/2/ai-drawing?entry=apps&standalone=1', '_blank', 'noopener,noreferrer');
  expect(host.querySelector('output')?.textContent).toBe('/');
  expect(JSON.parse(localStorage.getItem('application-preferences:1')!).favorites).toEqual(['drawing']);
});

it('shows an empty state and a working all-apps entry for a new user', async () => {
  await render(true);
  expect(host.querySelectorAll('.home-app-item')).toHaveLength(0);
  expect(host.textContent).toContain('暂无最近使用的应用');
  await act(async () => host.querySelector<HTMLButtonElement>('.home-all-apps')!.click());
  expect(host.querySelector('output')?.textContent).toBe('/apps');
});

it.each(['left-right', 'top-bottom'])('opens recent apps in a new window from any sidebar under %s', async layoutMode => {
  session.layoutMode = layoutMode;
  state.apps = [drawing];
  localStorage.setItem('application-preferences:1', JSON.stringify({ recent: { drawing: 100 } }));
  await render(true, '/applications/3/research-assistant?entry=home');
  await act(async () => host.querySelector<HTMLButtonElement>('.home-app-item')!.click());
  expect(window.open).toHaveBeenCalledWith('/applications/2/ai-drawing?entry=apps&standalone=1', '_blank', 'noopener,noreferrer');
  expect(host.querySelector('output')?.textContent).toBe('/applications/3/research-assistant?entry=home');
});

it('shares catalog usage with the workbench and retains new-window behavior', async () => {
  state.apps = [drawing];
  const open = vi.spyOn(window, 'open').mockReturnValue(null);
  await render();
  await act(async () => host.querySelector<HTMLElement>('[aria-label="绘图（在新窗口中打开）"]')!.click());
  session.layoutMode = 'left-right';
  await render(true);
  expect(host.querySelectorAll('.home-app-item')).toHaveLength(1);
  await act(async () => host.querySelector<HTMLButtonElement>('.home-app-item')!.click());
  expect(open).toHaveBeenCalledTimes(2);
  expect(open).toHaveBeenLastCalledWith('/applications/2/ai-drawing?entry=apps&standalone=1', '_blank', 'noopener,noreferrer');
});

it('refreshes other-window usage, isolates users, and handles cleared history', async () => {
  state.apps = [drawing];
  await render(true);
  localStorage.setItem('application-preferences:1', JSON.stringify({ recent: { drawing: 100 } }));
  await act(async () => window.dispatchEvent(new StorageEvent('storage', { key: 'application-preferences:1' })));
  expect(host.querySelectorAll('.home-app-item')).toHaveLength(1);
  session.userId = 2;
  await render(true);
  expect(host.querySelectorAll('.home-app-item')).toHaveLength(0);
  session.userId = 1;
  await render(true);
  expect(host.querySelectorAll('.home-app-item')).toHaveLength(1);
  localStorage.clear();
  await act(async () => window.dispatchEvent(new StorageEvent('storage', { key: null })));
  expect(host.querySelectorAll('.home-app-item')).toHaveLength(0);
});

it.each(['broken json', '{"recent":{"drawing":"100","research":-1}}'])('ignores invalid history: %s', async saved => {
  state.apps = [drawing, research];
  localStorage.setItem('application-preferences:1', saved);
  await render(true);
  expect(host.querySelectorAll('.home-app-item')).toHaveLength(0);
});

it('keeps navigation working when persisting history fails', async () => {
  localStorage.setItem('application-preferences:1', JSON.stringify({ recent: { cowork: 100 } }));
  await render(true);
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('Storage unavailable'); });
  await act(async () => host.querySelector<HTMLButtonElement>('.home-app-item')!.click());
  expect(window.open).toHaveBeenCalledWith('/chat?entry=apps&standalone=1', '_blank', 'noopener,noreferrer');
  expect(host.querySelector('output')?.textContent).toBe('/');
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
