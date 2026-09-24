// @vitest-environment jsdom
import React, { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
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
vi.mock('../RemoteFilesPage', () => ({ default: ({ deviceId }: { deviceId: string }) => React.createElement('div', {}, `files:${deviceId}`) }));

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

function LocationProbe() {
  return React.createElement('output', { 'data-testid': 'location-search' }, useLocation().search);
}

it('opens the files deep link with application navigation parameters and without loading chat history', async () => {
  await act(async () => root.render(React.createElement(MemoryRouter, { initialEntries: ['/apps/my-computer/computer/files/?entry=apps&standalone=1'] },
    React.createElement(LocationProbe), React.createElement(Routes, {},
      React.createElement(Route, { path: '/apps/my-computer/:deviceId/files', element: React.createElement(MyComputerPage) })))));
  await act(async () => { await vi.advanceTimersByTimeAsync(0); });
  expect(container.textContent).toContain('files:computer');
  expect(container.querySelector('[data-testid="location-search"]')?.textContent).toBe('?entry=apps&standalone=1');
  expect(vi.mocked(api.get).mock.calls.some(call => call[0].endsWith('/conversations/'))).toBe(false);
});

it.each(['', '?entry=apps&standalone=1'])('keeps mobile navigation, launch presentation and offline drafts (%s)', async (search) => {
  const expectPresentation = () => expect(container.querySelector('[data-testid="location-search"]')?.textContent).toBe(search);
  await act(async () => root.render(React.createElement(MemoryRouter, { initialEntries: [`/apps/my-computer${search}`] },
    React.createElement(LocationProbe),
    React.createElement(Routes, {}, ...[
      '/apps/my-computer', '/apps/my-computer/:deviceId', '/apps/my-computer/:deviceId/conversations/:conversationId',
    ].map(path => React.createElement(Route, { key: path, path, element: React.createElement(MyComputerPage) }))))));
  await click('查看对话');
  expectPresentation();
  expect(container.textContent).toContain('本机对话');
  await click('新建对话');
  expectPresentation();
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
  expectPresentation();
  expect(container.textContent).toContain('新建对话');
  await click('电脑列表');
  expectPresentation();
  expect(container.textContent).toContain('绑定电脑');
});

it('shows every named computer and opens the selected computer', async () => {
  const get = vi.mocked(api.get);
  const original = get.getMockImplementation()!;
  get.mockImplementation(async (path, ...args) => path === '/remote/devices/' ? [
    { id: 'study', name: '书房电脑', online: true, confirmed: true },
    { id: 'office', name: '办公室电脑', online: true, confirmed: true },
    { id: 'laptop', name: '出差笔记本', online: false, confirmed: true },
    { id: 'pending', name: '待确认电脑', online: false, confirmed: false },
  ] : original(path, ...args));
  await act(async () => root.render(React.createElement(MemoryRouter, { initialEntries: ['/apps/my-computer'] },
    React.createElement(Routes, {}, ...['/apps/my-computer', '/apps/my-computer/:deviceId'].map(path =>
      React.createElement(Route, { key: path, path, element: React.createElement(MyComputerPage) }))))));

  expect(container.textContent).toContain('电脑列表（4）');
  const cards = Array.from(container.querySelectorAll('.my-computer-devices .ant-card'));
  expect(cards.map(card => card.querySelector('.ant-card-head-title')?.textContent?.trim()))
    .toEqual(['书房电脑', '办公室电脑', '出差笔记本', '待确认电脑']);
  expect(cards[2].textContent).toContain('离线');
  expect(cards[3].textContent).toContain('等待电脑确认');
  expect(cards.map(card => card.querySelector<HTMLButtonElement>('button')!.disabled))
    .toEqual([false, false, true, true]);
  await act(async () => { cards[1].querySelector<HTMLButtonElement>('button')!.click(); });
  expect(container.querySelector('.my-computer-toolbar strong')?.textContent).toContain('办公室电脑');
  expect(get.mock.calls.some(([path]) => path.includes('/remote/devices/office/') && path.endsWith('/conversations/'))).toBe(true);
});
