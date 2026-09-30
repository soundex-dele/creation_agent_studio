// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import { api } from '@/services/api';
import { researchApi, type ResearchTask, type Trend } from '@/services/douyinResearch';
import { DouyinHome } from '../DouyinBenchmarkPage';
import { ResearchHub } from '../douyin/ResearchHub';
import { ResearchResult } from '../douyin/ResearchResult';
import { TrendPanel } from '../douyin/ResearchLibrary';

vi.mock('@/services/api', () => ({ api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() } }));
const account = { id: 'a1', name: '科普账号', source_url: 'https://www.douyin.com/user/test', group: '', is_owned: true, notes: '', profile: {} };
const work = { platform_id: '123', cover: '', duration: 60, ratio: null, outstanding: false, has_upload: false, id: 'w1', title: '一个科学问题', account_id: 'a1', account_name: '科普账号', is_owned: true, description: '作品描述', likes: 0, comments: null, collects: 2, shares: null, kind: 'video', published_at: '2026-09-28T10:00:00Z', captured_at: '2026-09-30T10:00:00Z', url: 'https://www.douyin.com/?modal_id=123' };
const task: ResearchTask = { id: 'r1', kind: 'radar', status: 'succeeded', stage: 'completed', error: '', progress: {}, output: { topics: [{ title: '科学常识', angle: '用日常案例解释', refs: ['w1'] }], baseline: true }, sources: [work], work_id: null, run_id: 'run1', created_at: '2026-09-30T10:00:00Z' };
let container: HTMLDivElement; let root: Root;
beforeEach(() => {
  vi.clearAllMocks();
  const original = window.getComputedStyle; vi.spyOn(window, 'getComputedStyle').mockImplementation(el => original(el));
  Object.defineProperty(window, 'matchMedia', { writable: true, value: vi.fn(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() })) });
  Object.defineProperty(globalThis, 'IS_REACT_ACT_ENVIRONMENT', { configurable: true, value: true });
  vi.mocked(api.get).mockImplementation(async url => {
    if (url.endsWith('/accounts')) return { count: 1, results: [account] };
    if (url.endsWith('/connection')) return { connected: true, message: '已配置' };
    if (url.endsWith('/brands')) return [];
    if (url.endsWith('/works')) return { count: 1, results: [work] };
    if (url.endsWith('/tasks')) return { count: 1, results: [task] };
    if (url.endsWith('/tasks/r1')) return task;
    if (url.endsWith('/versions')) return [];
    return { count: 0, results: [] };
  });
  vi.mocked(api.post).mockResolvedValue(task);
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); vi.restoreAllMocks(); });
async function render(node: React.ReactNode) { await act(async () => root.render(<MemoryRouter>{node}</MemoryRouter>)); }
async function click(label: string) { const button = [...document.querySelectorAll<HTMLElement>('button,[role="tab"]')].find(el => el.textContent === label); expect(button, label).toBeDefined(); await act(async () => button!.click()); }

describe('Private Douyin research workflow', () => {
  it('exposes all five sections without removing the account library', async () => {
    await render(<DouyinHome base="/dy" />);
    expect(container.textContent).toContain('我的对标账号');
    for (const label of ['对标研究', '选题库', '创作中心', '作品复盘', '订阅通知']) expect(container.textContent).toContain(label);
    await click('跨账号研究与选题雷达');
    expect(container.textContent).toContain('生成选题雷达');
    expect(container.querySelector('main')?.className).toContain('app-scroll-page');
  });
  it.each([['ideas', '灵感与选题库'], ['create', '开头与标题实验室'], ['review', '自己的作品复盘'], ['subscriptions', '订阅与通知'], ['profiles', '个人创作档案']])('opens %s with its actions', async (section, title) => {
    await render(<ResearchHub base="/dy" section={section} onSection={vi.fn()} openAccount={vi.fn()} />);
    expect(container.textContent).toContain(title);
  });
  it('starts a bounded radar task and offers explicit account comparison', async () => {
    await render(<ResearchHub base="/dy" section="research" onSection={vi.fn()} openAccount={vi.fn()} />);
    await click('生成选题雷达');
    expect(api.post).toHaveBeenCalledWith('/dy/tasks', { kind: 'radar', account_ids: [], group: '', days: 30 }, expect.objectContaining({ headers: expect.any(Object) }));
    const compare = [...container.querySelectorAll<HTMLButtonElement>('button')].find(el => el.textContent === '比较账号数据');
    expect(compare?.disabled).toBe(true);
  });
  it('saves a radar topic with its source and verifies the work', async () => {
    await render(<ResearchResult client={researchApi('/dy')} task={task} run={vi.fn()} />);
    await click('保存为选题');
    expect(api.post).toHaveBeenCalledWith('/dy/ideas', expect.objectContaining({ title: '科学常识', source_task: 'r1' }));
    await click('核对作品 w1');
    expect(document.body.textContent).toContain('作品描述');
  });
  it('does not auto-run AI when opening subscription notifications', async () => {
    await render(<ResearchHub base="/dy" section="subscriptions" onSection={vi.fn()} openAccount={vi.fn()} />);
    await click('应用内通知');
    expect(api.post).not.toHaveBeenCalled();
  });
  it('keeps zero, missing and negative trend values distinct with a table', async () => {
    const data = { work, points: [{ captured_at: '2026-09-30T10:00:00Z', values: { likes: 0, comments: null, collects: 2, shares: null }, delta: { likes: -4, comments: null, collects: 0, shares: null }, per_hour: { likes: -2, comments: null, collects: 0, shares: null } }] } as Trend;
    await render(<TrendPanel data={data} />);
    expect(container.querySelector('.douyin-trend')).toBeNull();
    expect(container.querySelector('table')?.textContent).toContain('-4');
    expect(container.querySelector('table')?.textContent).toContain('-2');
    expect(container.querySelector('caption')?.textContent).toContain('点赞采集历史');
  });
});
