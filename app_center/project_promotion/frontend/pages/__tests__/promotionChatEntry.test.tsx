// @vitest-environment jsdom
import { act } from 'react';
import { parse } from 'yaml';
import explorerManifest from '../../../../../app_center/topic_explorer/application.yaml?raw';
import { createRoot, type Root } from 'react-dom/client';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { ConfigProvider } from 'antd';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { api } from '@platform/http';
import ChatApplicationRuntimePage from '@platform/pages/Apps/ChatApplicationRuntimePage';

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
  const draft: Record<string, string> = slug === 'topic-explorer'
    ? { source: '已选素材：真实功能与限制', requirements: '不做功能清单', audience: '', platform: 'wechat', content_type: '', goal: '', direction: '' }
    : { source: '选题：从文章到排版\n素材：真实功能与限制', requirements: '仅依据来源事实', task: 'full-article', audience: '创作者' };
  const explorer = parse(explorerManifest).spec.definition;
  mocks.loadApp.mockResolvedValue({ id: slug, applicationId: 10, name: '创作应用', kind: 'chat', runtime: {
    default_config: {}, chat_profile: {}, agent_bindings: [],
    guided_prompts: slug === 'topic-explorer' ? explorer.guided_prompts : [{ id: 'write', key: 'write', title: '创作需求', questions: Object.keys(draft).map(key => ({ id: key, key, label: key, type: 'text', required: true, default_value: '' })) }],
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

it('loads exploration fields without submitting, saves added scope and explicitly clears the platform', async () => {
  const draft = await mount('topic-explorer');
  expect(api.post).not.toHaveBeenCalled();
  const label = (name: string) => [...container.querySelectorAll('label')].find(l => l.textContent?.startsWith(name))!;
  expect(label('想法或素材').querySelector('textarea')?.value).toBe(draft.source);
  expect(label('发布平台').textContent).toContain('公众号');
  expect(label('内容形式').textContent).toContain('暂不确定');
  expect(label('本次主要目标').textContent).toContain('暂不确定');
  expect(label('目标读者').querySelector('textarea')?.value).toBe('');
  vi.mocked(api.patch).mockImplementation(async (_url, value) => {
    const update = value as { revision: number; draft: Record<string, string> };
    return { id: 'handoff1', revision: update.revision + 1, draft: update.draft };
  });
  await act(async () => {
    label('发布平台').querySelector('.ant-select-clear')!.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
    const input = label('目标读者').querySelector('textarea')!;
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(input, '独立创作者');
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await act(async () => [...container.querySelectorAll('button')].find(b => b.textContent === '生成提示词')!.click());
  expect(api.patch).toHaveBeenCalledWith(expect.stringContaining('/handoffs/handoff1'), expect.objectContaining({
    draft: expect.objectContaining({ source: draft.source, audience: '独立创作者', platform: '', goal: '', content_type: '' }),
  }));
  expect(api.post).toHaveBeenCalledWith('/apps/topic-explorer/compose-prompt/', expect.objectContaining({
    answers: expect.objectContaining({ platform: '', audience: '独立创作者' }),
  }));
  expect(container.querySelector('[data-testid="conversation"]')).toBeNull();
});

it('resumes the exploration conversation', async () => {
  await mount('topic-explorer', '53');
  expect(container.querySelector('[data-testid="conversation"]')?.textContent).toBe('53');
  expect(api.post).not.toHaveBeenCalled();
});
