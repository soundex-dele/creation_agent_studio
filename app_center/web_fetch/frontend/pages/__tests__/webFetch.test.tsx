// @vitest-environment jsdom
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '@platform/http';
import { WebFetchWorkspace } from '../WebFetchPage';
import { downloadArtifact, errorMessage, readDocument, safeLink, type FetchRun } from '../../services/webFetch';

const runtime = vi.hoisted(() => ({ subscribeRun: vi.fn(), sendCommand: vi.fn(), getArtifactAccess: vi.fn(), abort: vi.fn(),
  callbacks: undefined as undefined | { onEvent: (event: { type: string; payload: Record<string, unknown> }) => Promise<void> } }));
vi.mock('@/services/api', () => ({ api: { get: vi.fn(), post: vi.fn() } }));
vi.mock('@/services/applicationRuntime', () => ({ createApplicationRuntimeClient: () => runtime }));
const doc = { version: 1, title: '网页标题', author: '作者', siteName: '示例站点', publishedAt: null, url: 'https://example.com/article',
  markdown: '# 正文\n\n这是文章。\n\n[危险](javascript:alert(1))\n\n<script>alert(1)</script>', warnings: [], media: [] };
const artifact = (kind: string) => ({ id: kind, run_id: 'run-1', kind, content_hash: 'hash', mime_type: kind === 'web-document' ? 'application/json' : 'text/markdown', size: 100, metadata: {}, created_at: '' });
const run = (status = 'succeeded'): FetchRun => ({ id: 'run-1', organization_id: 'org', status, version: 1, next_event_sequence: 1,
  definition_snapshot: {}, input: { url: 'https://example.com/article' }, output_summary: { title: '网页标题' },
  artifacts: status === 'succeeded' ? [artifact('web-document'), artifact('web-markdown')] : [], created_at: '2026-10-16T08:00:00Z' });
let host: HTMLDivElement; let root: Root; let current: FetchRun; let records: FetchRun[];
const blob = () => ({ text: async () => JSON.stringify(doc) }) as Blob;
beforeEach(() => {
  vi.clearAllMocks(); current = run('queued'); records = []; runtime.callbacks = undefined;
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
  Object.defineProperty(window, 'matchMedia', { configurable: true, value: () => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() }) });
  Object.defineProperty(URL, 'createObjectURL', { configurable: true, writable: true, value: vi.fn(() => 'blob:download') });
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, writable: true, value: vi.fn() });
  runtime.subscribeRun.mockImplementation((_id, callbacks) => { runtime.callbacks = callbacks; return { abort: runtime.abort, done: Promise.resolve(), cursor: 0 }; });
  runtime.sendCommand.mockResolvedValue({});
  runtime.getArtifactAccess.mockResolvedValue({ url: 'https://api.example/content?token=signed', content_path: '/api/v1/organizations/org/runs/run-1/artifacts/web-document/content?token=signed' });
  vi.mocked(api.get).mockImplementation(async url => url.includes('/content?') ? blob() : url.endsWith('/runs') ? { count: records.length, results: records } : current);
  vi.mocked(api.post).mockResolvedValue(current);
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });
async function render(initialRunId?: string) {
  await act(async () => root.render(createElement(MemoryRouter, null, createElement(WebFetchWorkspace, { organizationId: 'org', applicationId: '12', initialRunId }))));
}
const button = (label: string) => Array.from(host.querySelectorAll('button')).find(element => element.textContent?.replace(/\s/g, '') === label)!;
async function click(label: string) { await act(async () => button(label).click()); }
async function typeUrl(value: string) {
  await act(async () => {
    const input = host.querySelector('#web-fetch-url')!;
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

describe('web fetch workflow', () => {
  it('explains authenticated blob download failures instead of displaying an empty error', () => {
    expect(errorMessage({ response: { data: new Blob(['denied']) } })).toContain('文件读取失败');
    expect(errorMessage({ response: { data: {} } })).toContain('操作失败');
  });
  it('validates, submits once, displays streamed progress and a safe article', async () => {
    await render(); await click('开始抓取'); expect(api.post).not.toHaveBeenCalled();
    await typeUrl('https://example.com/article'); await click('开始抓取');
    expect(api.post).toHaveBeenCalledWith(expect.stringContaining('/web-fetch/runs'), { url: current.input.url }, expect.objectContaining({ headers: { 'Idempotency-Key': expect.any(String) } }));
    expect(button('开始抓取').disabled).toBe(true);
    current = run('running');
    await act(async () => { await runtime.callbacks?.onEvent({ type: 'run.started', payload: {} }); await runtime.callbacks?.onEvent({ type: 'progress.updated', payload: { stage: 'extracting' } }); });
    expect(host.textContent).toContain('正在提取正文');
    current = run(); records = [current];
    await act(async () => { await runtime.callbacks?.onEvent({ type: 'run.succeeded', payload: {} }); });
    expect(host.textContent).toContain('这是文章');
    expect(host.querySelector('script')).toBeNull();
    expect(host.querySelector('a[href^="javascript:"]')).toBeNull();
    expect(api.get).toHaveBeenCalledWith(expect.stringContaining('/content?token=signed'), undefined, expect.objectContaining({ responseType: 'blob' }));
  });
  it.each(['missing', 'throws', 'absent'])('reuses failed request keys, resets after success and payload change with crypto %s', async mode => {
    vi.stubGlobal('crypto', mode === 'absent' ? undefined : { randomUUID: mode === 'missing' ? undefined : () => { throw new Error('HTTP insecure context'); } });
    await render(); await typeUrl('https://example.com/article');
    vi.mocked(api.post).mockRejectedValueOnce(new Error('网络中断'));
    await click('开始抓取'); expect(host.textContent).toContain('网络中断');
    await click('开始抓取');
    const calls = vi.mocked(api.post).mock.calls;
    expect(calls[0][2]).toEqual(calls[1][2]);
    current = run('failed'); records = [current];
    await act(async () => { await runtime.callbacks?.onEvent({ type: 'run.failed', payload: {} }); });
    vi.mocked(api.post).mockResolvedValue(current);
    await click('重新抓取');
    expect(calls[2][2]).not.toEqual(calls[1][2]);
    vi.mocked(api.post).mockRejectedValueOnce(new Error('网络中断'));
    await typeUrl('https://example.com/changed'); await click('开始抓取');
    expect(calls[3][2]).not.toEqual(calls[2][2]);
    await click('开始抓取'); expect(calls[4][2]).toEqual(calls[3][2]);
  });
  it('restores history without starting another extraction', async () => {
    current = run(); records = [current]; await render('run-1');
    expect(host.textContent).toContain('网页标题'); expect(host.textContent).toContain('这是文章');
    expect(api.post).not.toHaveBeenCalled();
    await act(async () => (host.querySelector('.web-fetch-history button') as HTMLButtonElement).click());
    expect(api.post).not.toHaveBeenCalled();
  });
  it('cancels the selected run and shows failure explanations', async () => {
    records = [current]; await render();
    current = { ...run('cancelled'), error_message: '抓取已取消' };
    await click('取消抓取');
    expect(runtime.sendCommand).toHaveBeenCalledWith('run-1', expect.objectContaining({ type: 'cancel' }));
    expect(host.textContent).toContain('抓取已取消');
    current = { ...run('failed'), error_message: '需要登录或验证' };
    await act(async () => (host.querySelector('.web-fetch-history button') as HTMLButtonElement).click());
    expect(host.textContent).toContain('需要登录或验证');
  });
  it('offers selected text when clipboard is unavailable or throws', async () => {
    current = run(); records = [current]; await render();
    const original = Object.getOwnPropertyDescriptor(navigator, 'clipboard');
    try {
      Object.defineProperty(navigator, 'clipboard', { configurable: true, value: undefined });
      await click('复制Markdown');
      expect((host.querySelector('#web-fetch-copy') as HTMLTextAreaElement).value).toBe(doc.markdown);
      Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: vi.fn().mockRejectedValue(new Error('denied')) } });
      await click('复制Markdown'); expect(host.textContent).toContain('请选择下方文字复制');
    } finally {
      if (original) Object.defineProperty(navigator, 'clipboard', original); else Reflect.deleteProperty(navigator, 'clipboard');
    }
  });
  it('downloads protected content through the authenticated API', async () => {
    current = run(); records = [current]; await render();
    const anchorClick = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    await click('下载JSON');
    expect(anchorClick).toHaveBeenCalled(); expect(URL.createObjectURL).toHaveBeenCalled();
    expect(api.get).toHaveBeenCalledWith(expect.stringContaining('/organizations/org/runs/run-1/artifacts/'), undefined, expect.objectContaining({ responseType: 'blob' }));
  });
  it('never forwards platform authentication to external storage URLs', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, blob: async () => blob() }));
    expect((await readDocument({ url: 'https://storage.example/file' })).title).toBe(doc.title);
    expect(api.get).not.toHaveBeenCalled();
    expect(fetch).toHaveBeenCalledWith('https://storage.example/file', { signal: undefined });
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    await downloadArtifact({ url: 'https://storage.example/file' }, 'article.md');
    for (const value of ['javascript:alert(1)', 'data:text/html,bad', 'file:///etc/passwd', 'https://user:pass@example.com']) expect(safeLink(value)).toBe('');
  });
});
