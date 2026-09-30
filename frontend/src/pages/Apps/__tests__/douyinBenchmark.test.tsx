// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import { api } from '@/services/api';
import { douyinApi, metric, type DouyinTask } from '@/services/douyinBenchmark';
import { applicationPath } from '@/lib/applicationCatalog';
import { DouyinHome } from '../DouyinBenchmarkPage';
import { DouyinWorkspace } from '../douyin/DouyinWorkspace';
import { AnalysisResult } from '../douyin/AnalysisResult';
import { ScriptEditor } from '../douyin/ScriptEditor';
vi.mock('@/services/api', () => ({ api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() } }));
const account = { id: 'a1', source_url: 'https://www.douyin.com/user/test', name: '知识账号', group: '', notes: '', profile: {}, updated_at: '2026-09-29' };
const work = { id: 'w1', title: '如何读书', likes: 0, comments: null, collects: null, shares: null, ratio: null, published_at: null, duration: 60, url: 'https://www.douyin.com/video/7536599534051626299', video_url: 'https://v3.douyinvod.com/real-file.mp4', cover: '', kind: 'video' };
const script = { title: '读书的新角度', cover: '从问题开始', narration: '今天讨论一个问题。', scenes: [{ time: '0–5秒', visual: '固定机位', spoken: '今天讨论一个问题。' }], checklist: ['准备提词器'] };
const task: DouyinTask = { id: 't1', kind: 'breakdown', work_id: 'w1', run_id: 'r1', status: 'succeeded', stage: 'completed', error: '', created_at: '2026-09-29', progress: {}, sources: [], output: { visual_status: 'pending', visual_note: '未配置视觉模型，已保留转写和关键帧', segments: [{ id: 's1', start: 0, end: 5, text: '你有没有遇到过这种情况？' }], claims: [{ type: 'observation', text: '以提问开场', refs: ['s1'] }] } };
let container: HTMLDivElement; let root: Root;
beforeEach(() => {
  vi.clearAllMocks();
  const computed = window.getComputedStyle;
  vi.spyOn(window, 'getComputedStyle').mockImplementation((element) => computed(element));
  Object.defineProperty(window, 'matchMedia', { writable: true, value: vi.fn().mockImplementation(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() })) });
  Object.defineProperty(globalThis, 'IS_REACT_ACT_ENVIRONMENT', { configurable: true, value: true });
  vi.mocked(api.get).mockImplementation(async (url) => {
    if (url.endsWith('/accounts')) return { count: 1, results: [account] };
    if (url.endsWith('/connection')) return { connected: false, message: '采集登录状态已失效' };
    if (url.endsWith('/collector-config')) return { configured: true, user_agent: 'Chrome saved UA', has_cookies: true, screen: '1920x1080', language: 'zh-CN', timezone: 'Asia/Shanghai', updated_at: null };
    if (url.endsWith('/brands')) return [];
    if (url.endsWith('/works')) return { items: [work], sample_size: 1, median_likes: null, explanation: '样本不足10条', batch: { ...task, kind: 'collect', output: { actual: 1, complete: true } } };
    if (url.endsWith('/tasks')) return { count: 1, results: [task] };
    if (url.endsWith('/tasks/t1')) return task;
    if (url.endsWith('/versions')) return [{ id: 'v1', revision: 1, content: script, created_at: '2026-09-29' }];
    return account;
  });
  vi.mocked(api.post).mockResolvedValue(task);
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); vi.restoreAllMocks(); });
async function render(node: React.ReactNode) { await act(async () => root.render(<MemoryRouter>{node}</MemoryRouter>)); }
async function click(text: string) {
  const candidates = [...document.querySelectorAll<HTMLElement>('button,[role="tab"]')];
  const element = candidates.find((el) => el.textContent === text) ?? candidates.find((el) => el.textContent?.includes(text));
  expect(element, text).toBeDefined(); await act(async () => element!.click());
}
async function setText(label: string, value: string) {
  const element = document.querySelector<HTMLInputElement | HTMLTextAreaElement>(`[aria-label="${label}"]`)!;
  expect(element).not.toBeNull();
  const proto = element.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  await act(async () => { Object.getOwnPropertyDescriptor(proto, 'value')!.set!.call(element, value); element.dispatchEvent(new Event('input', { bubbles: true })); });
}

describe('Douyin benchmark workflow', () => {
  it('registers its route and distinguishes unavailable metrics from zero', () => {
    expect(applicationPath({ id: 'douyin-benchmark', applicationId: 42, rendererKey: 'douyin-benchmark', kind: 'custom' })).toBe('/applications/42/douyin-benchmark?entry=apps');
    expect(metric(null)).toBe('未获取'); expect(metric(0)).toBe('0');
  });
  it('shows login failure while keeping existing accounts accessible', async () => {
    await render(<DouyinHome base="/dy" />);
    expect(container.textContent).toContain('采集登录状态已失效'); expect(container.textContent).toContain('知识账号');
  });
  it('adds an account and sends an idempotency key', async () => {
    vi.mocked(api.post).mockResolvedValue({ ...account, task });
    await render(<DouyinHome base="/dy" />); await click('添加对标账号');
    await setText('主页链接或分享文本', account.source_url); await click('添加并采集');
    expect(api.post).toHaveBeenCalledWith('/dy/accounts', expect.objectContaining({ source: account.source_url, count: 50 }), expect.objectContaining({ headers: { 'Idempotency-Key': expect.any(String) } }));
  });
  it('renders missing counts and launches video breakdown from the work list', async () => {
    await render(<DouyinWorkspace client={douyinApi('/dy')} accountId="a1" onRemoved={vi.fn()} />);
    await click('作品库'); expect(container.textContent).toContain('未获取');
    await click('转写并拆解');
    expect(api.post).toHaveBeenCalledWith('/dy/accounts/a1/tasks', { kind: 'breakdown', work_id: 'w1' }, expect.anything());
    expect(container.textContent).toContain('以提问开场');
  });
  it('keeps work results when refresh fails', async () => {
    vi.mocked(api.post).mockRejectedValue(new Error('采集服务不可用'));
    await render(<DouyinWorkspace client={douyinApi('/dy')} accountId="a1" onRemoved={vi.fn()} />);
    await click('作品库'); await click('刷新作品数据');
    expect(container.textContent).toContain('如何读书'); expect(container.textContent).toContain('采集服务不可用');
  });
  it('opens timestamped evidence and identifies missing visual analysis', async () => {
    await render(<AnalysisResult client={douyinApi('/dy')} accountId="a1" task={task} />);
    expect(container.textContent).toContain('未配置视觉模型');
    await act(async () => document.querySelector<HTMLButtonElement>('[aria-label="查看出处 s1"]')!.click());
    expect(document.body.textContent).toContain('0.0–5.0秒'); expect(document.body.textContent).toContain('你有没有遇到过这种情况？');
  });
  it('saves a new script version without overwriting the prior one', async () => {
    vi.mocked(api.post).mockResolvedValue({ id: 'v2', revision: 2, content: { ...script, narration: '改成我的表达。' }, created_at: '2026-09-29' });
    await render(<ScriptEditor client={douyinApi('/dy')} accountId="a1" taskId="t1" />);
    await setText('完整口播稿', '改成我的表达。');
    expect([...container.querySelectorAll('button')].find(button => button.textContent === '导入动画制作')?.disabled).toBe(true);
    await click('保存新版本');
    expect(api.post).toHaveBeenCalledWith('/dy/accounts/a1/tasks/t1/versions', { revision: 1, content: { ...script, narration: '改成我的表达。' } });
    expect(container.textContent).toContain('已保存新版本');
  });
  it('shows the account empty state', async () => {
    const original = vi.mocked(api.get).getMockImplementation()!;
    vi.mocked(api.get).mockImplementation((url, ...args) => url.endsWith('/accounts') ? Promise.resolve({ count: 0, results: [] }) : original(url, ...args));
    await render(<DouyinHome base="/dy" />); expect(container.textContent).toContain('添加第一个账号');
  });
});


describe('personal collector settings', () => {
  it('keeps saved cookies blank and saves replacement credentials', async () => {
    vi.mocked(api.put).mockResolvedValue({ configured: true });
    await render(<DouyinHome base="/dy" />); await click('采集设置');
    expect((document.querySelector('[aria-label="采集 Cookie"]') as HTMLTextAreaElement).value).toBe('');
    expect(document.body.textContent).toContain('已保存，留空保留原值');
    await setText('采集 User-Agent', 'new Chrome UA'); await setText('采集 Cookie', 'UIFID_TEMP=personal-cookie');
    await click('保存配置');
    expect(api.put).toHaveBeenCalledWith('/dy/collector-config', expect.objectContaining({ user_agent: 'new Chrome UA', cookies: 'UIFID_TEMP=personal-cookie' }));
    expect(document.querySelector('[aria-label="采集 Cookie"]')).toBeNull();
    await click('采集设置');
    expect((document.querySelector('[aria-label="采集 Cookie"]') as HTMLTextAreaElement).value).toBe('');
  });
  it('clears only the personal collector configuration', async () => {
    vi.mocked(api.delete).mockResolvedValue(undefined);
    await render(<DouyinHome base="/dy" />); await click('采集设置'); await click('清除已保存配置');
    expect(api.delete).toHaveBeenCalledWith('/dy/collector-config');
    expect(document.querySelector('[aria-label="采集 Cookie"]')).toBeNull();
  });
  it('keeps the form open on a configuration error', async () => {
    vi.mocked(api.put).mockRejectedValue(new Error('Cookie 格式错误'));
    await render(<DouyinHome base="/dy" />); await click('采集设置'); await click('保存配置');
    expect(document.body.textContent).toContain('Cookie 格式错误');
    expect(document.querySelector('[aria-label="采集 Cookie"]')).not.toBeNull();
  });
});


it('opens DTK media for playback and keeps the Douyin source page separate', async () => {
  await render(<DouyinWorkspace client={douyinApi('/dy')} accountId="a1" onRemoved={() => {}} />);
  await click('作品库');
  const links = [...container.querySelectorAll('a')];
  expect(links.find((link) => link.textContent === '播放视频')?.getAttribute('href')).toBe('https://v3.douyinvod.com/real-file.mp4');
  expect(links.find((link) => link.textContent === '抖音来源页')?.getAttribute('href')).toBe('https://www.douyin.com/video/7536599534051626299');
});
