// @vitest-environment jsdom
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import * as markdownMath from '@/lib/markdownMath';
import MessageList, { type ChatMessage } from '../MessageList';
import { ChatConnectionContext } from '../ChatConnectionContext';
import { api } from '@/services/api';
import { useConversationStore } from '@/stores/useConversationStore';

let root: Root;
let host: HTMLDivElement;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  vi.stubGlobal('matchMedia', vi.fn((media: string) => ({
    matches: false, media, onchange: null,
    addListener: vi.fn(), removeListener: vi.fn(),
    addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn(),
  })));
  host = document.createElement('div');
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it('does not reparse historical Markdown while another message streams; formats the final reply once', async () => {
  const parse = vi.spyOn(markdownMath, 'normalizeMarkdownMath');
  const history: ChatMessage = { id: 'old', role: 'assistant', content: '# 旧回复\n\n$x^2$', created_at: '' };
  let live: ChatMessage = { id: 'live', role: 'assistant', content: '', created_at: '' };
  const render = async (streamingMessageId: string | null) => {
    await act(async () => root.render(<MessageList messages={[history, live]} streamingMessageId={streamingMessageId} />));
  };
  await render('live');
  expect(parse).toHaveBeenCalledTimes(1);
  for (let index = 0; index < 20; index++) {
    live = { ...live, content: `${live.content}**新内容**\n` };
    await render('live');
  }
  expect(parse).toHaveBeenCalledTimes(1);
  expect(host.querySelector('.message-streaming-content')?.textContent).toBe(live.content);
  await render(null);
  expect(parse).toHaveBeenCalledTimes(2);
  expect(host.querySelectorAll('strong')).toHaveLength(20);
  expect(host.querySelector('.message-streaming-content')).toBeNull();
  history.content = '更新的历史';
  await act(async () => root.render(<MessageList messages={[{ ...history }, live]} />));
  expect(parse).toHaveBeenCalledTimes(3);
  expect(host.textContent).toContain('更新的历史');
});

it('refreshes memoized messages when the connection or custom renderer changes', async () => {
  const message: ChatMessage = { id: 'old', role: 'assistant', content: '[链接](https://example.com)', created_at: '' };
  await act(async () => root.render(<MessageList messages={[message]} />));
  expect(host.querySelector('a')).not.toBeNull();
  const render = async (remote: boolean, custom?: () => React.ReactNode) => {
    await act(async () => root.render(<ChatConnectionContext.Provider value={{
      api, store: useConversationStore, remote, online: true,
    }}><MessageList messages={[message]} renderAssistantContent={custom} /></ChatConnectionContext.Provider>));
  };
  await render(false);
  await render(true);
  expect(host.querySelector('a')).toBeNull();
  expect(host.textContent).toContain('远程访问暂不支持打开文件或链接');
  await render(true, () => <p>自定义回复</p>);
  expect(host.textContent).toContain('自定义回复');
});
