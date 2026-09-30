// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ImportAnimationModal } from '../douyin/ImportAnimationModal';
import { api } from '@/services/api';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import { douyinApi, type Script } from '@/services/douyinBenchmark';

vi.mock('@/services/api', () => ({ api: { get: vi.fn(), post: vi.fn() } }));
const script: Script = { title: '我的视频', cover: '封面短句', narration: '完整口播', checklist: ['准备道具'], scenes: [{ time: '0–10秒', visual: '书本翻页', spoken: '镜头口播' }] };
const client = douyinApi('/organizations/org/applications/22/douyin-benchmark');
let host: HTMLDivElement; let root: Root;
function Location() { const location = useLocation(); return <output>{location.pathname}{location.search}</output>; }
beforeEach(() => {
  vi.clearAllMocks();
  useOrganizationStore.setState({ currentOrganizationId: 'org' });
  Object.defineProperty(globalThis, 'IS_REACT_ACT_ENVIRONMENT', { configurable: true, value: true });
  Object.defineProperty(window, 'matchMedia', { configurable: true, value: () => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() }) });
  const computed = window.getComputedStyle;
  vi.spyOn(window, 'getComputedStyle').mockImplementation(element => computed(element));
  vi.mocked(api.get).mockResolvedValue([{ id: 33, name: '动画制作' }]);
  vi.mocked(api.post).mockResolvedValue({ id: 'imported-project' });
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); useOrganizationStore.setState({ currentOrganizationId: null }); vi.restoreAllMocks(); });
async function render() {
  await act(async () => root.render(<MemoryRouter initialEntries={['/source?entry=home&embedded=1']}><ImportAnimationModal client={client} script={script} onClose={() => {}} /><Location /></MemoryRouter>));
}
function submit() { return [...document.querySelectorAll('button')].find(button => button.textContent === '创建动画作品并打开')!; }

describe('import saved scripts into animation', () => {
  it('creates a separate tenant-scoped project and preserves the launch presentation', async () => {
    await render();
    expect(api.get).toHaveBeenCalledWith('/organizations/org/applications/22/douyin-benchmark/animation-integrations');
    await act(async () => submit().click());
    expect(api.post).toHaveBeenCalledWith('/organizations/org/applications/33/animation-studio/projects', expect.objectContaining({
      title: script.title, draft: expect.objectContaining({ aspect: '9:16', scenes: [expect.objectContaining({ title: '', narration: '镜头口播', frames: 300 })] }),
    }));
    expect(host.querySelector('output')?.textContent).toBe('/applications/33/animation-studio?project=imported-project&entry=home&embedded=1');
  });

  it('does not allow import when the animation application is unavailable', async () => {
    vi.mocked(api.get).mockResolvedValue([]);
    await render();
    expect(submit().disabled).toBe(true);
    expect(document.body.textContent).toContain('当前没有可用的动画制作应用');
    expect(api.post).not.toHaveBeenCalled();
  });

  it('keeps errors visible and permits retry without navigating away', async () => {
    vi.mocked(api.post).mockRejectedValueOnce(new Error('创建失败'));
    await render(); await act(async () => submit().click());
    expect(document.body.textContent).toContain('创建失败');
    expect(host.querySelector('output')?.textContent).toContain('/source');
    await act(async () => submit().click());
    expect(api.post).toHaveBeenCalledTimes(2);
    expect(host.querySelector('output')?.textContent).toContain('project=imported-project');
  });

  it('submits once while creation is pending and does not navigate after a tenant switch', async () => {
    let resolve!: (value: unknown) => void;
    vi.mocked(api.post).mockImplementation(() => new Promise(done => { resolve = done; }));
    await render();
    await act(async () => { submit().click(); submit().click(); });
    expect(api.post).toHaveBeenCalledTimes(1);
    await act(async () => { useOrganizationStore.setState({ currentOrganizationId: 'other-org' }); resolve({ id: 'imported-project' }); });
    expect(host.querySelector('output')?.textContent).toContain('/source');
  });
});
