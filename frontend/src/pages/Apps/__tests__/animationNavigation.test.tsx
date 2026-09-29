// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import AnimationStudioEditor from '../animation/AnimationStudioEditor';
import { api } from '@/services/api';
import { newDocument, newScene, type StudioProject } from '@/services/animationProjects';
import { resolveApplicationPresentation } from '@/lib/applicationPresentation';
import type { AnimationGeneration } from '@/services/animationStudio';

const runtime = vi.hoisted(() => ({ getArtifactAccess: vi.fn(), sendCommand: vi.fn() }));
vi.mock('@/services/api', () => ({ api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn() } }));
vi.mock('@/services/applicationRuntime', () => ({ createApplicationRuntimeClient: () => runtime }));
let host: HTMLDivElement; let root: Root; let project: StudioProject;
let mobile: boolean;
let mediaChange: ((event: { matches: boolean }) => void) | undefined;
const onSelect = vi.fn();
const generation = (): AnimationGeneration => ({
  id: 'generation-1', status: 'succeeded', organization_id: 'org', version: 1, next_event_sequence: 1,
  definition_snapshot: {}, output_summary: {}, created_at: '',
  input: { prompt: '内容', aspect: '16:9', duration: 10, style: '', asset_ids: [] },
  artifacts: [{ id: 'preview', run_id: 'generation-1', kind: 'animation-preview', mime_type: 'text/html', content_hash: '', size: 1, created_at: '', metadata: {} }], exports: [],
});
function addVersion() {
  const run = generation();
  project.versions = [{ id: 'version-1', document: project.draft, created_at: '', note: '', run }];
  return run;
}
beforeEach(() => {
  vi.resetAllMocks(); localStorage.clear(); mobile = false; mediaChange = undefined;
  Object.defineProperty(globalThis, 'IS_REACT_ACT_ENVIRONMENT', { value: true, configurable: true });
  Object.defineProperty(window, 'matchMedia', { configurable: true, value: (query: string) => ({
    matches: query === '(max-width: 767px)' && mobile, addListener: vi.fn(), removeListener: vi.fn(),
    addEventListener: (_event: string, listener: typeof mediaChange) => { if (query === '(max-width: 767px)') mediaChange = listener; }, removeEventListener: vi.fn(),
  }) });
  Object.defineProperty(URL, 'createObjectURL', { configurable: true, writable: true, value: vi.fn(() => 'blob:asset') });
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, writable: true, value: vi.fn() });
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {});
  // jsdom cannot measure pseudo-element scrollbars used by the Drawer portal.
  const computedStyle = window.getComputedStyle.bind(window);
  vi.spyOn(window, 'getComputedStyle').mockImplementation(element => computedStyle(element));
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, text: async () => '<h1>动画</h1>' }));
  runtime.getArtifactAccess.mockResolvedValue({ url: 'https://test.invalid/preview' });
  project = { id: 'project-1', title: '我的作品', archived: false, revision: 1, updated_at: '', draft: { ...newDocument(), scenes: [newScene()] }, versions: [], tasks: [] };
  vi.mocked(api.get).mockImplementation(async url => {
    if (url.includes('/projects/project-1')) return project;
    if (url.endsWith('/projects')) return { count: 1, results: [project] };
    if (url.endsWith('/presets')) return { results: [], fonts: ['Noto Sans SC'] };
    if (url.endsWith('/speech-config')) return { enabled: false, app_id: '', resource_id: '', secret_ref: '', voices: [{ id: 'one', name: '音色一' }, { id: 'two', name: '音色二' }] };
    if (url.includes('/generations/')) return { ...generation(), project_id: project.id };
    return { results: [] };
  });
  vi.mocked(api.put).mockImplementation(async (_url, data) => {
    const body = data as { document: StudioProject['draft'] };
    project = { ...project, draft: body.document, revision: project.revision + 1 };
    return project;
  });
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers(); });
async function render(initialRunId?: string, search = 'entry=apps') {
  await act(async () => root.render(<MemoryRouter initialEntries={[`/applications/33/animation-studio?${search}`]}><AnimationStudioEditor organizationId="org" applicationId="33" userId="user" initialRunId={initialRunId} showHeader={resolveApplicationPresentation(new URLSearchParams(search)).showApplicationHeader} onSelect={onSelect} /></MemoryRouter>));
}
function button(name: string) { return Array.from(document.querySelectorAll<HTMLButtonElement>('button')).find(b => b.textContent?.replace(/\s/g, '') === name && !b.closest('[hidden]'))!; }
async function panel(name: string) {
  await act(async () => document.querySelector<HTMLButtonElement>(`.studio-navigation button[data-page="${name}"]`)!.click());
}
async function click(name: string) { await act(async () => button(name).click()); }
function field(label: string, selector = 'input') {
  return Array.from(host.querySelectorAll('label')).find(node => node.textContent?.startsWith(label) && !node.closest('[hidden]'))!.querySelector<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>(selector)!;
}
async function write(element: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement, value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(Object.getPrototypeOf(element), 'value')!.set!.call(element, value);
    element.dispatchEvent(new Event(element.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true }));
  });
}
function currentPage() { return host.querySelector('.studio-workspace')?.getAttribute('data-page'); }
async function openMenu() {
  const trigger = host.querySelector<HTMLButtonElement>('[aria-label="打开动画制作菜单"]')!;
  await act(async () => { trigger.focus(); trigger.click(); });
  await act(async () => vi.advanceTimersByTimeAsync(500));
  expect(trigger.getAttribute('aria-expanded')).toBe('true');
  return trigger;
}

describe('unified animation navigation', () => {
  it('exposes nine destinations with one active menu item, title and content pane', async () => {
    await render(); expect(api.post).not.toHaveBeenCalled();
    expect(currentPage()).toBe('scenes');
    expect(host.querySelectorAll('.studio-navigation button')).toHaveLength(9);
    expect(host.textContent).not.toContain('工作面板');
    expect(host.querySelector('.animation-mobile-tabs')).toBeNull();
    for (const mode of ['history', 'audio', 'subtitles', 'assets', 'presets', 'batch', 'settings', 'preview', 'scenes']) {
      await panel(mode);
      expect(currentPage()).toBe(mode);
      const selected = host.querySelector('.studio-navigation [aria-current="page"]')!;
      expect(selected.getAttribute('data-page')).toBe(mode);
      expect(host.querySelector('.studio-page-title')?.textContent).toBe(selected.textContent);
      expect(host.querySelectorAll('.studio-content > section:not([hidden])')).toHaveLength(1);
    }
    expect(api.post).not.toHaveBeenCalled();
  });

  it('preserves draft and local template, batch, settings and audio fields across navigation', async () => {
    await render();
    await write(field('动画内容', 'textarea'), '尚未完成的分镜文案');
    await write(field('只修改这一幕', 'textarea'), '保留这个修改指令');
    await panel('presets'); await write(field('预设名称'), '测试模板');
    await panel('batch'); await click('添加一行');
    await panel('settings'); await write(field('密钥引用名称'), 'my-secret-ref');
    await panel('audio'); await write(field('音色', 'select'), 'two');
    await panel('history'); await write(field('搜索作品'), '作品过滤');
    await panel('preview'); await panel('history'); expect(field('搜索作品').value).toBe('作品过滤');
    await panel('audio'); expect(field('音色', 'select').value).toBe('two');
    await panel('settings'); expect(field('密钥引用名称').value).toBe('my-secret-ref');
    await panel('batch'); expect(host.querySelectorAll('[data-panel="batch"] tbody tr')).toHaveLength(2);
    await panel('presets'); expect(field('预设名称').value).toBe('测试模板');
    await panel('scenes');
    expect(field('动画内容', 'textarea').value).toBe('尚未完成的分镜文案');
    expect(field('只修改这一幕', 'textarea').value).toBe('保留这个修改指令');
    expect(host.querySelector('[data-panel="settings"]')?.hasAttribute('hidden')).toBe(true);
    await click('保存草稿'); expect(project.draft.prompt).toBe('尚未完成的分镜文案');
  });

  it('opens saved links in preview, removes playing frames when leaving and keeps export choices', async () => {
    addVersion(); await render('generation-1');
    expect(currentPage()).toBe('preview');
    expect(host.querySelector('iframe')).not.toBeNull();
    await write(field('格式', 'select'), 'gif');
    await click('继续修改');
    expect(currentPage()).toBe('scenes'); expect(host.querySelector('iframe')).toBeNull();
    await panel('preview'); expect(field('格式', 'select').value).toBe('gif');
    expect(host.querySelector('iframe')).not.toBeNull();
  });

  it('navigates after generation, choosing and creating a work', async () => {
    vi.mocked(api.post).mockImplementation(async url => url.endsWith('/tasks') ? addVersion() : project);
    await render(); await click('确认分镜并生成预览');
    expect(currentPage()).toBe('preview'); expect(onSelect).toHaveBeenCalledWith('generation-1');
    await panel('history'); await act(async () => host.querySelector<HTMLButtonElement>('.studio-project')!.click());
    expect(currentPage()).toBe('scenes');
    await panel('history'); await click('新的作品'); expect(currentPage()).toBe('scenes');
    expect(api.post).toHaveBeenCalledWith(expect.stringMatching(/\/projects$/), expect.anything());
  });

  it('synchronizes shortcut navigation and pauses retained asset audio on departure', async () => {
    project.draft.audio = [{ asset_id: 'audio-1', role: 'narration', start: 0, frames: 60, volume: 1 }];
    const originalGet = vi.mocked(api.get).getMockImplementation()!;
    vi.mocked(api.get).mockImplementation(async (url, ...args) => {
      if (url.endsWith('/assets/audio-1')) return new Blob(['audio'], { type: 'audio/mpeg' });
      if (url.endsWith('/assets')) return { results: args[0]?.archived === '1' ? [] : [{ id: 'audio-1', name: '录音', mime_type: 'audio/mpeg', duration: 2, size: 1, category: '', archived: false }] };
      return originalGet(url, ...args);
    });
    await render(); await panel('audio'); await click('在素材库试听');
    expect(currentPage()).toBe('assets');
    expect(host.querySelector('.studio-navigation [aria-current]')?.textContent).toBe('素材库');
    await click('预览'); const audio = host.querySelector('audio')!; expect(audio).not.toBeNull();
    await panel('scenes'); expect(audio.pause).toHaveBeenCalled();
    await panel('assets'); expect(host.querySelector('audio')).toBe(audio);
  });

  it('keeps conflicts and task failures visible on every page without losing the local draft', async () => {
    localStorage.setItem('animation-draft:org:33:user:project-1', JSON.stringify({ revision: 0, document: { ...project.draft, prompt: '恢复文案' } }));
    project.tasks = [{ ...generation(), status: 'failed', error_message: '生成任务失败' }];
    await render();
    for (const mode of ['history', 'preview', 'assets', 'scenes']) {
      await panel(mode);
      const notices = host.querySelector('.studio-notices')!;
      expect(notices.closest('[hidden]')).toBeNull();
      expect(notices.textContent).toContain('草稿保存冲突');
      expect(notices.textContent).toContain('生成任务失败');
    }
    expect(field('动画内容', 'textarea').value).toBe('恢复文案');
    await click('保存草稿'); expect(api.put).not.toHaveBeenCalled();
  });

  it('keeps navigation available during initial loading and after a load failure', async () => {
    const originalGet = vi.mocked(api.get).getMockImplementation()!;
    let fail!: (reason: Error) => void;
    vi.mocked(api.get).mockImplementation((url, ...args) => url.endsWith('/projects/project-1') ? new Promise((_resolve, reject) => { fail = reject; }) : originalGet(url, ...args));
    await render(); await panel('preview');
    expect(host.querySelector('[aria-label="正在加载作品"]')).not.toBeNull();
    await act(async () => fail(new Error('暂时无法加载作品')));
    expect(host.querySelector('.studio-notices')?.textContent).toContain('暂时无法加载作品');
    for (const mode of ['scenes', 'preview']) {
      await panel(mode);
      expect(host.querySelector('.studio-content > section:not([hidden])')?.textContent).toContain('作品加载失败');
    }
  });

  it('identifies a stored storyboard parsing failure as a previous task, not a page loading error', async () => {
    // The shared legacy input type only declares generate/export; studio tasks
    // returned by the server also carry storyboard/scene/speech actions.
    project.tasks = [{ ...generation(), input: { ...generation().input, action: 'storyboard' } as unknown as AnimationGeneration['input'], status: 'failed', error_message: 'Invalid control character at: line 1 column 433 (char 432)' }];
    await render();
    expect(host.querySelector('.studio-notices')?.textContent).toContain('上次生成分镜失败');
    expect(host.querySelector('.studio-notices')?.textContent).toContain('返回制作页面重新生成');
    expect(host.textContent).not.toContain('Invalid control character');
    expect(field('动画内容', 'textarea')).not.toBeNull();
  });
});

describe('mobile studio navigation', () => {
  beforeEach(() => { mobile = true; vi.useFakeTimers(); });
  it.each(['entry=home', 'entry=apps', 'standalone=1', 'embedded=1'])('keeps the drawer available for %s and restores focus after selection', async search => {
    await render(undefined, search);
    expect(host.querySelector('.studio-sidebar')).toBeNull();
    expect(Boolean(host.querySelector('[aria-label="返回应用"]'))).toBe(search === 'entry=apps');
    const trigger = await openMenu();
    expect(document.querySelectorAll('.studio-menu-drawer .studio-navigation button')).toHaveLength(9);
    await panel('subtitles'); await act(async () => vi.advanceTimersByTimeAsync(500));
    expect(currentPage()).toBe('subtitles');
    expect(trigger.getAttribute('aria-expanded')).toBe('false'); expect(document.activeElement).toBe(trigger);
  });
  it.each(['close', 'mask', 'escape'])('dismisses the drawer using %s', async method => {
    await render(); const trigger = await openMenu();
    await act(async () => {
      if (method === 'escape') document.querySelector('.ant-drawer-content-wrapper')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', keyCode: 27, bubbles: true }));
      else document.querySelector<HTMLElement>(method === 'close' ? '.ant-drawer-close' : '.ant-drawer-mask')!.click();
    });
    await act(async () => vi.advanceTimersByTimeAsync(500));
    expect(trigger.getAttribute('aria-expanded')).toBe('false'); expect(document.activeElement).toBe(trigger);
    expect(currentPage()).toBe('scenes');
  });
  it('closes the drawer at the desktop breakpoint without resetting selection or draft', async () => {
    await render(); await write(field('动画内容', 'textarea'), '断点切换文案');
    await openMenu(); await panel('assets'); await openMenu();
    await act(async () => { mobile = false; mediaChange?.({ matches: false }); });
    expect(host.querySelector('.studio-sidebar')).not.toBeNull();
    expect(document.querySelector('.studio-menu-drawer')).toBeNull();
    expect(currentPage()).toBe('assets');
    await panel('scenes'); expect(field('动画内容', 'textarea').value).toBe('断点切换文案');
  });
});
