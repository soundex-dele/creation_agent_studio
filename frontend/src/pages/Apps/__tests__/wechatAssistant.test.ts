// @vitest-environment jsdom
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { ConfigProvider } from 'antd';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { WechatAssistantApp, type Binding, type Requester } from '@wechat-assistant/main';
import { applicationPath } from '@/lib/applicationCatalog';

const base = '/applications/21/wechat-assistant/';
const binding: Binding = { id: 'b', status: 'connected', enabled: true, agent_id: 1, conversation_id: 12, busy: false, login_id: null, login_expires_at: null, qr_content: '', heartbeat_at: new Date().toISOString(), received_at: null, sent_at: null, last_error: '' };
let root: Root;
let element: HTMLDivElement;
const request = vi.fn();
const open = vi.fn();
const settle = () => act(async () => { await new Promise(resolve => setTimeout(resolve, 20)); });
const button = (label: string) => [...document.querySelectorAll<HTMLButtonElement>('button')].find(b => b.textContent?.replace(/\s/g, '') === label)!;
const render = async () => {
  await act(async () => root.render(createElement(ConfigProvider, { theme: { token: { motion: false } } }, createElement(WechatAssistantApp, { apiBasePath: base, requester: request as Requester, openConversation: open }))));
  await settle();
};

beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() })));
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
  const originalStyle = window.getComputedStyle.bind(window);
  vi.spyOn(window, 'getComputedStyle').mockImplementation(element => originalStyle(element));
  request.mockImplementation(async (url: string) => url.endsWith('agents') ? [{ id: 1, name: '我的智能体', kind: 'agent' }] : url.endsWith('tasks') ? [] : binding);
  element = document.createElement('div'); document.body.append(element); root = createRoot(element);
});
afterEach(async () => {
  await act(async () => root.unmount()); element.remove();
  vi.restoreAllMocks(); vi.resetAllMocks(); vi.unstubAllGlobals();
});

describe('微信助手', () => {
  it('shows refresh progress while retaining the current connection and tasks', async () => {
    await render();
    let resolveStatus!: (value: Binding) => void;
    request.mockImplementation(async (url: string) => url === base
      ? new Promise<Binding>(resolve => { resolveStatus = resolve; }) : []);
    await act(async () => button('刷新').click());
    expect(button('刷新').classList.contains('ant-btn-loading')).toBe(true);
    expect(element.textContent).toContain('已连接');
    await act(async () => resolveStatus(binding));
    await settle();
    expect(button('刷新').classList.contains('ant-btn-loading')).toBe(false);
  });

  it('opens a dedicated application and an existing conversation', async () => {
    expect(applicationPath({ id: 'wechat-assistant', applicationId: 21, kind: 'custom', rendererKey: 'wechat-assistant' })).toBe('/applications/21/wechat-assistant?entry=apps');
    await render();
    expect(element.textContent).toContain('已连接');
    await act(async () => button('打开当前会话').click());
    expect(open).toHaveBeenCalledWith(12);
  });
  it('disables changing conversations while a task needs input', async () => {
    request.mockImplementation(async (url: string) => url.endsWith('agents') ? [] : url.endsWith('tasks') ? [] : { ...binding, busy: true });
    await render();
    expect(button('新建会话').disabled).toBe(true);
    expect(button('保存智能体').disabled).toBe(true);
    expect(element.textContent).toContain('当前任务尚未结束');
  });
  it('starts QR login and displays its asynchronous state', async () => {
    request.mockImplementation(async (url: string) => url.endsWith('agents') ? [] : url.endsWith('tasks') ? [] : { ...binding, enabled: false, status: url.endsWith('login') ? 'qr_pending' : 'unbound' });
    await render();
    await act(async () => button('扫码绑定').click());
    expect(request).toHaveBeenCalledWith(base + 'login', { method: 'POST' });
    expect(element.textContent).toContain('正在获取二维码');
  });
  it('shows an actionable error and retries loading', async () => {
    request.mockRejectedValue(new Error('offline'));
    await render();
    expect(element.querySelector('[role="alert"]')?.textContent).toContain('无法读取');
    request.mockImplementation(async (url: string) => url.endsWith('agents') || url.endsWith('tasks') ? [] : binding);
    await act(async () => button('重试').click()); await settle();
    expect(element.textContent).toContain('已连接');
  });
});
