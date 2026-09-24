// @vitest-environment jsdom
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { ConfigProvider } from 'antd';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '@/services/api';
import type { DriveEntry, DriveListing } from '@/services/myDrive';
import { MyDriveWorkspace } from '../MyDrivePage';

vi.mock('@/services/api', () => ({ api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() } }));
const base = '/organizations/org/applications/22/my-drive';
const folder: DriveEntry = { id: 'folder', parent: null, name: '我的素材', kind: 'folder', size: 0, media_type: '', trash_root: false, created_at: '', updated_at: '2026-09-24T00:00:00Z' };
const file: DriveEntry = { ...folder, id: 'file', name: '示例.html', kind: 'file', size: 16, media_type: 'text/html' };
const listing = (results: DriveEntry[] = []): DriveListing => ({ count: results.length, results, breadcrumbs: [], capacity: { used: 16, reserved: 0, limit: 100 * 1024 ** 3, max_file_size: 20 * 1024 ** 3 } });
let root: Root, container: HTMLDivElement;
const settle = async (delay = 30) => act(async () => { await new Promise((resolve) => setTimeout(resolve, delay)); });
const click = async (element: HTMLElement) => act(async () => element.click());
const button = (text: string, scope: ParentNode = document) => {
  const found = [...scope.querySelectorAll<HTMLButtonElement>('button')].find((element) => element.textContent?.replace(/\s/g, '') === text);
  expect(found, text).toBeDefined(); return found!;
};
const input = async (selector: string, value: string) => {
  const field = document.querySelector<HTMLInputElement>(selector)!;
  expect(field).not.toBeNull();
  await act(async () => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(field, value); field.dispatchEvent(new Event('input', { bubbles: true })); });
};
const tab = async (label: string) => {
  await click([...container.querySelectorAll<HTMLElement>('.ant-segmented-item-label')].find((element) => element.textContent === label)!);
  await settle();
};
const render = async () => {
  await act(async () => root.render(createElement(MemoryRouter, {}, createElement(ConfigProvider, { theme: { token: { motion: false } } }, createElement(MyDriveWorkspace, { base })))));
  await settle();
};
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() })));
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
  const computed = window.getComputedStyle.bind(window);
  vi.spyOn(window, 'getComputedStyle').mockImplementation((element) => computed(element));
  vi.mocked(api.get).mockImplementation(async (url) => url.endsWith('/uploads') ? { count: 0, results: [], next: null } : listing([folder, file]));
  vi.mocked(api.post).mockResolvedValue({ ok: true });
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); vi.restoreAllMocks(); vi.resetAllMocks(); vi.unstubAllGlobals(); });

describe('My Drive workspace', () => {
  it('navigates directories and searches the drive', async () => {
    await render();
    expect(container.textContent).toContain('100.0 GiB');
    await click(button('我的素材')); await settle();
    expect(api.get).toHaveBeenLastCalledWith(base, expect.objectContaining({ parent: 'folder', scope: 'files' }), expect.anything());
    await input('input[aria-label="搜索文件"]', '海边'); await settle(280);
    expect(api.get).toHaveBeenLastCalledWith(base, expect.objectContaining({ search: '海边', page: 1 }), expect.anything());
    await tab('回收站');
    expect(api.get).toHaveBeenLastCalledWith(base, expect.objectContaining({ scope: 'trash', search: '' }), expect.anything());
  });
  it('creates folders and keeps form content after failure', async () => {
    await render(); await click(button('新建文件夹'));
    await input('#drive-name', '旅行');
    vi.mocked(api.post).mockRejectedValueOnce(new Error('磁盘不可用'));
    await click(button('OK')); await settle();
    expect(document.querySelector('[role="dialog"]')?.textContent).toContain('磁盘不可用');
    expect(document.querySelector<HTMLInputElement>('#drive-name')?.value).toBe('旅行');
    await click(button('OK')); await settle();
    expect(api.post).toHaveBeenLastCalledWith(base, { name: '旅行', parent: null });
    expect(document.querySelector<HTMLElement>('[role="dialog"]')?.style.display).toBe('none');
  });
  it('requires confirmation for batch trash and restores selected items', async () => {
    await render();
    await click(container.querySelector<HTMLInputElement>('thead input[type="checkbox"]')!);
    await click(button('移入回收站'));
    expect(api.post).not.toHaveBeenCalled();
    await click(button('OK')); await settle();
    expect(api.post).toHaveBeenLastCalledWith(`${base}/actions`, { action: 'trash', ids: ['folder', 'file'] });
    vi.mocked(api.get).mockImplementation(async (url) => url.endsWith('/uploads') ? { results: [], next: null } : listing([{ ...file, trash_root: true }]));
    await tab('回收站');
    await click(button('恢复', container)); await settle();
    expect(api.post).toHaveBeenLastCalledWith(`${base}/actions`, { action: 'restore', ids: ['file'] });
  });
  it('moves a file using the destination picker', async () => {
    await render();
    const row = [...container.querySelectorAll('tbody tr')].find((element) => element.textContent?.includes(file.name))!;
    await click(button('移动', row)); await settle();
    await click(button('OK')); await settle();
    expect(api.post).toHaveBeenLastCalledWith(`${base}/actions`, { action: 'move', ids: ['file'], parent: null });
  });
  it('offers download for unsupported previews and handles listing errors', async () => {
    await render();
    vi.mocked(api.post).mockRejectedValueOnce({ response: { data: ['该格式不支持在线预览，请下载查看。'] } });
    await click(button(file.name)); await settle();
    expect(document.querySelector('[role="dialog"]')?.textContent).toContain('不支持在线预览');
    expect(button('下载文件')).toBeDefined();
    await click(document.querySelector<HTMLButtonElement>('.ant-modal-close')!);
    vi.mocked(api.get).mockRejectedValueOnce(new Error('网络中断'));
    await click(button('刷新')); await settle();
    expect(container.textContent).toContain('网络中断');
  });
  it('shows persisted transfers with original-file resume controls', async () => {
    vi.mocked(api.get).mockImplementation(async (url) => url.endsWith('/uploads') ? { count: 1, next: null, results: [{ id: 'upload', name: 'video.mp4', size: 1024, offset: 512, state: 'uploading' }] } : listing());
    await render(); await tab('传输列表');
    expect(container.textContent).toContain('video.mp4');
    expect(container.textContent).toContain('已暂停');
    expect(button('选择原文件续传')).toBeDefined();
  });
});
