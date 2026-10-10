// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import { api } from '@/services/api';
import type { ResearchTask, RadarSource } from '@/services/douyinResearch';
import { TopicRadar } from '../douyin/TopicRadar';
import { DouyinHome } from '../DouyinBenchmarkPage';

vi.mock('@/services/api', () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } }));
const source: RadarSource = { id: 'hot:1', kind: 'hot', title: '科学问题', rank: 3, heat: 0, url: 'https://www.douyin.com/search/test', captured_at: '2026-10-10T00:00:00Z' };
const hot: ResearchTask = { id: 'scan1', kind: 'radar_hotlist', status: 'succeeded', stage: 'completed', error: '', progress: {}, sources: [], output: { radar_items: [source], radar_request: { kind: 'radar_hotlist' } }, work_id: null, run_id: 'run1', created_at: source.captured_at };
let container: HTMLDivElement; let root: Root;
let tasks: ResearchTask[];
beforeEach(() => {
  vi.clearAllMocks(); tasks = [hot];
  const original = window.getComputedStyle; vi.spyOn(window, 'getComputedStyle').mockImplementation(el => original(el));
  Object.defineProperty(window, 'matchMedia', { writable: true, value: vi.fn(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() })) });
  Object.defineProperty(globalThis, 'IS_REACT_ACT_ENVIRONMENT', { configurable: true, value: true });
  vi.mocked(api.get).mockImplementation(async url => {
    if (url.endsWith('/accounts')) return { count: 1, results: [{ id: 'a1', name: '我的科普号', is_owned: true }] };
    if (url.endsWith('/tasks')) return { count: tasks.length, results: tasks };
    const task = tasks.find(t => url.endsWith(`/tasks/${t.id}`));
    if (task) return task;
    if (url.endsWith('/connection')) return { connected: true };
    return { count: 0, results: [] };
  });
  vi.mocked(api.post).mockResolvedValue(hot);
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
async function render(node = <TopicRadar base="/dy" />, entry = '/?view=radar') {
  await act(async () => root.render(<MemoryRouter initialEntries={[entry]}>{node}</MemoryRouter>));
}
async function click(label: string) {
  const button = [...container.querySelectorAll<HTMLElement>('button,[role="tab"],a')].find(el => el.textContent === label);
  expect(button, label).toBeDefined(); await act(async () => button!.click());
}
async function checkSource() { await act(async () => container.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click()); }
function Location() { const location = useLocation(); return <output>{location.search}</output>; }

describe('All-site topic radar', () => {
  it.each(['entry=home', 'entry=apps', 'standalone=1', 'embedded=1'])('opens the independent page preserving %s', async query => {
    await render(<><DouyinHome base="/dy" /><Location /></>, `/?${query}&view=radar`);
    expect(container.querySelector('h1')?.textContent).toBe('发现与研究');
    expect(container.querySelector('main')?.className).toContain('app-scroll-page');
    expect(container.querySelector('output')?.textContent).toContain(query);
    expect(container.querySelector('output')?.textContent).toContain('task=scan1');
    expect(api.post).not.toHaveBeenCalled();
  });
  it('restores bounded history, searches a hotword only on submission', async () => {
    await render();
    expect(api.get).toHaveBeenCalledWith('/dy/tasks', expect.objectContaining({ kind: 'radar_hotlist,radar_search,radar_topics' }));
    expect(container.textContent).toContain('榜单排名 3 · 热度 0');
    await click('搜索相关作品');
    expect(container.querySelector<HTMLInputElement>('[aria-label="行业或关键词"]')?.value).toBe('科学问题');
    expect(api.post).not.toHaveBeenCalled();
    await click('搜索作品');
    expect(api.post).toHaveBeenCalledWith('/dy/tasks', { kind: 'radar_search', keyword: '科学问题' }, expect.any(Object));
  });
  it('generates from selected real sources without requiring a target account', async () => {
    await render(); await checkSource(); await click('生成选题建议');
    expect(api.post).toHaveBeenCalledWith('/dy/tasks', { kind: 'radar_topics', source_task_id: hot.id, source_ids: ['hot:1'] }, expect.any(Object));
  });
  it('supports an optional owned account and keeps selection on a missing-positioning error', async () => {
    await render(); await checkSource();
    const select = container.querySelector('[aria-label="关联我的账号"]')!.closest('.ant-select')!.querySelector('.ant-select-selector')!;
    await act(async () => select.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })));
    const option = [...document.querySelectorAll<HTMLElement>('.ant-select-item-option')].find(el => el.textContent === '我的科普号')!;
    expect(option).toBeDefined(); await act(async () => option.click());
    vi.mocked(api.post).mockRejectedValueOnce(new Error('该账号缺少定位，请补充或取消关联'));
    await click('生成选题建议');
    expect(api.post).toHaveBeenCalledWith('/dy/tasks', expect.objectContaining({ target_account_id: 'a1' }), expect.any(Object));
    expect(container.querySelector<HTMLInputElement>('input[type="checkbox"]')?.checked).toBe(true);
    expect(container.textContent).toContain('该账号缺少定位');
  });
  it('saves advice with readable evidence and prevents duplicate clicks', async () => {
    tasks = [{ ...hot, id: 'topics1', kind: 'radar_topics', output: { source_task_id: hot.id, radar_items: [source], topics: [{ title: '一个选题', angle: '角度', hook: '开头', reason: '理由', materials_needed: '核对事实', refs: ['hot:1'] }] } }];
    await render(); await click('保存到选题库');
    expect(api.post).toHaveBeenCalledWith('/dy/ideas', expect.objectContaining({ source_task: 'topics1', notes: expect.stringContaining(source.url) }));
    expect(container.textContent).toContain('已保存到选题库');
    expect([...container.querySelectorAll<HTMLButtonElement>('button')].find(b => b.textContent === '已保存到选题库')?.disabled).toBe(true);
  });
  it('shows partial results and supports retrying a failed job after reload', async () => {
    tasks = [{ ...hot, status: 'failed', error: '限流', output: { ...hot.output, warning: '已保留部分作品' } }];
    await render(); expect(container.textContent).toContain('已保留部分作品');
    expect(container.textContent).toContain('科学问题');
    await click('重新执行');
    expect(api.post).toHaveBeenCalledWith('/dy/tasks', { kind: 'radar_hotlist' }, expect.any(Object));
  });
  it('offers manual retry after a task load failure', async () => {
    const get = vi.mocked(api.get).getMockImplementation()!;
    let failed = false;
    vi.mocked(api.get).mockImplementation(async (...args) => {
      if (args[0].endsWith('/tasks/scan1') && !failed) { failed = true; throw new Error('网络失败'); }
      return get(...args);
    });
    await render(); expect(container.textContent).toContain('网络失败');
    await click('重试加载'); expect(container.textContent).toContain('科学问题');
  });
  it('cancels a running scan and preserves its collected evidence', async () => {
    tasks = [{ ...hot, status: 'running', stage: '采集热榜' }];
    vi.mocked(api.post).mockImplementation(async url => {
      if (url.endsWith('/cancel')) tasks = [{ ...hot, status: 'cancelled' }];
      return tasks[0];
    });
    await render(); await click('取消任务');
    expect(api.post).toHaveBeenCalledWith('/dy/tasks/scan1/cancel');
    expect(container.textContent).toContain('任务已取消');
    expect(container.textContent).toContain('科学问题');
    expect(container.querySelector<HTMLInputElement>('input[type="checkbox"]')?.disabled).toBe(true);
  });
  it('keeps an empty search distinct from a failure', async () => {
    tasks = [{ ...hot, kind: 'radar_search', output: { keyword: '稀有关键词', radar_items: [] } }];
    await render();
    expect(container.textContent).toContain('本次未发现结果');
    expect(container.textContent).not.toContain('重试提交');
    expect(api.post).not.toHaveBeenCalled();
  });
  it('limits one analysis to twenty selected sources', async () => {
    tasks = [{ ...hot, output: { radar_items: Array.from({ length: 21 }, (_, i) => ({ ...source, id: `hot:${i}`, title: `热词${i}` })) } }];
    await render();
    const inputs = [...container.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')];
    for (const input of inputs.slice(0, 20)) await act(async () => input.click());
    expect(inputs[20].disabled).toBe(true);
    await click('生成选题建议');
    expect(api.post).toHaveBeenCalledWith('/dy/tasks', expect.objectContaining({ source_ids: Array.from({ length: 20 }, (_, i) => `hot:${i}`) }), expect.any(Object));
  });
  it.each(['missing', 'throws', 'absent'])('retries the same request and renews successful keys when crypto is %s', async mode => {
    vi.stubGlobal('crypto', mode === 'absent' ? undefined : mode === 'missing' ? {} : { randomUUID: () => { throw new Error('unsupported'); } });
    await render();
    vi.mocked(api.post).mockRejectedValueOnce(new Error('Network Error'));
    await click('刷新热榜');
    const key = () => { const calls = vi.mocked(api.post).mock.calls; return calls[calls.length - 1]?.[2]?.headers?.['Idempotency-Key']; };
    const first = key(); expect(first).toEqual(expect.any(String));
    await click('重试提交'); expect(key()).toBe(first);
    await click('刷新热榜'); expect(key()).not.toBe(first);
    expect(api.post).toHaveBeenCalledTimes(3);
  });
});
