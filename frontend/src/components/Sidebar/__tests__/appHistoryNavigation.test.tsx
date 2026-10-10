// @vitest-environment jsdom
import { act, type ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import AppHistorySidebar from '../AppHistorySidebar';

vi.mock('antd', () => ({
  Menu: () => null,
  Empty: () => null,
  Popconfirm: ({ children }: { children: ReactNode }) => <>{children}</>,
}));
vi.mock('@/stores/useAppStore', () => {
  const state = { categories: [], loadCategories: vi.fn(), selectCategory: vi.fn() };
  return { useAppStore: () => state };
});
vi.mock('@/stores/useProjectStore', () => {
  const state = {
  projects: [
    { id: 1, title: '关联应用', source: 'application', application_id: 12, updated_at: '2026-10-01' },
    { id: 2, title: '历史工作空间', source: 'application', updated_at: '2026-10-01' },
  ],
  loadProjects: vi.fn(), deleteProject: vi.fn(),
  };
  return { useProjectStore: () => state };
});
vi.mock('@/stores/useOrganizationStore', () => ({ useOrganizationStore: () => 'org' }));
vi.mock('@/services/api', () => ({ api: { get: vi.fn(async () => [
  { id: 'workflow-1', definition_snapshot: { workflow_name: '工作流历史' }, created_at: '2026-10-01' },
]) } }));

let host: HTMLDivElement;
let root: Root;
function Location() { const location = useLocation(); return <output>{location.pathname}</output>; }
beforeEach(async () => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  vi.spyOn(window, 'open').mockReturnValue(null);
  host = document.createElement('div');
  root = createRoot(host);
  await act(async () => root.render(<MemoryRouter initialEntries={['/apps']}><AppHistorySidebar /><Location /></MemoryRouter>));
});
afterEach(async () => {
  await act(async () => root.unmount());
  vi.restoreAllMocks(); vi.unstubAllGlobals();
});

it.each([
  ['关联应用', '/applications/12/run?entry=apps&standalone=1'],
  ['历史工作空间', '/workspace/2?entry=apps&standalone=1'],
])('opens %s separately without leaving the catalog', async (title, path) => {
  const row = [...host.querySelectorAll<HTMLElement>('.tpl-history-item')].find(item => item.textContent?.includes(title))!;
  await act(async () => row.click());
  expect(window.open).toHaveBeenCalledWith(path, '_blank', 'noopener,noreferrer');
  expect(host.querySelector('output')?.textContent).toBe('/apps');
});

it('keeps workflow history in the platform window', async () => {
  const row = [...host.querySelectorAll<HTMLElement>('.tpl-history-item')].find(item => item.textContent?.includes('工作流历史'))!;
  await act(async () => row.click());
  expect(window.open).not.toHaveBeenCalled();
  expect(host.querySelector('output')?.textContent).toBe('/runs/workflow-1');
});
