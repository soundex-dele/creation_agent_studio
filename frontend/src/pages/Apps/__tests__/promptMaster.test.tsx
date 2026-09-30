// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '@/services/api';
import { applicationPath } from '@/lib/applicationCatalog';
import { blankInput, type PromptClient, type PromptSession, type PromptTask, type PromptVersion } from '@/services/promptMaster';
import { PromptWorkspace } from '../prompt/PromptWorkspace';
import { PromptMasterHome } from '../PromptMasterPage';
import { PromptLibrary } from '../prompt/PromptLibrary';

vi.mock('@/services/api', () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } }));
const version: PromptVersion = { id: 'v1', source: 'generate', standard: '标准提示词：预算2000元', concise: '预算2000元', assumptions: ['默认读者为新手'], health: [], changes: ['补齐预算'], constraints: [], health_stale: false, basis: {}, created_at: '2026-09-30T00:00:00Z' };
const initial: PromptSession = {
  ...blankInput(), id: 's1', title: '露营选购', topic: '露营装备，预算2000元', detected_scene: 'writing', favorite: false,
  revision: 1, results_stale: false, created_at: '', updated_at: '', rounds: 1, answers: {},
  questions: [{ id: 'audience', label: '主要读者是谁？', help: '选择或自由填写', type: 'single_choice', options: [{ value: 'new', label: '新手' }, { value: 'pro', label: '资深爱好者' }], recommended: '新手' }],
  analysis: { summary: '为露营新手选择装备' }, latest_version: null, latest_task: null,
};
const queued: PromptTask = { id: 't1', kind: 'generate', status: 'queued', error: '', revision: 1, result: {} };
let container: HTMLDivElement; let root: Root; let client: PromptClient;
const dirty = vi.fn();

beforeEach(() => {
  vi.useFakeTimers(); vi.clearAllMocks();
  Object.defineProperty(globalThis, 'IS_REACT_ACT_ENVIRONMENT', { configurable: true, value: true });
  Object.defineProperty(window, 'matchMedia', { writable: true, value: vi.fn().mockImplementation(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() })) });
  const computed = window.getComputedStyle.bind(window);
  vi.spyOn(window, 'getComputedStyle').mockImplementation((el) => computed(el));
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: vi.fn().mockResolvedValue(undefined) } });
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
  client = {
    catalog: vi.fn().mockResolvedValue({ templates: [] }), list: vi.fn().mockResolvedValue({ count: 0, results: [] }),
    create: vi.fn().mockResolvedValue(initial), get: vi.fn().mockResolvedValue(initial),
    update: vi.fn().mockImplementation(async (_id, revision, changes) => ({ ...initial, ...changes, revision: revision + 1 })),
    remove: vi.fn().mockResolvedValue(undefined), copy: vi.fn().mockResolvedValue({ ...initial, id: 'copy' }),
    versions: vi.fn().mockResolvedValue({ count: 0, results: [] }),
    saveVersion: vi.fn().mockResolvedValue({ ...initial, revision: 2, latest_version: { ...version, id: 'v2', health_stale: true } }),
    start: vi.fn().mockResolvedValue(queued), task: vi.fn().mockResolvedValue(queued), cancel: vi.fn().mockResolvedValue({ ...queued, status: 'cancelled' }),
  };
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); vi.useRealTimers(); vi.restoreAllMocks(); });
const button = (text: string) => [...container.querySelectorAll<HTMLButtonElement>('button')].find((b) => b.textContent?.trim() === text)!;
const render = async (session: PromptSession = initial) => {
  vi.mocked(client.get).mockResolvedValue(session);
  if (session.latest_version) vi.mocked(client.versions).mockResolvedValue({ count: 1, results: [session.latest_version] });
  await act(async () => root.render(<MemoryRouter><PromptWorkspace client={client} id="s1" onDirty={dirty} /></MemoryRouter>));
};
const changeText = async (label: string, value: string) => {
  const input = container.querySelector<HTMLTextAreaElement>(label)!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(input, value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
};

describe('prompt master workflow', () => {
  it('saves chosen recommendations before generation', async () => {
    await render();
    const checkbox = container.querySelector<HTMLInputElement>('input[type="checkbox"]')!;
    await act(async () => checkbox.click());
    expect(dirty).toHaveBeenLastCalledWith(true);
    await act(async () => button('生成标准版与精简版').click());
    expect(client.update).toHaveBeenCalledWith('s1', 1, { answers: { audience: null } });
    expect(client.start).toHaveBeenCalledWith('s1', 2, 'generate', expect.any(String), '', undefined);
    expect(container.textContent).toContain('正在生成标准版与精简版');
  });
  it('allows direct generation when the model needs no questions', async () => {
    await render({ ...initial, questions: [] });
    expect(container.textContent).toContain('信息已充分，可以生成');
    expect(button('检查是否需要补问')).toBeUndefined();
    await act(async () => button('生成标准版与精简版').click());
    expect(client.start).toHaveBeenCalledWith('s1', 1, 'generate', expect.any(String), '', undefined);
  });
  it('limits supplemental questions to two rounds', async () => {
    await render({ ...initial, rounds: 2 });
    expect(button('检查是否需要补问')).toBeUndefined();
    expect(container.textContent).toContain('2 / 2');
  });
  it('restores running tasks and retrieves the completed version', async () => {
    await render({ ...initial, latest_task: queued });
    expect(button('生成标准版与精简版').disabled).toBe(true);
    vi.mocked(client.task).mockResolvedValue({ ...queued, status: 'succeeded' });
    vi.mocked(client.get).mockResolvedValue({ ...initial, revision: 2, latest_task: { ...queued, status: 'succeeded' }, latest_version: version });
    vi.mocked(client.versions).mockResolvedValue({ count: 1, results: [version] });
    await act(async () => { await vi.advanceTimersByTimeAsync(1300); });
    expect(container.querySelector<HTMLTextAreaElement>('#pm-标准版')?.value).toBe(version.standard);
    expect(client.start).not.toHaveBeenCalled();
  });
  it('keeps edited text and marks checks stale, saves before checking', async () => {
    await render({ ...initial, latest_version: version });
    await changeText('#pm-标准版', '新的标准版');
    expect(container.textContent).toContain('体检待更新');
    expect(button('保存为新版本').disabled).toBe(false);
    await act(async () => button('保存并体检').click());
    expect(client.saveVersion).toHaveBeenCalledWith('s1', 1, 'v1', '新的标准版', version.concise);
    expect(client.start).toHaveBeenCalledWith('s1', 2, 'check', expect.any(String), '', 'v2');
  });
  it('preserves edits when saving hits a revision conflict', async () => {
    await render({ ...initial, latest_version: version });
    await changeText('#pm-标准版', '不能丢失的编辑');
    vi.mocked(client.saveVersion).mockRejectedValue({ response: { data: { detail: '版本冲突' } } });
    await act(async () => button('保存为新版本').click());
    expect(container.textContent).toContain('版本冲突');
    expect(container.querySelector<HTMLTextAreaElement>('#pm-标准版')?.value).toBe('不能丢失的编辑');
  });
  it('keeps result edits if saving answers succeeds but saving the version fails', async () => {
    await render({ ...initial, latest_version: version });
    await changeText('#pm-标准版', '保留这段编辑');
    await act(async () => container.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());
    vi.mocked(client.saveVersion).mockRejectedValue({ response: { data: { detail: '版本冲突' } } });
    await act(async () => button('保存并体检').click());
    expect(client.update).toHaveBeenCalled();
    expect(container.querySelector<HTMLTextAreaElement>('#pm-标准版')?.value).toBe('保留这段编辑');
    expect(client.start).not.toHaveBeenCalled();
  });
  it('copies the selected version and explains clipboard failure', async () => {
    await render({ ...initial, latest_version: version });
    await act(async () => button('复制精简版').click());
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(version.concise);
    vi.mocked(navigator.clipboard.writeText).mockRejectedValue(new Error('denied'));
    await act(async () => button('复制标准版').click());
    expect(container.textContent).toContain('手动复制');
  });
  it('preserves original prompts in optimization mode', async () => {
    await render({ ...initial, mode: 'optimize', original: '原文不能丢失' });
    expect(container.textContent).toContain('原文不能丢失');
    await act(async () => button('生成标准版与精简版').click());
    expect(client.start).toHaveBeenCalledWith('s1', 1, 'optimize', expect.any(String), '', undefined);
  });
  it('shows stale results and cancellation without replacing content', async () => {
    await render({ ...initial, results_stale: true, latest_version: version, latest_task: { ...queued, status: 'stale', error: '需求已更新' } });
    expect(container.textContent).toContain('下方历史结果已过期');
    expect(container.querySelector<HTMLTextAreaElement>('#pm-标准版')?.value).toBe(version.standard);
  });
  it('cancels an active task through the API', async () => {
    await render({ ...initial, latest_task: queued });
    vi.mocked(client.get).mockResolvedValue({ ...initial, latest_task: { ...queued, status: 'cancelled' } });
    await act(async () => button('取消任务').click());
    expect(client.cancel).toHaveBeenCalledWith('s1', 't1');
    expect(container.textContent).toContain('任务已取消');
  });
  it('loads and resumes private history and copies a new task', async () => {
    vi.mocked(client.list).mockResolvedValue({ count: 1, results: [initial] });
    const open = vi.fn();
    await act(async () => root.render(<PromptLibrary client={client} open={open} />));
    await act(async () => { await vi.advanceTimersByTimeAsync(220); });
    await act(async () => button('复制新任务').click());
    expect(client.copy).toHaveBeenCalledWith('s1');
    expect(open).toHaveBeenCalledWith('copy');
  });
});

describe('application integration', () => {
  it.each(['home', 'apps'] as const)('routes catalog launch from %s', (entry) => {
    expect(applicationPath({ id: 'prompt-master', applicationId: 42, rendererKey: 'prompt-master', kind: 'custom' }, entry)).toBe(`/applications/42/prompt-master?entry=${entry}`);
  });
  it.each(['entry=home', 'entry=apps', 'standalone=1', 'embedded=1'])('attaches the shared scroll root for %s', async (query) => {
    vi.mocked(api.get).mockResolvedValue({ templates: [] });
    await act(async () => root.render(<MemoryRouter initialEntries={[`/?${query}`]}><PromptMasterHome base="/prompt" /></MemoryRouter>));
    expect(container.querySelector('.prompt-master-page.app-scroll-page')).not.toBeNull();
    const back = container.querySelector('a[href="/apps"]');
    expect(!!back).toBe(query === 'entry=apps');
  });
  it('templates prefill editable needs instead of bypassing analysis', async () => {
    vi.mocked(api.get).mockResolvedValue({ templates: [{ id: 'image-1', scene: 'image', title: '产品展示图', topic: '设计产品展示图' }] });
    await act(async () => root.render(<MemoryRouter initialEntries={['/?tab=templates&embedded=1']}><PromptMasterHome base="/prompt" /></MemoryRouter>));
    await act(async () => container.querySelector<HTMLButtonElement>('.pm-template-card')!.click());
    expect(container.querySelector<HTMLTextAreaElement>('#pm-topic')?.value).toBe('设计产品展示图');
    expect(api.post).not.toHaveBeenCalled();
  });
});
