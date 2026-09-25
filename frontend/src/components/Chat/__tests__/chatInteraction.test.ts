// @vitest-environment jsdom
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { message } from 'antd';
import { useConversationStore, type ConversationDetail } from '@/stores/useConversationStore';
import { ChatConnectionContext } from '../ChatConnectionContext';
import { api } from '@/services/api';
import ChatContainer, { type ChatContainerProps } from '../ChatContainer';
import MessageList from '../MessageList';

vi.mock('@/stores/useAuthStore', () => ({ useAuthStore: () => ({ user: { id: 1 } }) }));
vi.mock('@/stores/useAgentStore', () => ({ useAgentStore: () => ({ agents: [], loadAgents: vi.fn() }) }));
vi.mock('@/stores/useProjectStore', () => ({ useProjectStore: () => ({ projects: [], loadProjects: vi.fn() }) }));
vi.mock('@/pages/Apps/FolderPickerModal', () => ({ default: () => null }));
vi.mock('../AgentQuestionCard', () => ({ default: () => null }));

let root: Root;
let host: HTMLDivElement;
let mobile: boolean;
const initialState = useConversationStore.getState();
const historyMessage = { id: 'm1', role: 'user' as const, content: '已有消息', created_at: '2026-09-23T03:20:00Z' };
const cancelTurn = vi.fn(async () => {});

beforeEach(() => {
  mobile = true;
  cancelTurn.mockReset();
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  window.matchMedia = vi.fn().mockImplementation(query => ({ matches: mobile, media: query,
    addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn() }));
  HTMLElement.prototype.scrollTo = vi.fn();
  // jsdom does not implement pseudo-element styles used by Drawer scrollbar measurement.
  const getComputedStyle = window.getComputedStyle.bind(window);
  vi.spyOn(window, 'getComputedStyle').mockImplementation(element => getComputedStyle(element));
  vi.spyOn(api, 'get').mockResolvedValue({ skills: [], require_tool_approval: false });
  useConversationStore.setState({
    ...initialState,
    currentConversation: { id: 'c1', messages: [historyMessage] } as ConversationDetail,
    cancelTurn,
    disconnect: vi.fn(),
    refreshIfIdle: vi.fn(async () => {}),
  });
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  useConversationStore.setState(initialState, true);
  vi.restoreAllMocks();
  vi.useRealTimers();
});

async function renderChat(props: Partial<ChatContainerProps> = {}, online = true) {
  await act(async () => root.render(React.createElement(ChatConnectionContext.Provider, {
    value: { store: useConversationStore, api, remote: false, online },
  }, React.createElement(ChatContainer, {
    conversationId: 'c1', autoFetch: false, composerMode: 'study', ...props,
  }))));
}

function button(selector: string) {
  const element = host.querySelector<HTMLButtonElement>(selector);
  expect(element, selector).not.toBeNull();
  return element!;
}

async function click(selector: string) {
  await act(async () => button(selector).click());
}

async function enterDraft(text: string) {
  const textarea = host.querySelector('textarea')!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(textarea, text);
    textarea.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

it('shows send instead of stop when leaving a running conversation for a new chat', async () => {
  useConversationStore.setState({
    disconnect: initialState.disconnect,
    streamingMessageId: 'previous-account-reply',
    agentActivity: 'Agent 正在运行…',
  });
  await renderChat({ conversationId: undefined, createOnFirstSend: true });
  expect(host.querySelector('[aria-label="结束任务"]')).toBeNull();
  await enterDraft('新账号的消息');
  expect(button('[aria-label="发送消息"]').disabled).toBe(false);
});

it('does not show another conversation running state while switching views', async () => {
  useConversationStore.setState({ streamingMessageId: 'c1-reply', agentActivity: 'Agent 正在运行…' });
  await renderChat();
  expect(host.querySelector('[aria-label="结束任务"]')).not.toBeNull();
  await renderChat({ conversationId: 'c2' });
  expect(host.querySelector('[aria-label="结束任务"]')).toBeNull();
  expect(host.textContent).not.toContain('已有消息');
  await enterDraft('第二个会话的消息');
  expect(button('[aria-label="发送消息"]').disabled).toBe(false);
  expect(cancelTurn).not.toHaveBeenCalled();
  await renderChat({ conversationId: 'c1' });
  expect(host.querySelector('[aria-label="结束任务"]')).not.toBeNull();
});

it('does not show another conversation pending question as a running task', async () => {
  useConversationStore.setState({ pendingQuestion: {
    id: 'c1-question', kind: 'question', header: 'Question', question: 'Continue?', options: [],
  } });
  await renderChat({ conversationId: 'c2' });
  expect(host.querySelector('[aria-label="结束任务"]')).toBeNull();
  await enterDraft('第二个会话');
  expect(button('[aria-label="发送消息"]').disabled).toBe(false);
});

it('collapses mobile history and preserves a draft across repeated toggles', async () => {
  await renderChat();
  expect(host.querySelector('textarea')!.closest('[hidden]')).not.toBeNull();
  expect(button('.chat-composer-toggle').getAttribute('aria-expanded')).toBe('false');
  await click('.chat-composer-toggle');
  await enterDraft('保留这段草稿');
  await click('.chat-composer-toggle');
  await click('.chat-composer-toggle');
  expect(host.querySelector('textarea')!.value).toBe('保留这段草稿');
  expect(host.querySelector('textarea')!.closest('[hidden]')).toBeNull();
  expect(host.textContent).not.toContain('Enter 发送');
});

it('keeps the input open on desktop and for an empty mobile conversation', async () => {
  mobile = false;
  await renderChat();
  expect(host.querySelector('.chat-composer-toggle')).toBeNull();
  expect(host.querySelector('textarea')!.closest('[hidden]')).toBeNull();
  await act(async () => useConversationStore.setState({
    currentConversation: { id: 'c1', messages: [] } as unknown as ConversationDetail,
  }));
  // Remount so the responsive hook starts on a phone viewport.
  await act(async () => root.render(null));
  mobile = true;
  await renderChat();
  expect(host.querySelector('.chat-composer-toggle')).toBeNull();
  expect(host.querySelector('textarea')!.closest('[hidden]')).toBeNull();
});

it('opens an externally supplied draft even when mobile history is collapsed', async () => {
  await renderChat();
  await renderChat({ draftRequest: { id: 1, text: '新的提示词' } });
  expect(host.querySelector('textarea')!.value).toBe('新的提示词');
  expect(host.querySelector('textarea')!.closest('[hidden]')).toBeNull();
});

it('replaces send with stop while running and keeps stop available when collapsed', async () => {
  useConversationStore.setState({ streamingMessageId: 'reply' });
  await renderChat();
  expect(button('.chat-mobile-stop').disabled).toBe(false);
  await click('.chat-mobile-stop');
  expect(cancelTurn).toHaveBeenCalledWith('c1');
  await click('.chat-composer-toggle');
  expect(host.querySelector('textarea')!.disabled).toBe(true);
  expect(button('.chat-send-btn').disabled).toBe(false);
  expect(button('.chat-send-btn').getAttribute('aria-label')).toBe('结束任务');
  await click('.chat-send-btn');
  expect(cancelTurn).toHaveBeenCalledTimes(2);
  await renderChat({}, false);
  expect(button('.chat-send-btn').disabled).toBe(true);
  await act(async () => useConversationStore.setState({ streamingMessageId: null }));
  await renderChat();
  expect(button('.chat-send-btn').getAttribute('aria-label')).toBe('发送消息');
});

it('queues a stop during submission, prevents duplicate requests and allows retry on failure', async () => {
  mobile = false;
  let submitted!: () => void;
  const controller = Object.assign(new AbortController(), {
    submitted: new Promise<void>(resolve => { submitted = resolve; }),
  });
  useConversationStore.setState({ sendMessageStream: vi.fn(() => {
    useConversationStore.setState({ streamingMessageId: 'reply' });
    return controller;
  }) });
  await renderChat();
  await enterDraft('开始任务');
  await click('.chat-send-btn');
  await click('.chat-send-btn');
  expect(cancelTurn).not.toHaveBeenCalled();
  expect(button('.chat-send-btn').disabled).toBe(true);
  await click('.chat-send-btn');
  await act(async () => submitted());
  expect(cancelTurn).toHaveBeenCalledTimes(1);
  const errorToast = vi.spyOn(message, 'error').mockImplementation(() => (() => {}) as ReturnType<typeof message.error>);
  cancelTurn.mockRejectedValueOnce(new Error('offline'));
  await click('.chat-send-btn');
  expect(errorToast).toHaveBeenCalledWith('结束任务失败，请重试');
  expect(button('.chat-send-btn').disabled).toBe(false);
});

it('groups time and copy below the bubble and copies only the message content', async () => {
  const writeText = vi.fn(async () => {});
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
  vi.spyOn(message, 'success').mockImplementation(() => (() => {}) as ReturnType<typeof message.success>);
  await act(async () => root.render(React.createElement(MessageList, { messages: [historyMessage] })));
  const footer = host.querySelector('.message-actions')!;
  expect(footer.querySelector('time')!.dateTime).toBe(historyMessage.created_at);
  expect(footer.parentElement!.classList.contains('message-bubble-column')).toBe(true);
  expect(footer.previousElementSibling!.querySelector('.message-content')!.textContent).toBe('已有消息');
  expect(host.textContent).not.toContain('你');
  await click('.message-copy-button');
  expect(writeText).toHaveBeenCalledWith('已有消息');
});

it('loads workspace files and previews only on explicit sidebar clicks, without polling', async () => {
  vi.useFakeTimers();
  const workspaceEndpoint = '/conversations/c1/workspace-files/';
  const get = vi.mocked(api.get).mockImplementation(async (path, params) => {
    if (path !== workspaceEndpoint) return { skills: [], require_tool_approval: false };
    if (params?.path) return { path: 'notes.txt', name: 'notes.txt', size: 5, preview_kind: 'text', content: 'hello' };
    return {
      working_directory: 'E:/workspace', file_count: 1, truncated: false,
      entries: [{ path: 'notes.txt', name: 'notes.txt', size: 5, is_directory: false,
        depth: 0, preview_kind: 'text', modified_at: '2026-09-23T03:20:00Z' }],
    };
  });
  const openDirectory = vi.spyOn(api, 'post').mockResolvedValue({});
  const fileRequests = () => get.mock.calls.filter(([path]) => path === workspaceEndpoint);
  const clickInSidebar = async (label: string) => {
    const target = Array.from(document.querySelectorAll<HTMLButtonElement>('.chat-workspace-drawer button'))
      .find(element => element.textContent === label);
    expect(target, label).toBeTruthy();
    await act(async () => target!.click());
  };
  useConversationStore.setState({ streamingMessageId: 'reply' });
  await renderChat();
  expect(fileRequests()).toHaveLength(0);
  expect(host.querySelector('[aria-label="打开目录"]')).toBeNull();
  await click('[aria-label="打开右侧栏"]');
  expect(fileRequests()).toHaveLength(0);
  expect(openDirectory).not.toHaveBeenCalled();
  await clickInSidebar('打开目录');
  expect(openDirectory).toHaveBeenCalledWith('/conversations/c1/open-workspace/', {});
  await clickInSidebar('查看工作空间文件');
  expect(fileRequests()).toHaveLength(1);
  expect(document.querySelector('.workspace-file-preview')!.textContent).toContain('选择文件查看内容');
  await act(async () => { await vi.advanceTimersByTimeAsync(6000); });
  expect(fileRequests()).toHaveLength(1);
  await act(async () => document.querySelector<HTMLButtonElement>('.workspace-file-row')!.click());
  expect(fileRequests()).toHaveLength(2);
  expect(fileRequests()[1][1]).toEqual({ path: 'notes.txt' });
  expect(document.querySelector('.workspace-file-preview')!.textContent).toContain('hello');
  await act(async () => document.querySelector<HTMLButtonElement>('[aria-label="刷新文件"]')!.click());
  expect(fileRequests()).toHaveLength(3);
  await clickInSidebar('收起工作空间文件');
  await act(async () => { await vi.advanceTimersByTimeAsync(6000); });
  expect(fileRequests()).toHaveLength(3);
  await renderChat({ conversationId: 'c2' });
  expect(button('[aria-label="打开右侧栏"]').getAttribute('aria-expanded')).toBe('false');
  expect(get.mock.calls.some(([path]) => path === '/conversations/c2/workspace-files/')).toBe(false);
});
