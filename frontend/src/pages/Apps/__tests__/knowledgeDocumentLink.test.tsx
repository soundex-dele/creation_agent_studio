// @vitest-environment jsdom
import { act } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { api } from '@/services/api';
import KnowledgePage from '../../Knowledge/KnowledgePage';

vi.mock('@/services/api', () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } }));
vi.mock('@/features/run-stream', () => ({ useRunStream: () => ({ state: {}, error: null }) }));
const loadOrganizations = vi.fn();
vi.mock('@/stores/useOrganizationStore', () => ({ useOrganizationStore: () => ({ organizations: [{ id: 'org', role: 'developer' }], currentOrganizationId: 'org', loadOrganizations }) }));
let container: HTMLDivElement; let root: Root;
beforeEach(() => {
  vi.clearAllMocks(); vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  Object.defineProperty(window, 'matchMedia', { writable: true, value: vi.fn(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() })) });
  const style = window.getComputedStyle; vi.spyOn(window, 'getComputedStyle').mockImplementation(el => style(el));
  vi.mocked(api.get).mockImplementation(async url => {
    if (url.endsWith('/knowledge-bases/')) return [{ id: 1, name: '其他库' }, { id: 2, name: '目标库' }];
    if (url.endsWith('/documents/')) return [{ id: 7, knowledge_base_id: 2, title: '已分享知识', status: 'ready', byte_size: 100, metadata: { source_kind: 'douyin_knowledge', card_revision: 3 } }];
    return { id: 2, name: '目标库', description: '团队资料' };
  });
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it('opens the linked library and highlights its document with provenance', async () => {
  await act(async () => root.render(<MemoryRouter initialEntries={['/knowledge?base=2&document=7']}><KnowledgePage /></MemoryRouter>));
  expect(api.get).toHaveBeenCalledWith('/organizations/org/knowledge-bases/2/documents/');
  const document = container.querySelector('#knowledge-document-7');
  expect(document?.classList.contains('knowledge-document-linked')).toBe(true);
  expect(document?.textContent).toContain('来自抖音对标助手 · 卡片 v3');
  expect(window.document.activeElement).toBe(document);
  const refresh = [...container.querySelectorAll<HTMLButtonElement>('button')].find(el => el.textContent === '刷新')!;
  refresh.focus(); await act(async () => refresh.click());
  expect(window.document.activeElement).toBe(refresh);
});

it('explains when a linked document no longer exists', async () => {
  await act(async () => root.render(<MemoryRouter initialEntries={['/knowledge?base=2&document=99']}><KnowledgePage /></MemoryRouter>));
  expect(container.textContent).toContain('目标文档已删除或不可访问');
});
