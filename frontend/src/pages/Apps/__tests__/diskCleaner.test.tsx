// @vitest-environment jsdom
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { ConfigProvider } from 'antd';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { api } from '@/services/api';
import { DiskCleanerWorkspace } from '../DiskCleanerPage';
import type { CleanerTask } from '@/services/diskCleaner';

vi.mock('@/services/api', () => ({ api: { get: vi.fn(), post: vi.fn() } }));
const base = '/applications/12/disk-cleaner';
const host = { name: '测试电脑', supported: true, worker_online: true, volumes: [{ path: 'C:\\', total: 1000, used: 700, free: 300 }], cache_roots: ['C:\\Temp'] };
const scan: CleanerTask = { id: 'scan-1', kind: 'scan', state: 'completed', parameters: { mode: 'large', root: 'C:\\Temp', minimum_bytes: 104857600 }, processed: 1, total_bytes: 500, skipped: 0, deleted_bytes: 0, free_before: {}, free_after: {}, message: '', created_at: '2026-10-10T00:00:00Z', finished_at: null, cancel_requested: false, summary: {} };
const file = { id: 'entry-1', path: 'C:\\Temp\\sample.bin', parent: 'C:\\Temp', kind: 'file', size: 500, modified_at: null, cleanable: true };
const preview = { id: 'preview-1', token: 'signed-token', count: 1, total_bytes: 500, root: 'C:\\Temp', host_name: host.name, expires_at: '2099-01-01T00:00:00Z' };
let root: Root, container: HTMLDivElement;
const settle = async () => act(async () => { await new Promise(resolve => setTimeout(resolve, 25)); });
const click = async (element: HTMLElement) => act(async () => { element.click(); });
const button = (name: string) => {
  const element = [...document.querySelectorAll<HTMLButtonElement>('button')].find(item => item.textContent?.replace(/\s/g, '') === name);
  expect(element, name).toBeDefined(); return element!;
};
async function render() {
  await act(async () => root.render(createElement(MemoryRouter, {}, createElement(ConfigProvider, { theme: { token: { motion: false } } }, createElement(DiskCleanerWorkspace, { base })))));
  await settle();
}
async function input(value: string) {
  const element = document.querySelector<HTMLInputElement>('#cleaner-root')!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(element, value);
    element.dispatchEvent(new Event('input', { bubbles: true }));
  });
}
function calls(path: string) { return vi.mocked(api.post).mock.calls.filter(([url]) => url === base + path).map(([, data]) => data as Record<string, unknown>); }

beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() })));
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
  const computed = window.getComputedStyle.bind(window);
  vi.spyOn(window, 'getComputedStyle').mockImplementation(element => computed(element));
  vi.mocked(api.get).mockImplementation(async url => {
    if (url.endsWith('/host')) return host;
    if (url.endsWith('/tasks')) return { count: 0, results: [] };
    if (url.endsWith('/entries') || url.includes('/previews/')) return { count: 1, results: [file] };
    return scan;
  });
  vi.mocked(api.post).mockImplementation(async url => url.endsWith('/previews') ? preview : url.endsWith('/cleanups') ? { ...scan, id: 'cleanup-1', kind: 'cleanup', deleted_bytes: 500, summary: { deleted: 1 } } : scan);
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount()); container.remove(); vi.restoreAllMocks(); vi.resetAllMocks(); vi.unstubAllGlobals();
});

it('does not scan on entry; requires selection, preview, and explicit permanent-delete confirmation', async () => {
  await render();
  expect(api.post).not.toHaveBeenCalled();
  await click(button('开始扫描')); await settle();
  expect(document.querySelector<HTMLInputElement>('input[type="checkbox"]')!.checked).toBe(false);
  expect(button('预览清理').disabled).toBe(true);
  await click(document.querySelector<HTMLInputElement>('input[type="checkbox"]')!);
  await click(button('预览清理')); await settle();
  expect(document.querySelector('[role="dialog"]')?.textContent).toContain('永久删除无法撤销');
  expect(document.querySelector('[role="dialog"]')?.textContent).toContain(file.path);
  expect(calls('/cleanups')).toHaveLength(0);
  await click(button('返回检查')); await settle();
  expect(calls('/cleanups')).toHaveLength(0);
  await click(button('预览清理')); await settle();
  await click(button('永久删除')); await settle();
  expect(calls('/cleanups')[0]).toEqual({ token: 'signed-token', request_key: expect.any(String) });
  expect(container.textContent).toContain('已删除文件大小');
});

it.each(['missing', 'throwing', 'absent'])('reaches API and preserves retry keys with crypto %s', async variant => {
  vi.stubGlobal('crypto', variant === 'absent' ? undefined : variant === 'missing' ? {} : { randomUUID: () => { throw new Error('insecure context'); } });
  await render();
  vi.mocked(api.post).mockRejectedValueOnce(new Error('网络中断'));
  await click(button('开始扫描')); await settle();
  expect(container.textContent).toContain('网络中断');
  await click(button('开始扫描')); await settle();
  const first = calls('/tasks');
  expect(first).toHaveLength(2);
  expect(first[0].request_key).toBe(first[1].request_key);
  await click(button('开始扫描')); await settle();
  expect(calls('/tasks')[2].request_key).not.toBe(first[0].request_key);
  await click(document.querySelector<HTMLInputElement>('input[type="checkbox"]')!);
  await click(button('预览清理')); await settle();
  vi.mocked(api.post).mockRejectedValueOnce(new Error('网络中断'));
  await click(button('永久删除')); await settle();
  expect(button('永久删除').disabled).toBe(false);
  await click(button('永久删除')); await settle();
  expect(calls('/cleanups')).toHaveLength(2);
  expect(calls('/cleanups')[0].request_key).toBe(calls('/cleanups')[1].request_key);
});

it('uses a new key when a failed scan payload changes', async () => {
  await render();
  vi.mocked(api.post).mockRejectedValueOnce(new Error('network'));
  await click(button('开始扫描')); await settle();
  await input('C:\\Other');
  await click(button('开始扫描')); await settle();
  expect(calls('/tasks')[0].request_key).not.toBe(calls('/tasks')[1].request_key);
});

it('restores latest task after reload and renders an authorization failure', async () => {
  vi.mocked(api.get).mockImplementation(async url => url.endsWith('/host') ? host : url.endsWith('/tasks') ? { count: 1, results: [scan] } : { count: 1, results: [file] });
  await render();
  expect(container.textContent).toContain(file.path);
  expect(api.post).not.toHaveBeenCalled();
  vi.mocked(api.get).mockRejectedValue(new Error('仅平台管理员可以使用磁盘清理大师。'));
  await click(button('刷新')); await settle();
  expect(container.textContent).toContain('仅平台管理员');
});

it('shows unsupported platform and no scan controls', async () => {
  vi.mocked(api.get).mockImplementation(async url => url.endsWith('/host') ? { ...host, supported: false } : { count: 0, results: [] });
  await render();
  expect(container.textContent).toContain('首版仅支持 Windows');
  expect(container.textContent).not.toContain('开始扫描');
});

it('polls a restored task, cancels it and aborts the polling request on leaving the task', async () => {
  const running = { ...scan, state: 'running' };
  vi.mocked(api.get).mockImplementation(async url => url.endsWith('/host') ? host : url.endsWith('/tasks') ? { count: 1, results: [running] } : url.endsWith('/entries') ? { count: 0, results: [] } : running);
  await render();
  expect(button('开始扫描').disabled).toBe(true);
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 2100)); });
  const poll = vi.mocked(api.get).mock.calls.find(([url]) => url === `${base}/tasks/${scan.id}`);
  expect(poll).toBeDefined();
  const signal = (poll![2] as { signal: AbortSignal }).signal;
  expect(signal.aborted).toBe(false);
  vi.mocked(api.post).mockResolvedValue({ ...scan, state: 'cancelled', cancel_requested: true });
  await click(button('停止任务')); await settle();
  expect(api.post).toHaveBeenCalledWith(`${base}/tasks/${scan.id}`, {});
  expect(container.textContent).toContain('已停止');
  expect(signal.aborted).toBe(true);
});
