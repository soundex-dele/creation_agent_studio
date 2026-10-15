// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { ConfigProvider } from 'antd';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { api } from '@/services/api';
import ChatApplicationRuntimePage from '../ChatApplicationRuntimePage';

vi.setConfig({ testTimeout: 30000 });

const mocks = vi.hoisted(() => ({ loadApp: vi.fn() }));
vi.mock('@/services/api', () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() } }));
vi.mock('@/stores/useAppStore', () => ({ useAppStore: (select: (state: unknown) => unknown) => select({ loadApp: mocks.loadApp }) }));
vi.mock('@/stores/useOrganizationStore', () => ({ useOrganizationStore: (select: (state: unknown) => unknown) => select({ currentOrganizationId: 'org-1' }) }));
vi.mock('@/stores/useAuthStore', () => ({ useAuthStore: (select: (state: unknown) => unknown) => select({ user: { id: 'user-1' } }) }));
vi.mock('@/components/Chat/ChatContainer', () => ({ default: ({ conversationId }: { conversationId: string }) => <div data-testid="conversation">{conversationId}</div> }));

let root: Root; let container: HTMLDivElement;
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} })));
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
  const computed = window.getComputedStyle.bind(window); vi.spyOn(window, 'getComputedStyle').mockImplementation(el => computed(el));
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); vi.restoreAllMocks(); vi.resetAllMocks(); vi.unstubAllGlobals(); });

async function mount(slug: string, conversation = '') {
  const draft = { source: '选题：从文章到排版\n素材：真实功能与限制', requirements: '仅依据来源事实', task: 'full-article', audience: '创作者' };
  mocks.loadApp.mockResolvedValue({ id: slug, applicationId: 10, name: '创作应用', kind: 'chat', runtime: {
    default_config: {}, chat_profile: {}, agent_bindings: [],
    guided_prompts: [{ id: 'write', key: 'write', title: '创作需求', questions: Object.keys(draft).map(key => ({ id: key, key, label: key, type: 'text', required: true, default_value: '' })) }],
  } });
  vi.mocked(api.get).mockResolvedValue({ id: 'handoff1', revision: 0, draft, target_id: conversation });
  vi.mocked(api.post).mockResolvedValue({ prompt: '生成的写作提示词', normalized_answers: draft });
  const router = createMemoryRouter([{ path: '/applications/:applicationId/chat', element: <ChatApplicationRuntimePage /> }], {
    initialEntries: [`/applications/10/chat?slug=${slug}&promotionApplication=1&promotionHandoff=handoff1${conversation ? `&conversation=${conversation}` : ''}`],
  });
  await act(async () => root.render(<ConfigProvider theme={{ token: { motion: false } }}><RouterProvider router={router} /></ConfigProvider>));
  return draft;
}

it('loads the topic handoff into the creative form without a return or import action', async () => {
  const draft = await mount('wechat-viral-article');
  expect(api.get).toHaveBeenCalledWith('/organizations/org-1/applications/1/project-promotion/handoffs/handoff1');
  for (const [key, value] of Object.entries(draft)) {
    const label = [...container.querySelectorAll('label')].find(l => l.textContent?.includes(key));
    expect(label).toBeDefined();
    expect(label!.querySelector('textarea')?.value).toBe(value);
  }
  expect(container.querySelector('a[href*="project-promotion"]')).toBeNull();
  expect(container.textContent).not.toContain('回存');
  expect(container.textContent).not.toContain('返回项目宣传助手');
  expect(api.post).not.toHaveBeenCalled();
});

it('resumes the creative conversation directly without routing back to promotion', async () => {
  await mount('wechat-viral-article', '42');
  expect(container.querySelector('[data-testid="conversation"]')?.textContent).toBe('42');
  expect(container.querySelector('a[href*="project-promotion"]')).toBeNull();
});
