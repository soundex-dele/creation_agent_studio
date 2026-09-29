// @vitest-environment jsdom
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AnimationStudioWorkspace } from '../AnimationStudioPage';
import { api } from '@/services/api';
import { applicationPath } from '@/lib/applicationCatalog';
import { completedExport, type AnimationGeneration, type AnimationRun } from '@/services/animationStudio';

const runtime = vi.hoisted(() => ({
  subscribeRun: vi.fn(), getArtifactAccess: vi.fn(), sendCommand: vi.fn(), abort: vi.fn(),
  callbacks: undefined as undefined | { onEvent: (event: { type: string; payload: Record<string, unknown> }) => Promise<void> },
}));
vi.mock('@/services/api', () => ({ api: { get: vi.fn(), post: vi.fn() } }));
vi.mock('@/services/applicationRuntime', () => ({ createApplicationRuntimeClient: () => runtime }));
const preview = { id: 'preview', run_id: 'generation-1', kind: 'animation-preview', mime_type: 'text/html', content_hash: 'hash', size: 100, created_at: '', metadata: { width: 1920, height: 1080, durationInFrames: 900 } };
const source = { ...preview, id: 'source', kind: 'animation-source', mime_type: 'application/zip' };
const generation = (status = 'succeeded'): AnimationGeneration => ({
  id: 'generation-1', status, organization_id: 'org', version: 1, next_event_sequence: 1, definition_snapshot: {}, output_summary: { title: '测试动画' },
  input: { prompt: '番茄工作法', aspect: '16:9', duration: 30, style: '简洁', asset_ids: [] },
  artifacts: status === 'succeeded' ? [preview, source] : [], exports: [], created_at: '2026-09-29T06:00:00Z',
});
const exported = (status = 'queued'): AnimationRun => ({ ...generation(status), id: 'export-1', input: { ...generation().input, action: 'export', source_run_id: 'generation-1' }, artifacts: status === 'succeeded' ? [{ ...preview, id: 'video', run_id: 'export-1', kind: 'animation-video', mime_type: 'video/mp4' }] : [] });
let root: Root;
let host: HTMLDivElement;
let current: AnimationGeneration;
let records: AnimationGeneration[];
beforeEach(() => {
  vi.clearAllMocks(); current = generation(); records = [current]; runtime.callbacks = undefined;
  Object.defineProperty(globalThis, 'IS_REACT_ACT_ENVIRONMENT', { value: true, configurable: true });
  Object.defineProperty(window, 'matchMedia', { configurable: true, value: () => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() }) });
  Object.defineProperty(URL, 'createObjectURL', { configurable: true, writable: true, value: vi.fn(() => 'blob:video') });
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, writable: true, value: vi.fn() });
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, text: async () => '<!doctype html><h1>Animation</h1>', blob: async () => new Blob(['video']) }));
  runtime.subscribeRun.mockImplementation((_id, callbacks) => { runtime.callbacks = callbacks; return { abort: runtime.abort }; });
  runtime.getArtifactAccess.mockResolvedValue({ url: 'https://test.invalid/artifact' });
  vi.mocked(api.get).mockImplementation(async url => url.endsWith('/generations') ? { count: records.length, results: records } : current);
  runtime.sendCommand.mockResolvedValue({});
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
async function render(initialRunId?: string) { await act(async () => root.render(createElement(MemoryRouter, null, createElement(AnimationStudioWorkspace, { organizationId: 'org', applicationId: '12', initialRunId })))); }
function button(name: string) { return Array.from(host.querySelectorAll('button')).find(node => node.textContent?.replace(/\s/g, '') === name)!; }
async function click(name: string) { await act(async () => button(name).click()); }
async function write(text: string) {
  await act(async () => {
    const input = host.querySelector('textarea')!;
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(input, text);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
}
async function event(type = 'run.succeeded') { await act(async () => { await runtime.callbacks?.onEvent({ type, payload: {} }); }); }

describe('animation workflow', () => {
  it('opens a saved work link in preview with editing available above the canvas', async () => {
    current = { ...generation(), id: 'saved-version', input: { ...generation().input, aspect: '9:16', duration: 45, style: '手绘', source_run_id: 'previous-version' } };
    records = [generation()];
    await render(current.id);
    expect(api.get).toHaveBeenCalledWith(expect.stringContaining('/generations/saved-version'));
    expect(host.querySelector('.animation-workspace')?.getAttribute('data-tab')).toBe('preview');
    const editButton = button('继续修改');
    expect(editButton.disabled).toBe(false);
    expect(editButton.closest('.animation-preview-heading')).not.toBeNull();
    expect(editButton.compareDocumentPosition(host.querySelector('.animation-canvas')!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    await click('继续修改');
    expect(host.querySelector('.animation-workspace')?.getAttribute('data-tab')).toBe('create');
    expect((host.querySelector('#animation-duration') as HTMLInputElement).value).toBe('45');
    expect((host.querySelector('#animation-style') as HTMLInputElement).value).toBe('手绘');
    await write('标题换成蓝色');
    vi.mocked(api.post).mockResolvedValue({ ...generation('queued'), id: 'new-version' });
    await click('生成新版本');
    expect(api.post).toHaveBeenCalledWith(expect.stringContaining('/generations'), expect.objectContaining({ source_run_id: 'saved-version', prompt: '标题换成蓝色', aspect: '9:16', duration: 45, style: '手绘' }), expect.any(Object));
  });
  it('keeps the creation panel as the default when entering without a saved work link', async () => {
    await render();
    expect(host.querySelector('.animation-workspace')?.getAttribute('data-tab')).toBe('create');
  });
  it('registers the dedicated route and previews HTML in an opaque sandbox without auto-export', async () => {
    expect(applicationPath({ id: 'animation-studio', applicationId: 12, rendererKey: 'animation-studio', kind: 'custom' })).toBe('/applications/12/animation-studio?entry=apps');
    await render();
    expect(host.querySelector('iframe')?.getAttribute('sandbox')).toBe('allow-scripts');
    expect(host.querySelector('iframe')?.getAttribute('srcdoc')).toContain('Animation');
    expect(host.querySelector('video')).toBeNull();
    expect(api.post).not.toHaveBeenCalled();
  });
  it('keeps HTML during export then switches to the completed MP4', async () => {
    await render(); vi.mocked(api.post).mockResolvedValue(exported());
    await click('导出MP4');
    expect(api.post).toHaveBeenCalledWith(expect.stringContaining('/generations/generation-1/exports'), {}, expect.any(Object));
    expect(host.querySelector('iframe')).not.toBeNull();
    expect(host.querySelector('video')).toBeNull();
    current = { ...generation(), exports: [exported('succeeded')] }; await event();
    expect(host.querySelector('iframe')).toBeNull();
    expect(host.querySelector('video')?.getAttribute('src')).toBe('blob:video');
    expect(button('下载MP4')).toBeDefined();
  });
  it('retains the HTML and enables retry after an export fails', async () => {
    await render(); vi.mocked(api.post).mockResolvedValue(exported()); await click('导出MP4');
    current = { ...generation(), exports: [{ ...exported('failed'), error_message: '渲染失败' }] }; await event();
    expect(host.querySelector('iframe')).not.toBeNull();
    expect(host.textContent).toContain('渲染失败');
    expect(button('导出MP4').disabled).toBe(false);
    expect(completedExport(current)).toBeUndefined();
  });
  it('creates a new HTML version without replacing the original MP4', async () => {
    current = { ...generation(), exports: [exported('succeeded')] }; records = [current]; await render();
    await click('继续修改'); await write('标题换成蓝色');
    const next = { ...generation('queued'), id: 'generation-2', input: { ...current.input, prompt: '标题换成蓝色', source_run_id: current.id } };
    vi.mocked(api.post).mockResolvedValue(next); await click('生成新版本');
    expect(api.post).toHaveBeenCalledWith(expect.stringContaining('/generations'), expect.objectContaining({ source_run_id: 'generation-1', prompt: '标题换成蓝色' }), expect.any(Object));
    expect(host.querySelector('video')).toBeNull();
    current = { ...next, status: 'succeeded', artifacts: [{ ...preview, id: 'preview-2', run_id: next.id }, { ...source, id: 'source-2', run_id: next.id }] }; await event();
    expect(host.querySelector('iframe')).not.toBeNull();
    expect(records[0].exports[0].status).toBe('succeeded');
  });
  it('restores MP4 on refresh and cancellation preserves the HTML', async () => {
    current = { ...generation(), exports: [exported()] }; records = [current]; await render();
    current = { ...generation(), exports: [exported('cancelled')] }; await click('取消任务');
    expect(runtime.sendCommand).toHaveBeenCalledWith('export-1', expect.objectContaining({ type: 'cancel' }));
    expect(host.querySelector('iframe')).not.toBeNull();
    expect(host.textContent).toContain('HTML 预览与源码仍保留');
  });
  it('reuses idempotency key after an uncertain network failure', async () => {
    records = []; await render(); await write('动画');
    vi.mocked(api.post).mockRejectedValueOnce(new Error('网络中断')); await click('生成HTML预览');
    vi.mocked(api.post).mockResolvedValue(generation('queued')); await click('生成HTML预览');
    expect(vi.mocked(api.post).mock.calls[0][2]).toEqual(vi.mocked(api.post).mock.calls[1][2]);
  });
});
