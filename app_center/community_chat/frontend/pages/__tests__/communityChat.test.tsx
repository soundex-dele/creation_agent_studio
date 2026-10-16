// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { ConfigProvider } from 'antd';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { api } from '@/services/api';
import type { ChatMessage } from '../../services/chat';
import CommunityChatPage from '../CommunityChatPage';

vi.mock('@/services/api', () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() } }));
vi.mock('../../services/chat', async importOriginal => ({ ...await importOriginal<object>(), connectChat: () => () => undefined }));
vi.mock('../RoomDialogs', () => ({ NewChatDialog: () => null, GroupDrawer: () => null }));
const user = { id: 1, username: 'alice', nickname: 'Alice', avatar: '' };
const room = { id: 'lobby', kind: 'lobby', name: '公共大厅', last_read_id: 0, unread: 0, preview: '', member_count: 0, version: 0 };
function sentMessage(id: number, text = '大家好'): ChatMessage {
  const payload = [...vi.mocked(api.post).mock.calls].reverse().find(call => call[0].endsWith('/messages/'))?.[1] as { request_key: string };
  return { id, room_id: room.id, author: user, text, withdrawn: false, revision: id, request_key: payload.request_key, created_at: new Date().toISOString(), attachments: [] };
}
let root: Root; let container: HTMLDivElement;
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: true, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} })));
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
  const computed = window.getComputedStyle.bind(window);
  vi.spyOn(window, 'getComputedStyle').mockImplementation(el => computed(el));
  vi.mocked(api.get).mockImplementation(async url => {
    if (url.endsWith('/users/')) return { me: user, users: [] };
    if (url.endsWith('/rooms/')) return [room];
    return { messages: [], revision: 0, has_more: false };
  });
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount()); container.remove();
  vi.restoreAllMocks(); vi.resetAllMocks(); vi.unstubAllGlobals();
});
async function mount() {
  await act(async () => root.render(<ConfigProvider theme={{ token: { motion: false } }}><MemoryRouter><CommunityChatPage /></MemoryRouter></ConfigProvider>));
  await act(async () => (container.querySelector('.community-room') as HTMLButtonElement).click());
}
async function type(text: string) {
  const input = container.querySelector('textarea')!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(input, text);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
  return input;
}

it.each([0, 3])('only shows the aggregate unread badge when count is positive (%i)', async unread => {
  vi.mocked(api.get).mockImplementation(async url => {
    if (url.endsWith('/users/')) return { me: user, users: [] };
    if (url.endsWith('/rooms/')) return [{ ...room, unread }];
    return { messages: [], revision: 0, has_more: false };
  });
  await mount();
  const badge = container.querySelector('.community-sidebar-heading .ant-badge-count');
  if (unread === 0) expect(badge).toBeNull();
  else expect(badge?.getAttribute('title')).toBe(String(unread));
});

it('keeps IME Enter from sending and retries the same payload after a network failure', async () => {
  vi.stubGlobal('crypto', undefined);
  await mount();
  const input = await type('大家好');
  await act(async () => input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', isComposing: true, bubbles: true })));
  expect(api.post).not.toHaveBeenCalled();
  vi.mocked(api.post).mockRejectedValueOnce(new Error('offline'));
  await act(async () => input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })));
  expect(container.textContent).toContain('发送失败');
  const payload = vi.mocked(api.post).mock.calls[0][1];
  expect(payload).toMatchObject({ text: '大家好', attachments: [] });
  const retry = [...container.querySelectorAll('button')].find(b => b.textContent?.includes('重试发送'))!;
  vi.mocked(api.post).mockImplementationOnce(async () => sentMessage(1));
  await act(async () => retry.click());
  expect(vi.mocked(api.post).mock.calls[1][1]).toEqual(payload);
});

it('selects files, displays upload failure and retries upload before publishing the message', async () => {
  await mount();
  const picker = container.querySelector('input[type="file"]')!;
  Object.defineProperty(picker, 'files', { configurable: true, value: [new File(['document'], 'notes.txt')] });
  await act(async () => picker.dispatchEvent(new Event('change', { bubbles: true })));
  expect(container.textContent).toContain('notes.txt');
  vi.mocked(api.post).mockRejectedValueOnce(new Error('upload failed'));
  const send = [...container.querySelectorAll('.community-composer button')].find(b => b.textContent?.replace(/\s/g, '') === '发送') as HTMLButtonElement;
  await act(async () => send.click());
  expect(vi.mocked(api.post).mock.calls[0][0]).toContain('/uploads/');
  expect(container.textContent).toContain('发送失败');
  vi.mocked(api.post).mockResolvedValueOnce({ id: 'attachment' }).mockImplementationOnce(async () => sentMessage(2, ''));
  await act(async () => ([...container.querySelectorAll('button')].find(b => b.textContent?.includes('重试发送')) as HTMLButtonElement).click());
  expect(vi.mocked(api.post).mock.calls[2][1]).toMatchObject({ attachments: ['attachment'] });
});

it.each(['你好', '第一行\n第二行\n第三行'])('keeps the same message bubble from sending through confirmation for %s', async text => {
  await mount();
  let complete!: (item: ChatMessage) => void;
  vi.mocked(api.post).mockImplementationOnce(() => new Promise(resolve => { complete = resolve; }));
  const input = await type(text);
  await act(async () => input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })));
  const row = container.querySelector('.community-message--mine')!;
  const bubble = row.querySelector('.community-bubble')!;
  expect(bubble.textContent).toBe(text);
  expect(row.textContent).toContain('发送中');
  expect(container.textContent).not.toContain('还没有消息');
  expect(container.querySelector('.community-pending')).toBeNull();
  const confirmed = sentMessage(10, text);
  // Deliberately leave the history endpoint empty: the POST response must suffice.
  await act(async () => complete(confirmed));
  expect(container.querySelector('.community-message--mine')).toBe(row);
  expect(row.querySelector('.community-bubble')).toBe(bubble);
  expect(bubble.textContent).toBe(text);
  expect(row.textContent).toContain('已发送');
  expect(container.querySelectorAll('.community-message')).toHaveLength(1);
  // The next history refresh must deduplicate without replacing the bubble.
  vi.mocked(api.get).mockImplementation(async url => {
    if (url.endsWith('/users/')) return { me: user, users: [] };
    if (url.endsWith('/rooms/')) return [room];
    return { messages: [confirmed], revision: 10, has_more: false };
  });
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 180)); });
  expect(container.querySelectorAll('.community-message')).toHaveLength(1);
  expect(container.querySelector('.community-bubble')).toBe(bubble);
});
