// @vitest-environment jsdom
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { ConfigProvider } from 'antd';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { api } from '@/services/api';
import type { RunResource } from '@/services/applicationRuntime';
import HomePage from '../HomePage';

const state = vi.hoisted(() => ({
  user: { id: 'user-1', username: '用户一' } as { id: string; username: string } | null,
  currentOrganizationId: 'org-1' as string | null,
  loadOrganizations: vi.fn(),
}));
vi.mock('@/services/api', () => ({ api: { get: vi.fn() } }));
vi.mock('@/stores/useAuthStore', () => ({
  useAuthStore: (selector: (value: typeof state) => unknown) => selector(state),
}));
vi.mock('@/stores/useOrganizationStore', () => ({
  useOrganizationStore: (selector: (value: typeof state) => unknown) => selector(state),
}));
vi.mock('@/stores/usePreferencesStore', () => ({
  usePreferencesStore: (selector: (value: { layoutMode: string }) => unknown) =>
    selector({ layoutMode: 'top-bottom' }),
}));
vi.mock('@/components/Sidebar/HomeApplicationsSidebar', () => ({ default: () => null }));

const run = (id: string, status: RunResource['status'] = 'failed'): RunResource => ({
  id, organization_id: 'org-1', status, version: 1, next_event_sequence: 1,
  definition_snapshot: {}, input: {}, output_summary: {},
  source_type: 'application', task_title: `任务 ${id}`,
});

let root: Root;
let container: HTMLDivElement;
const render = () => act(async () => {
  root.render(createElement(MemoryRouter, null,
    createElement(ConfigProvider, { theme: { token: { motion: false } } }, createElement(HomePage))));
});
const counts = () => [...container.querySelectorAll('.home-overview strong')].map(item => item.textContent);

beforeEach(() => {
  state.user = { id: 'user-1', username: '用户一' };
  state.currentOrganizationId = 'org-1';
  localStorage.clear();
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  vi.stubGlobal('matchMedia', vi.fn(() => ({
    matches: false, addListener: vi.fn(), removeListener: vi.fn(),
    addEventListener: vi.fn(), removeEventListener: vi.fn(),
  })));
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  localStorage.clear();
  vi.restoreAllMocks();
  vi.resetAllMocks();
  vi.unstubAllGlobals();
});

it.each([false, true])('loads personal activity and counts (single tenant: %s)', async (singleTenant) => {
  localStorage.setItem('organization-storage', JSON.stringify({ state: { singleTenantMode: singleTenant } }));
  vi.mocked(api.get).mockResolvedValue([run('my-failed'), run('my-completed', 'succeeded')]);
  await render();
  const url = singleTenant ? '/runs' : '/organizations/org-1/runs';
  expect(api.get).toHaveBeenCalledWith(url, { collapse_conversations: true, scope: 'mine' });
  expect(container.querySelector('.home-recent-list')?.textContent).toContain('任务 my-failed');
  expect(counts()).toEqual(['0', '0', '1', '1']);
  await act(async () => {
    [...container.querySelectorAll('button')].find(button => button.textContent === '刷新')!.click();
  });
  expect(api.get).toHaveBeenLastCalledWith(url, { collapse_conversations: true, scope: 'mine' });
});

it.each(['resolve', 'reject'])('ignores a previous user request that later %s', async (outcome) => {
  let resolveOld!: (runs: RunResource[]) => void;
  let rejectOld!: (error: Error) => void;
  const oldRequest = new Promise<RunResource[]>((resolve, reject) => {
    resolveOld = resolve;
    rejectOld = reject;
  });
  vi.mocked(api.get).mockReturnValueOnce(oldRequest).mockResolvedValueOnce([run('user-2')]);
  await render();
  state.user = { id: 'user-2', username: '用户二' };
  await render();
  expect(api.get).toHaveBeenCalledTimes(2);
  expect(container.textContent).toContain('任务 user-2');
  await act(async () => {
    if (outcome === 'resolve') resolveOld([run('user-1')]);
    else rejectOld(new Error('Old request failed'));
  });
  expect(container.textContent).toContain('任务 user-2');
  expect(container.textContent).not.toContain('任务 user-1');
  expect(counts()).toEqual(['0', '0', '0', '1']);
});

it('clears previous activity while changing organization and handles a failed load', async () => {
  let rejectNew!: (error: Error) => void;
  vi.mocked(api.get).mockResolvedValueOnce([run('old-org')]).mockReturnValueOnce(
    new Promise((_resolve, reject) => { rejectNew = reject; }),
  );
  await render();
  expect(container.textContent).toContain('任务 old-org');
  state.currentOrganizationId = 'org-2';
  await render();
  expect(api.get).toHaveBeenLastCalledWith('/organizations/org-2/runs', {
    collapse_conversations: true, scope: 'mine',
  });
  expect(container.textContent).not.toContain('任务 old-org');
  expect(counts()).toEqual(['0', '0', '0', '0']);
  await act(async () => rejectNew(new Error('Failed to load')));
  expect(container.textContent).toContain('暂无任务');
});

it.each(['user', 'organization'])('clears history without loading when %s is missing', async (missing) => {
  vi.mocked(api.get).mockResolvedValue([run('previous')]);
  await render();
  expect(container.textContent).toContain('任务 previous');
  if (missing === 'user') state.user = null;
  else state.currentOrganizationId = null;
  await render();
  expect(api.get).toHaveBeenCalledTimes(1);
  expect(container.textContent).not.toContain('任务 previous');
  expect(counts()).toEqual(['0', '0', '0', '0']);
});
