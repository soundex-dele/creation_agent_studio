// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import AnimationStudioEditor from '../animation/AnimationStudioEditor';
import { api } from '@/services/api';
import { newDocument, newScene, type StudioProject } from '@/services/animationProjects';

vi.mock('@/services/api', () => ({ api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn() } }));
vi.mock('@/services/applicationRuntime', () => ({ createApplicationRuntimeClient: () => ({ getArtifactAccess: vi.fn(), sendCommand: vi.fn() }) }));
let host: HTMLDivElement; let root: Root; let project: StudioProject;
beforeEach(() => {
  vi.clearAllMocks(); localStorage.clear();
  Object.defineProperty(globalThis, 'IS_REACT_ACT_ENVIRONMENT', { value: true, configurable: true });
  Object.defineProperty(window, 'matchMedia', { configurable: true, value: () => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() }) });
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
  project = { id: 'project-1', title: '我的作品', archived: false, revision: 1, updated_at: '', draft: { ...newDocument(), scenes: [newScene()] }, versions: [], tasks: [] };
  vi.mocked(api.get).mockImplementation(async url => {
    if (url.includes('/projects/project-1')) return project;
    if (url.endsWith('/projects')) return { count: 1, results: [project] };
    if (url.endsWith('/presets')) return { results: [], fonts: ['Noto Sans SC'] };
    if (url.endsWith('/speech-config')) return { enabled: false, voices: [] };
    return { results: [] };
  });
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.unstubAllGlobals(); });
async function render() { await act(async () => root.render(<MemoryRouter><AnimationStudioEditor organizationId="org" applicationId="33" userId="user" showHeader onSelect={() => {}} /></MemoryRouter>)); }
function button(name: string) { return Array.from(host.querySelectorAll('button')).find(b => b.textContent?.replace(/\s/g, '') === name)!; }
async function panel(name: string) {
  await act(async () => host.querySelector<HTMLButtonElement>(`.studio-navigation button[data-page="${name}"]`)!.click());
}

describe('scene editor entry and panels', () => {
  it('opens the requested imported project instead of the first project in history', async () => {
    const imported = { ...project, id: 'imported', title: '导入的抖音脚本', draft: { ...newDocument(), scenes: [{ ...newScene(), narration: '导入的旁白' }] } };
    const original = vi.mocked(api.get).getMockImplementation()!;
    vi.mocked(api.get).mockImplementation((url, ...args) => url.endsWith('/projects/imported') ? Promise.resolve(imported) : original(url, ...args));
    await act(async () => root.render(<MemoryRouter><AnimationStudioEditor organizationId="org" applicationId="33" userId="user" initialProjectId="imported" showHeader onSelect={() => {}} /></MemoryRouter>));
    expect(api.get).toHaveBeenCalledWith(expect.stringContaining('/projects/imported'));
    expect(api.get).not.toHaveBeenCalledWith(expect.stringContaining('/projects/project-1'));
    expect(api.post).not.toHaveBeenCalled();
    expect([...host.querySelectorAll('textarea')].some(input => input.value === '导入的旁白')).toBe(true);
  });

  it('reports an unavailable project without creating a replacement', async () => {
    const original = vi.mocked(api.get).getMockImplementation()!;
    vi.mocked(api.get).mockImplementation((url, ...args) => url.endsWith('/projects/missing') ? Promise.reject(new Error('作品不可访问')) : original(url, ...args));
    await act(async () => root.render(<MemoryRouter><AnimationStudioEditor organizationId="org" applicationId="33" userId="user" initialProjectId="missing" showHeader onSelect={() => {}} /></MemoryRouter>));
    expect(host.textContent).toContain('作品不可访问');
    expect(api.post).not.toHaveBeenCalled();
  });

  it('loads existing projects without creating duplicates and exposes every workspace panel', async () => {
    await render(); expect(api.post).not.toHaveBeenCalled();
    expect(host.querySelector('.studio-editor-pane')).not.toBeNull();
    for (const mode of ['audio', 'subtitles', 'assets', 'presets', 'batch', 'settings', 'scenes']) await panel(mode);
    expect(button('确认分镜并生成预览')).toBeDefined();
  });
  it('locks scene form fields and AI modification while leaving an unlock action available', async () => {
    project.draft.scenes[0].locked = true;
    await render();
    expect(host.querySelector('fieldset')?.disabled).toBe(true);
    expect(button('AI修改当前场景').disabled).toBe(true);
    expect(button('解锁场景').disabled).toBe(false);
  });
  it('presents conversion and legacy editing for old work instead of assuming scene data exists', async () => {
    project.draft = { schema_version: 1 } as StudioProject['draft'];
    await render();
    expect(host.textContent).toContain('历史动画');
    expect(button('原版继续修改')).toBeDefined();
    await panel('batch'); expect(host.textContent).toContain('批量制作');
  });
});
