// @vitest-environment jsdom
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import WorkspaceFilesPanel from '../WorkspaceFilesPanel';
import type { WorkspaceFileEntry, WorkspaceFilePreview } from '@/types/workspaceFiles';

let root: Root;
let host: HTMLDivElement;
const file = (name: string, content = '', extra: Partial<WorkspaceFilePreview> = {}): WorkspaceFilePreview => ({
  name, path: name, content, size: content.length, mime_type: 'text/plain', preview_kind: 'text', truncated: false, ...extra,
});
const files = [file('README.MD', '# 标题\n\n| 项目 | 结果 |\n| --- | --- |\n| **测试** | 通过 |\n\n- [x] 完成\n\n```js\nconst a = 1;\n```'),
  file('page.html', '<html><head><style>h1{color:red}</style></head><body><h1>预览</h1><script>parent.alert(1)</script></body></html>'),
  file('data.json', '{"ok":true}'), file('photo.png', '', { preview_kind: 'image', data_url: 'data:image/png;base64,AA==' }),
  file('archive.zip', '', { preview_kind: 'binary' })];
const read = vi.fn<(path: string) => Promise<WorkspaceFilePreview>>();

beforeEach(() => {
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  window.matchMedia = vi.fn().mockReturnValue({ matches: false, addListener: vi.fn(), removeListener: vi.fn() });
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  read.mockReset().mockImplementation(async path => files.find(item => item.path === path)!);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); });

async function render(items = files) {
  await act(async () => root.render(<WorkspaceFilesPanel workingDirectory="/workspace" onRefresh={vi.fn()}
    entries={items.map(item => ({ ...item, is_directory: false, depth: 0, modified_at: '' } as WorkspaceFileEntry))}
    onReadFile={read} />));
}
async function select(name: string) {
  await act(async () => Array.from(host.querySelectorAll<HTMLButtonElement>('.workspace-file-row'))
    .find(button => button.textContent?.includes(name))!.click());
}
async function mode(value: string) {
  const label = Array.from(host.querySelectorAll<HTMLLabelElement>('.ant-segmented-item'))
    .find(item => item.textContent === (value === 'source' ? '源码' : '预览'))!;
  await act(async () => label.querySelector('input')!.click());
}

it('renders Markdown tables, code and tasks, switches to source, and resets mode for a different file', async () => {
  await render();
  expect(read).not.toHaveBeenCalled();
  await select('README.MD');
  expect(host.querySelector('h1')?.textContent).toBe('标题');
  expect(host.querySelector('table strong')?.textContent).toBe('测试');
  expect(host.querySelector('pre code')?.textContent).toContain('const a = 1;');
  expect(host.querySelector<HTMLInputElement>('input[type="checkbox"]')?.checked).toBe(true);
  await mode('source');
  expect(host.querySelector('table')).toBeNull();
  expect(host.querySelector('pre')?.textContent).toBe(files[0].content);
  await select('page.html');
  expect(host.querySelector('iframe')).not.toBeNull();
});

it('isolates HTML in a sandbox and preserves exact source', async () => {
  await render(); await select('page.html');
  const frame = host.querySelector('iframe')!;
  expect(frame.getAttribute('sandbox')).toBe('');
  expect(frame.getAttribute('referrerpolicy')).toBe('no-referrer');
  expect(frame.srcdoc).toContain('Content-Security-Policy');
  expect(frame.srcdoc).toContain('<base href="about:blank">');
  expect(frame.srcdoc).toContain("default-src 'none'");
  expect(frame.srcdoc).toContain(files[1].content);
  expect(host.querySelector('script')).toBeNull();
  await mode('source');
  expect(host.querySelector('iframe')).toBeNull();
  expect(host.querySelector('pre')?.textContent).toBe(files[1].content);
});

it('keeps text and image previews and unsupported-file feedback', async () => {
  await render(); await select('data.json');
  expect(host.querySelector('pre')?.textContent).toBe(files[2].content);
  expect(host.querySelector('.ant-segmented')).toBeNull();
  await select('photo.png');
  expect(host.querySelector('img')?.getAttribute('src')).toBe(files[3].data_url);
  await select('archive.zip');
  expect(host.textContent).toContain('该文件暂不支持在线预览');
});

it('does not let a slow previous file replace the current preview', async () => {
  let finish!: (result: WorkspaceFilePreview) => void;
  read.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  await render(); await select('README.MD');
  expect(host.querySelector('.ant-spin')).not.toBeNull();
  await select('data.json');
  await act(async () => finish(files[0]));
  expect(host.querySelector('pre')?.textContent).toBe(files[2].content);
});

it('offers retry after failure and shows truncation feedback', async () => {
  read.mockRejectedValueOnce(new Error('unavailable'));
  await render(); await select('README.MD');
  expect(host.querySelector('[role="alert"]')?.textContent).toContain('文件读取失败');
  read.mockResolvedValueOnce({ ...files[0], truncated: true });
  await act(async () => host.querySelector<HTMLButtonElement>('[role="alert"] button')!.click());
  expect(host.querySelector('h1')?.textContent).toBe('标题');
  expect(host.textContent).toContain('文件较大，仅展示部分内容');
  await render([]);
  expect(host.textContent).toContain('选择文件查看内容');
});

it('detects MIME types and does not render Markdown HTML or unsafe links', async () => {
  const markdown = file('document', '# MIME\n\n<script>alert(1)</script>\n\n[unsafe](javascript:alert)\n\n[local](/api/private)\n\n[site](https://example.com)', { mime_type: 'text/markdown; charset=utf-8' });
  read.mockResolvedValue(markdown);
  await render([markdown]); await select('document');
  expect(host.querySelector('h1')?.textContent).toBe('MIME');
  expect(host.querySelector('script')).toBeNull();
  expect(host.querySelectorAll('a')).toHaveLength(1);
  expect(host.querySelector('a')?.rel).toBe('noopener noreferrer');
});
