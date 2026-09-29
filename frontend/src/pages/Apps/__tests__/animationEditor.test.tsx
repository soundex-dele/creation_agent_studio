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
  await act(async () => {
    const select = Array.from(host.querySelectorAll('select')).find(s => Array.from(s.options).some(o => o.value === 'scenes'))!;
    select.value = name; select.dispatchEvent(new Event('change', { bubbles: true }));
  });
}

describe('scene editor entry and panels', () => {
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
