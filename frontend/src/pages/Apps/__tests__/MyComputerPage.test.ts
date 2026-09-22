// @vitest-environment jsdom
import React, { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { api } from '@/services/api';
import { useChatConnection } from '@/components/Chat/ChatConnectionContext';
import MyComputerPage from '../MyComputerPage';

vi.mock('@/components/Chat/ChatContainer', () => ({ default: function ChatStub() {
  const { online } = useChatConnection();
  const [draft, setDraft] = useState('');
  return React.createElement('div', {},
    React.createElement('input', { 'aria-label': 'draft', value: draft, onInput: (event: React.FormEvent<HTMLInputElement>) => setDraft(event.currentTarget.value) }),
    React.createElement('button', { disabled: !online, 'data-testid': 'send' }, '发送'));
} }));

let root: Root;
let container: HTMLDivElement;
let online: boolean;
beforeEach(() => {
  vi.useFakeTimers();
  online = true;
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  window.matchMedia = vi.fn().mockImplementation(query => ({ matches: false, media: query,
    addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn() }));
  vi.spyOn(api, 'get').mockImplementation(async (path) => {
    if (path === '/remote/devices/') return [{ id: 'computer', name: '书房电脑', online, confirmed: true }];
    if (path.endsWith('/conversations/')) return [{ id: 1, title: '本机对话', created_at: '', updated_at: '' }];
    if (path.endsWith('/apps/')) return [];
    return { organization_id: 'local-org' };
  });
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.restoreAllMocks(); vi.useRealTimers();
});

async function click(label: string) {
  const button = Array.from(container.querySelectorAll('button')).find(item => item.textContent?.replace(/\s/g, '').includes(label));
  expect(button, label).toBeTruthy();
  await act(async () => { button!.click(); });
}

it('keeps mobile navigation nested and retains the current draft while offline', async () => {
  await act(async () => root.render(React.createElement(MemoryRouter, { initialEntries: ['/apps/my-computer'] },
    React.createElement(Routes, {}, ...[
      '/apps/my-computer', '/apps/my-computer/:deviceId', '/apps/my-computer/:deviceId/conversations/:conversationId',
    ].map(path => React.createElement(Route, { key: path, path, element: React.createElement(MyComputerPage) }))))));
  await click('查看对话');
  expect(container.textContent).toContain('本机对话');
  await click('新建对话');
  const draft = container.querySelector<HTMLInputElement>('input[aria-label="draft"]')!;
  await act(async () => {
    draft.value = '保留的草稿';
    draft.dispatchEvent(new Event('input', { bubbles: true }));
  });
  online = false;
  await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
  expect(container.querySelector<HTMLInputElement>('input[aria-label="draft"]')?.value).toBe('保留的草稿');
  expect(container.querySelector<HTMLButtonElement>('[data-testid="send"]')?.disabled).toBe(true);
  await click('对话列表');
  expect(container.textContent).toContain('新建对话');
  await click('电脑列表');
  expect(container.textContent).toContain('绑定电脑');
});
