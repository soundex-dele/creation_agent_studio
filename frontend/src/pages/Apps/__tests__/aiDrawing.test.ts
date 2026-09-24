// @vitest-environment jsdom
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AIDrawingWorkspace } from '../AIDrawingPage';
import { api } from '@/services/api';
import { applicationPath } from '@/lib/applicationCatalog';
import { drawingStatus, downloadDrawing, type DrawingRun } from '@/services/aiDrawing';

const runtime = vi.hoisted(() => ({
  subscribeRun: vi.fn(), sendCommand: vi.fn(), getArtifactAccess: vi.fn(), abort: vi.fn(),
  callbacks: undefined as undefined | { onEvent: (event: { type: string; payload: Record<string, unknown> }) => Promise<void> },
}));
vi.mock('@/services/api', () => ({ api: { get: vi.fn(), post: vi.fn() } }));
vi.mock('@/services/applicationRuntime', () => ({ createApplicationRuntimeClient: () => runtime }));

const artifact = { id: 'picture-1', run_id: 'run-1', kind: 'drawing', content_hash: 'hash', mime_type: 'image/png', size: 100, metadata: { width: 1024, height: 1024 }, created_at: '' };
const run = (status = 'succeeded'): DrawingRun => ({ id: 'run-1', organization_id: 'org', status, version: 1, next_event_sequence: 1, definition_snapshot: {}, input: { prompt: '一只紫色小猫', orientation: 'square' }, output_summary: {}, artifacts: status === 'succeeded' ? [artifact] : [], created_at: '2026-09-24T08:00:00Z' });
let root: Root;
let host: HTMLDivElement;
let records: DrawingRun[];
let current: DrawingRun;

beforeEach(() => {
  vi.clearAllMocks();
  records = []; current = run('queued');
  runtime.callbacks = undefined;
  Object.defineProperty(globalThis, 'IS_REACT_ACT_ENVIRONMENT', { value: true, configurable: true });
  Object.defineProperty(window, 'matchMedia', { configurable: true, value: () => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() }) });
  Object.defineProperty(URL, 'createObjectURL', { configurable: true, writable: true, value: vi.fn(() => 'blob:preview') });
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, writable: true, value: vi.fn() });
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
  runtime.subscribeRun.mockImplementation((_id, callbacks) => { runtime.callbacks = callbacks; return { abort: runtime.abort, done: Promise.resolve(), cursor: 0 }; });
  runtime.getArtifactAccess.mockResolvedValue({ url: 'https://example.test/image.png' });
  runtime.sendCommand.mockResolvedValue({});
  vi.mocked(api.get).mockImplementation(async (url) => url.endsWith('/generations') ? { count: records.length, results: records } : current);
  vi.mocked(api.post).mockResolvedValue(current);
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });
async function render(initialRunId?: string) {
  await act(async () => root.render(createElement(MemoryRouter, null, createElement(AIDrawingWorkspace, { organizationId: 'org', applicationId: '12', initialRunId }))));
}
const button = (label: string) => Array.from(host.querySelectorAll('button')).find((element) => element.textContent?.replace(/\s/g, '') === label)!;
async function click(label: string) { await act(async () => button(label).click()); }
async function typePrompt(value: string) {
  await act(async () => {
    const textarea = host.querySelector('textarea')!;
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(textarea, value);
    textarea.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

describe('AI drawing workspace', () => {
  it('registers a dedicated application entry and meaningful status labels', () => {
    expect(applicationPath({ id: 'ai-drawing', applicationId: 12, rendererKey: 'ai-drawing', kind: 'custom' })).toBe('/applications/12/ai-drawing?entry=apps');
    expect(drawingStatus('running', 'saving')).toBe('正在保存图片');
    expect(drawingStatus('cancelled')).toBe('已取消');
  });
  it('validates input, submits a generation once and displays streamed completion', async () => {
    await render(); await click('生成图片');
    expect(api.post).not.toHaveBeenCalled();
    await typePrompt('一只猫'); await click('生成图片');
    expect(api.post).toHaveBeenCalledWith(expect.stringContaining('/generations'), { prompt: '一只猫', orientation: 'auto' }, expect.objectContaining({ headers: { 'Idempotency-Key': expect.any(String) } }));
    expect(button('生成图片').disabled).toBe(true);
    expect(runtime.subscribeRun).toHaveBeenCalledWith('run-1', expect.any(Object));
    current = run('running');
    await act(async () => { await runtime.callbacks?.onEvent({ type: 'run.started', payload: {} }); await runtime.callbacks?.onEvent({ type: 'progress.updated', payload: { stage: 'saving' } }); });
    expect(host.textContent).toContain('正在保存图片');
    current = run(); records = [current];
    await act(async () => { await runtime.callbacks?.onEvent({ type: 'run.succeeded', payload: {} }); });
    expect(host.querySelector('img[alt="当前生成作品"]')?.getAttribute('src')).toBe('https://example.test/image.png');
    expect(host.textContent).toContain('1024 × 1024');
    expect(runtime.abort).toHaveBeenCalled();
  });
  it('restores history, edits its archived image, and leaves the original intact', async () => {
    current = run(); records = [current];
    await render('run-1'); await click('继续修改');
    expect(host.textContent).toContain('历史作品 · 作为修改原图');
    await typePrompt('把背景换成蓝色');
    vi.mocked(api.post).mockResolvedValue({ ...run('queued'), id: 'run-2' });
    await click('生成图片');
    expect(api.post).toHaveBeenCalledWith(expect.any(String), { prompt: '把背景换成蓝色', orientation: 'auto', source_artifact_id: 'picture-1' }, expect.any(Object));
    expect(records[0].artifacts[0].id).toBe('picture-1');
  });
  it('supports cancellation and shows server failures', async () => {
    records = [current]; await render();
    current = { ...run('cancelled'), error_message: '账号暂时无法生成图片' };
    await click('取消生成');
    expect(runtime.sendCommand).toHaveBeenCalledWith('run-1', expect.objectContaining({ type: 'cancel' }));
    expect(host.textContent).toContain('账号暂时无法生成图片');
    expect(host.textContent).toContain('生成已取消');
  });
  it('retains the same idempotency key after a network failure', async () => {
    await render(); await typePrompt('小猫');
    vi.mocked(api.post).mockRejectedValueOnce(new Error('网络中断'));
    await click('生成图片');
    expect(host.textContent).toContain('网络中断');
    vi.mocked(api.post).mockResolvedValue(current);
    await click('生成图片');
    expect(vi.mocked(api.post).mock.calls[0][2]).toEqual(vi.mocked(api.post).mock.calls[1][2]);
  });
  it('uploads a reference before enabling generation', async () => {
    await render();
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:reference');
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
    vi.mocked(api.post).mockResolvedValueOnce({ id: 'reference-1', width: 24, height: 16, mime_type: 'image/png', size: 100 });
    await act(async () => {
      const input = host.querySelector('input[type="file"]')!;
      Object.defineProperty(input, 'files', { value: [new File(['image'], 'cat.png', { type: 'image/png' })] });
      input.dispatchEvent(new Event('change', { bubbles: true }));
    });
    expect(host.textContent).toContain('cat.png');
    await typePrompt('修改背景'); await click('生成图片');
    expect(api.post).toHaveBeenLastCalledWith(expect.stringContaining('/generations'), expect.objectContaining({ reference_id: 'reference-1' }), expect.any(Object));
  });
  it('downloads a new signed URL as an original image blob', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, blob: async () => new Blob(['image'], { type: 'image/png' }) }));
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:download');
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    await downloadDrawing('https://example.test/signed', 'drawing.png');
    expect(fetch).toHaveBeenCalledWith('https://example.test/signed');
    expect(click).toHaveBeenCalled();
  });
});
