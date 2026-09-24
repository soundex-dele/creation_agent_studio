// @vitest-environment jsdom
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import { api } from '@/services/api';
import RemoteTerminalPage from '../RemoteTerminalPage';
import { terminalStream } from '@/services/remoteTerminal';

const xterm = vi.hoisted(() => ({ write: vi.fn(), dispose: vi.fn(), onData: vi.fn() }));
vi.mock('@xterm/xterm', () => ({ Terminal: class {
  cols = 80; rows = 24;
  open() {} loadAddon() {} focus() {} reset() {}
  dispose = xterm.dispose;
  write(data: string, done: () => void) { xterm.write(data); done(); }
  onData(handler: (data: string) => void) { xterm.onData(handler); return { dispose: vi.fn() }; }
} }));
vi.mock('@xterm/addon-fit', () => ({ FitAddon: class { fit() {} } }));
vi.mock('@/services/remoteTerminal', async importOriginal => ({
  ...await importOriginal<typeof import('@/services/remoteTerminal')>(), terminalStream: vi.fn(),
}));

let root: Root;
let container: HTMLDivElement;
let capability: { enabled: boolean; supported: boolean } | undefined;
beforeEach(() => {
  vi.useFakeTimers(); vi.clearAllMocks();
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  window.matchMedia = vi.fn().mockImplementation(query => ({ matches: false, media: query,
    addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn() }));
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} });
  capability = { enabled: true, supported: true };
  vi.spyOn(api, 'get').mockImplementation(async path => path.endsWith('/context/') ? { terminal: capability } : { sessions: [] });
  vi.spyOn(api, 'post').mockImplementation(async path => path.endsWith('/terminals/')
    ? { id: 'session', shell: 'powershell', exited: false, created_at: '', exit_code: null } : {});
  vi.mocked(terminalStream).mockImplementation(async (_device, _session, _cursor, signal, onEvent) => {
    await onEvent({ type: 'ready' }); await onEvent({ type: 'output', sequence: 1, data: '中文输出' });
    await new Promise<void>(resolve => signal.addEventListener('abort', () => resolve(), { once: true }));
  });
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount()); container.remove();
  vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals();
});
async function render(path = '/terminals', online = true) {
  await act(async () => root.render(React.createElement(MemoryRouter, { initialEntries: [path] },
    React.createElement(Routes, {}, ...['/terminals', '/apps/my-computer/computer/terminals/:sessionId'].map(route =>
      React.createElement(Route, { key: route, path: route,
        element: React.createElement(RemoteTerminalPage, { deviceId: 'computer', online }) }))))));
}
function button(text: string) {
  return Array.from(container.querySelectorAll<HTMLButtonElement>('button')).find(item => item.textContent?.replace(/\s/g, '') === text)!;
}

it('explains local opt-in and refuses to create before permission is enabled', async () => {
  capability = { enabled: false, supported: true };
  await render();
  expect(container.textContent).toContain('允许远程终端');
  expect(button('新建终端').disabled).toBe(true);
  expect(api.post).not.toHaveBeenCalled();
});

it('supports legacy computers without terminal capability fields', async () => {
  capability = undefined; await render();
  expect(container.textContent).toContain('请升级电脑端');
  expect(button('新建终端').disabled).toBe(true);
});

it('creates on the selected computer and detaches without closing the process', async () => {
  await render();
  await act(async () => button('新建终端').click());
  await act(async () => { await vi.dynamicImportSettled(); });
  await act(async () => { await vi.advanceTimersByTimeAsync(200); });
  expect(api.post).toHaveBeenCalledWith('/remote/devices/computer/proxy/remote-access/terminals/',
    { cols: 80, rows: 24 }, expect.objectContaining({ headers: { 'Idempotency-Key': expect.any(String) } }));
  expect(xterm.write).toHaveBeenCalledWith('中文输出');
  expect(container.textContent).toContain('在线');
  await act(async () => { root.render(React.createElement('div', {}, '离开页面')); });
  expect(xterm.dispose).toHaveBeenCalled();
  expect(vi.mocked(api.post).mock.calls.some(([path]) => path.endsWith('/close/'))).toBe(false);
});

it('keeps a deep-linked session idle while the device is offline', async () => {
  await render('/apps/my-computer/computer/terminals/session', false);
  expect(button('新建终端').disabled).toBe(true);
  expect(terminalStream).not.toHaveBeenCalled();
  expect(api.post).not.toHaveBeenCalled();
});
