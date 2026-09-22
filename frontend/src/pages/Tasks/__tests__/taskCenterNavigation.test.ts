// @vitest-environment jsdom
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { ConfigProvider, message } from 'antd';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '@/services/api';
import type { RunResource } from '@/services/applicationRuntime';
import TaskCenterPage from '../TaskCenterPage';

vi.mock('@/services/api', () => ({ api: { get: vi.fn() } }));
vi.mock('@/stores/useOrganizationStore', () => {
  const state = { currentOrganizationId: 'org-1', loadOrganizations: vi.fn() };
  return { useOrganizationStore: (selector: (value: typeof state) => unknown) => selector(state) };
});

const run = (id: string): RunResource => ({
  id, organization_id: 'org-1', status: 'succeeded', version: 1,
  next_event_sequence: 1, definition_snapshot: {}, input: {}, output_summary: {},
  source_type: 'workflow', task_title: `任务 ${id}`,
});

let root: Root;
let container: HTMLDivElement;
let search: string;

function Page() {
  search = useLocation().search;
  return createElement(TaskCenterPage);
}

const render = async (entry: string) => act(async () => {
  root.render(createElement(MemoryRouter, { initialEntries: [entry] },
    createElement(ConfigProvider, { theme: { token: { motion: false } } }, createElement(Page))));
});

beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  vi.stubGlobal('matchMedia', vi.fn(() => ({
    matches: false, addListener: vi.fn(), removeListener: vi.fn(),
    addEventListener: vi.fn(), removeEventListener: vi.fn(),
  })));
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
  const getComputedStyle = window.getComputedStyle.bind(window);
  vi.spyOn(window, 'getComputedStyle').mockImplementation((element) => getComputedStyle(element));
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.restoreAllMocks();
  vi.resetAllMocks();
  vi.unstubAllGlobals();
});

describe('task center activity links', () => {
  it('opens the exact task and selects its table page', async () => {
    const runs = Array.from({ length: 25 }, (_, index) => run(`run-${index}`));
    vi.mocked(api.get).mockImplementation(async (url) => {
      if (url.endsWith('/runs')) return runs;
      if (url.endsWith('/children')) return [];
      return runs[24];
    });
    await render('/tasks?run=run-24&embedded=1');

    expect(document.querySelector('.task-detail-drawer .task-drawer-title')?.textContent)
      .toContain('任务 run-24');
    expect(container.querySelector('.ant-pagination-item-active')?.textContent).toBe('2');
    expect(container.querySelector('.task-desktop-table .task-row-selected')?.getAttribute('data-row-key'))
      .toBe('run-24');

    const close = document.querySelector<HTMLButtonElement>('.task-detail-drawer .ant-drawer-close');
    expect(close).not.toBeNull();
    await act(async () => close!.click());
    expect(new URLSearchParams(search).has('run')).toBe(false);
    expect(new URLSearchParams(search).get('embedded')).toBe('1');
    expect(document.querySelector('.task-detail-drawer .ant-drawer-open')).toBeNull();
  }, 15000);

  it('loads an exact task outside the recent list without changing summary counts', async () => {
    vi.mocked(api.get).mockImplementation(async (url) => {
      if (url.endsWith('/runs') || url.endsWith('/children')) return [];
      return run('older-run');
    });
    await render('/tasks?run=older-run');
    expect(document.querySelector('.task-detail-drawer .task-drawer-title')?.textContent)
      .toContain('任务 older-run');
    expect(container.querySelector('.task-total strong')?.textContent).toBe('0');
  });

  it('reports inaccessible tasks without opening unrelated details', async () => {
    const error = vi.spyOn(message, 'error').mockImplementation(() => (() => {}) as ReturnType<typeof message.error>);
    vi.mocked(api.get).mockImplementation(async (url) => {
      if (url.endsWith('/runs')) return [run('other-run')];
      throw new Error('Forbidden');
    });
    await render('/tasks?run=forbidden-run');
    expect(error).toHaveBeenCalledWith('无法打开该任务，任务不存在或你没有访问权限');
    expect(document.querySelector('.task-detail-drawer .task-drawer-title')).toBeNull();
  });

  it('does not reopen details when a request finishes after the drawer is closed', async () => {
    let resolveDetail!: (value: RunResource) => void;
    const detail = new Promise<RunResource>((resolve) => { resolveDetail = resolve; });
    vi.mocked(api.get).mockImplementation(async (url) => url.endsWith('/runs') ? [] : detail);
    await render('/tasks?run=slow-run');
    const close = document.querySelector<HTMLButtonElement>('.task-detail-drawer .ant-drawer-close');
    expect(close).not.toBeNull();
    await act(async () => close!.click());
    await act(async () => resolveDetail(run('slow-run')));
    expect(new URLSearchParams(search).has('run')).toBe(false);
    expect(document.querySelector('.task-detail-drawer .task-drawer-title')).toBeNull();
  });
});
