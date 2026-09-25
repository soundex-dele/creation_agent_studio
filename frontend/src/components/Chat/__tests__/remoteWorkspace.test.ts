// @vitest-environment jsdom
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { api } from '@/services/api';
import { createConnectionApi } from '@/services/chatConnection';
import { createConversationStore } from '@/stores/useConversationStore';
import { ChatConnectionContext } from '../ChatConnectionContext';
import MessageInput, { type ComposerContext } from '../MessageInput';
import ChatContainer from '../ChatContainer';
import type { ConversationDetail } from '@/stores/useConversationStore';

const local = vi.hoisted(() => ({ load: vi.fn() }));
vi.mock('@/stores/useAuthStore', () => ({ useAuthStore: () => ({ user: { id: 1 } }) }));
vi.mock('@/stores/useAgentStore', () => ({ useAgentStore: () => ({ agents: [], loadAgents: local.load }) }));
vi.mock('@/stores/useProjectStore', () => ({ useProjectStore: () => ({
  projects: [{ id: 99, title: 'Server-only workspace' }], loadProjects: local.load,
}) }));

const prefix = '/remote/devices/computer/proxy';
const directory = '/Users/owner/项目 空间';
let host: HTMLDivElement;
let root: Root;
let get: ReturnType<typeof vi.spyOn>;
let post: ReturnType<typeof vi.spyOn>;
let store: ReturnType<typeof createConversationStore>;

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  local.load.mockClear();
  HTMLElement.prototype.scrollTo = vi.fn();
  window.matchMedia = vi.fn().mockImplementation(query => ({ matches: false, media: query,
    addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() }));
  const computedStyle = window.getComputedStyle.bind(window);
  vi.spyOn(window, 'getComputedStyle').mockImplementation(element => computedStyle(element));
  get = vi.spyOn(api, 'get').mockImplementation(async (path, params) => {
    if (path === `${prefix}/projects/`) return { results: [{ id: 7, title: 'Computer workspace' }], next: null };
    if (path === `${prefix}/agents/`) return [];
    if (path === `${prefix}/conversations/composer-options/`) return { skills: [], require_tool_approval: false };
    if (path === `${prefix}/apps/runtime-files/list/`) return params?.path
      ? { path: directory, parent: '/Users/owner', roots: [], dirs: [] }
      : { path: '', parent: '', roots: [{ name: '项目 空间', path: directory }], dirs: [] };
    throw new Error(`Unexpected request: ${path}`);
  });
  post = vi.spyOn(api, 'post').mockResolvedValue({ id: 1, title: 'hello' });
  store = createConversationStore({ deviceId: 'computer' });
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  store.getState().disconnect();
  vi.restoreAllMocks();
});

async function render(props = {}) {
  await act(async () => root.render(React.createElement(ChatConnectionContext.Provider, {
    value: { store, api: createConnectionApi({ deviceId: 'computer' }), remote: true, online: true },
  }, React.createElement(MessageInput, {
    value: 'hello',
    onSendMessage: async (text: string, composer: ComposerContext) => {
      await store.getState().createConversation(text, undefined, composer.projectId, undefined, {
        workingDirectory: composer.workingDirectory,
      });
    },
    ...props,
  }))));
}

async function click(selector: string, text?: string) {
  const element = Array.from(document.querySelectorAll<HTMLElement>(selector))
    .find(item => text === undefined || item.textContent?.includes(text));
  expect(element, text || selector).toBeDefined();
  await act(async () => element!.click());
}

it('selects a workspace from the computer and retains the new chat in remote history', async () => {
  await render();
  expect(local.load).not.toHaveBeenCalled();
  expect(host.querySelector<HTMLButtonElement>('[aria-label="选择工作空间"]')!.disabled).toBe(false);
  await click('[aria-label="选择工作空间"]');
  expect(document.body.textContent).not.toContain('Server-only workspace');
  await click('[role="menuitem"]', 'Computer workspace');
  await click('[aria-label="发送消息"]');
  expect(post).toHaveBeenCalledWith(`${prefix}/conversations/`, { title: 'hello', project_id: 7 }, expect.any(Object));
  expect(store.getState().conversations.map(item => item.id)).toEqual(['1']);
});

it('browses the computer filesystem and sends its selected folder when creating the chat', async () => {
  await render();
  await click('[aria-label="选择工作空间"]');
  await click('[role="menuitem"]', '选择系统目录');
  expect(document.body.textContent).toContain('选择电脑上的文件夹');
  await click('.ant-list-item', '项目 空间');
  await click('.ant-modal-footer button', '选择此文件夹');
  expect(host.textContent).toContain(directory);
  await click('[aria-label="发送消息"]');
  expect(post).toHaveBeenCalledWith(`${prefix}/conversations/`, { title: 'hello', working_directory: directory }, expect.any(Object));
  expect(vi.mocked(api.get).mock.calls.every(([path]) => path.startsWith(prefix))).toBe(true);
  expect(get).toHaveBeenCalledWith(`${prefix}/apps/runtime-files/list/`, { path: directory }, expect.any(Object));
});

it.each([{ workspaceLocked: true }, { disabled: true }])('keeps workspace selection locked when unavailable (%s)', async props => {
  await render(props);
  expect(host.querySelector<HTMLButtonElement>('[aria-label="选择工作空间"]')!.disabled).toBe(true);
});

async function renderExisting(locked = false, online = true) {
  store.setState({
    currentConversation: {
      id: '1', title: 'Existing chat', messages: [], workspace_locked: locked,
      working_directory: '/Users/owner/original',
    } as unknown as ConversationDetail,
    refreshIfIdle: vi.fn(async () => {}),
  });
  await act(async () => root.render(React.createElement(ChatConnectionContext.Provider, {
    value: { store, api: createConnectionApi({ deviceId: 'computer' }), remote: true, online },
  }, React.createElement(ChatContainer, { conversationId: '1', autoFetch: false }))));
}

it('enables and persists workspace selection in an existing remote conversation', async () => {
  await renderExisting();
  expect(host.querySelector<HTMLButtonElement>('[aria-label="选择工作空间"]')!.disabled).toBe(false);
  expect(host.textContent).toContain('/Users/owner/original');
  post.mockResolvedValue({ ...store.getState().currentConversation, project: 7, working_directory: directory });
  await click('[aria-label="选择工作空间"]');
  await click('[role="menuitem"]', 'Computer workspace');
  expect(post).toHaveBeenCalledWith(`${prefix}/conversations/1/workspace/`, {
    project_id: 7, working_directory: '',
  }, expect.any(Object));
  expect(store.getState().currentConversation?.project).toBe(7);
  expect(host.textContent).toContain('Computer workspace');
});

it('keeps the previous workspace when saving fails', async () => {
  await renderExisting();
  post.mockRejectedValue(new Error('offline'));
  await click('[aria-label="选择工作空间"]');
  await click('[role="menuitem"]', 'Computer workspace');
  expect(store.getState().currentConversation?.working_directory).toBe('/Users/owner/original');
  expect(host.querySelector('[aria-label="选择工作空间"]')!.textContent).toContain('/Users/owner/original');
});

it.each([[true, true], [false, false]])('keeps fixed or offline remote workspaces locked (%s, %s)', async (locked, online) => {
  await renderExisting(locked, online);
  expect(host.querySelector<HTMLButtonElement>('[aria-label="选择工作空间"]')!.disabled).toBe(true);
});

it('blocks sending and further workspace changes while saving', async () => {
  await renderExisting();
  let resolveSave!: (value: unknown) => void;
  post.mockImplementation(() => new Promise(resolve => { resolveSave = resolve; }));
  await click('[aria-label="选择工作空间"]');
  await click('[role="menuitem"]', 'Computer workspace');
  expect(host.querySelector<HTMLButtonElement>('[aria-label="选择工作空间"]')!.disabled).toBe(true);
  expect(host.querySelector<HTMLTextAreaElement>('textarea')!.disabled).toBe(true);
  await act(async () => resolveSave({ ...store.getState().currentConversation, project: 7, working_directory: directory }));
  expect(host.querySelector<HTMLButtonElement>('[aria-label="选择工作空间"]')!.disabled).toBe(false);
});
