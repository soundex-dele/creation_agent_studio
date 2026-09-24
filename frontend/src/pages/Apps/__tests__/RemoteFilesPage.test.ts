// @vitest-environment jsdom
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import RemoteFilesPage from '../RemoteFilesPage';
import * as files from '@/services/remoteFiles';

const tasks: never[] = [];
vi.mock('@/stores/remoteFileQueues', () => ({ remoteFileQueue: () => ({ subscribe: () => () => undefined, getSnapshot: () => tasks, clearFinished: vi.fn(), add: vi.fn(), discover: vi.fn() }) }));
let root: Root; let container: HTMLDivElement;
beforeEach(() => {
  vi.useFakeTimers();
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  window.matchMedia = vi.fn().mockImplementation(query => ({ matches: false, media: query,
    addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn() }));
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); vi.restoreAllMocks(); vi.useRealTimers(); });

it.each([null, { supported: true, enabled: false, max_file_size: 2147483648, chunk_size: 262144 }])('explains old computers and opt-in permission (%s)', async capability => {
  vi.spyOn(files, 'fileRequest').mockResolvedValue({ files: capability });
  await act(async () => root.render(React.createElement(RemoteFilesPage, { deviceId: 'a', online: true })));
  expect(container.textContent).toContain(capability ? '文件传输未开启' : '升级电脑端');
  expect(Array.from(container.querySelectorAll('button')).find(button => button.textContent?.includes('上传文件'))?.disabled).toBe(true);
});

it('loads directory pages, resolves locations and disables file actions offline', async () => {
  vi.spyOn(files, 'fileRequest').mockResolvedValue({ files: { supported: true, enabled: true } });
  vi.spyOn(files, 'fileGet').mockResolvedValue({ roots: [{ name: '/', path: '/' }], home: '/home' });
  const post = vi.spyOn(files, 'filePost').mockResolvedValueOnce({ path: '/real/home', parent: '/real', next_cursor: 'next',
    entries: [{ name: '中文.txt', path: '/real/home/中文.txt', directory: false, size: 0, modified_at: 0 }] })
    .mockResolvedValueOnce({ path: '/real/home', parent: '/real', next_cursor: '',
      entries: [{ name: 'next.txt', path: '/real/home/next.txt', directory: false, size: 1, modified_at: 0 }] });
  await act(async () => root.render(React.createElement(RemoteFilesPage, { deviceId: 'a', online: true })));
  expect(container.querySelector<HTMLInputElement>('input[aria-label="电脑目录路径"]')?.value).toBe('/real/home');
  await act(async () => Array.from(container.querySelectorAll('button')).find(button => button.textContent?.includes('加载更多文件'))!.click());
  expect(post).toHaveBeenLastCalledWith('a', 'list/', { path: '/real/home', cursor: 'next' });
  expect(container.textContent).toContain('中文.txt'); expect(container.textContent).toContain('next.txt');
  await act(async () => root.render(React.createElement(RemoteFilesPage, { deviceId: 'a', online: false })));
  expect(container.querySelector<HTMLButtonElement>('button[aria-label="下载 中文.txt"]')?.disabled).toBe(true);
  expect(container.textContent).toContain('已保存到本地请查看浏览器下载列表');
});
