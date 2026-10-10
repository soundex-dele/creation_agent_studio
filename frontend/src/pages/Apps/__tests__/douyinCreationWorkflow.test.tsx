// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '@/services/api';
import { DouyinHome } from '../DouyinBenchmarkPage';

vi.mock('@/services/api', () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } }));
const accounts = ['a1', 'a2'].map((id, i) => ({ id, name: `账号${i + 1}`, is_owned: true, source_url: `https://www.douyin.com/user/${id}`, profile: {}, group: '', notes: '' }));
const profiles = accounts.map((a, i) => ({ id: `p${i + 1}`, account: a.id, name: a.name, positioning: '生活科普', audience: '新手', conditions: '', active_version: `v${i + 1}`, active_version_number: i + 1 }));
const idea = { id: 'i1', title: '为什么晚上更容易饿', notes: '解释作息与饮食', tags: [], status: 'create', revision: 1, source_task: null };
const task = { id: 'written', kind: 'article', status: 'succeeded', stage: 'completed', sources: [], progress: {}, output: { title: idea.title, body: '写作结果', creation_context: { target_account_id: 'a1', account_name: '账号1', voice_version_number: 1 } } };
let container: HTMLDivElement; let root: Root;
beforeEach(() => {
  vi.clearAllMocks(); vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn(), addListener: vi.fn(), removeListener: vi.fn() })));
  const style = window.getComputedStyle; vi.spyOn(window, 'getComputedStyle').mockImplementation(el => style(el));
  vi.mocked(api.get).mockImplementation(async url => {
    if (url.endsWith('/accounts')) return { count: 2, results: accounts };
    if (url.endsWith('/creator-profiles')) return { count: 2, results: profiles };
    if (url.endsWith('/ideas')) return { count: 1, results: [idea] };
    if (url.endsWith('/connection')) return { connected: true, message: '已配置' };
    if (url.endsWith('/brands')) return [];
    if (url.endsWith('/tasks/written')) return task;
    if (url.endsWith('/versions')) return [{ id: 'saved1', revision: 1, content: { title: idea.title, body: '写作结果', notes: [] } }];
    if (url.endsWith('/publications/summary')) return { by_theme: [], by_expression: [], note: '当前账号' };
    return { count: 0, results: [] };
  });
  vi.mocked(api.post).mockResolvedValue(task);
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
function Location() { return <output>{useLocation().search}</output>; }
async function render(entry: string) { await act(async () => root.render(<MemoryRouter initialEntries={[entry]}><DouyinHome base="/dy" /><Location /></MemoryRouter>)); }
async function click(label: string) {
  const el = [...document.querySelectorAll<HTMLElement>('button,a,[role="tab"]')].find(e => e.textContent?.replace(/\s/g, '') === label.replace(/\s/g, ''));
  expect(el, label).toBeDefined(); await act(async () => el!.click());
}
async function choose(label: string, option: string) {
  const selector = document.querySelector(`[aria-label="${label}"]`)!.closest('.ant-select')!.querySelector('.ant-select-selector')!;
  await act(async () => selector.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })));
  const el = [...document.querySelectorAll<HTMLElement>('.ant-select-item-option-content')].find(e => e.textContent === option);
  expect(el, option).toBeDefined(); await act(async () => el!.click());
}

describe('Creator-first Douyin workspace', () => {
  it('restores a saved idea and creator from the URL, then writes without regenerating topics', async () => {
    await render('/?view=create&owned=a1&idea=i1&embedded=1');
    expect(container.textContent).toContain('文风 v1');
    expect(container.textContent).toContain(idea.title);
    expect(container.querySelector('[aria-label="目标时长（秒）"]')).toBeNull();
    expect(container.querySelector('.douyin-header-actions')?.textContent).not.toContain('添加对标账号');
    await click('开始写作');
    expect(api.post).toHaveBeenCalledWith('/dy/tasks', expect.objectContaining({ kind: 'article', idea_id: 'i1', target_account_id: 'a1', profile_id: 'p1' }), expect.anything());
    expect(vi.mocked(api.post).mock.calls.some(([, body]) => (body as { kind: string }).kind === 'topics')).toBe(false);
    expect(container.querySelector('[aria-label="文章编辑器"]')).not.toBeNull();
    expect(container.querySelector('output')?.textContent).toContain('embedded=1');
  });

  it('passes the saved idea across navigation and does not attach unrelated history', async () => {
    await render('/?view=ideas&owned=a1&entry=home');
    expect(container.textContent).not.toContain('本模块任务记录');
    await click('用此选题创作');
    expect(container.querySelector('output')?.textContent).toContain('idea=i1');
    expect(container.querySelector('output')?.textContent).toContain('owned=a1');
    expect(container.querySelector('output')?.textContent).toContain('entry=home');
    await click('开始写作');
    expect(api.post).toHaveBeenCalledWith('/dy/tasks', expect.objectContaining({ idea_id: 'i1', kind: 'article' }), expect.anything());
  });

  it('clears the previous creator and source context when switching accounts', async () => {
    await render('/?view=create&owned=a1&idea=i1&standalone=1');
    await choose('创作账号或独立档案', '账号2 · 我的账号');
    const query = container.querySelector('output')?.textContent;
    expect(query).toContain('owned=a2'); expect(query).toContain('standalone=1');
    expect(query).not.toContain('idea='); expect(query).not.toContain('source=');
    expect(container.textContent).toContain('文风 v2');
    expect([...container.querySelectorAll<HTMLButtonElement>('button')].find(e => e.textContent === '开始写作')?.disabled).toBe(true);
    expect(api.post).not.toHaveBeenCalled();
  });

  it('shows shooting fields only for scripts and submits a direct script', async () => {
    await render('/?view=create&owned=a1&idea=i1');
    await choose('创作产物', '拍摄脚本');
    expect(container.querySelector('[aria-label="目标时长（秒）"]')).not.toBeNull();
    await click('生成拍摄脚本');
    expect(api.post).toHaveBeenCalledWith('/dy/tasks', expect.objectContaining({ kind: 'script', idea_id: 'i1' }), expect.anything());
  });

  it('retains manually entered positioning when choosing a saved idea', async () => {
    await render('/?view=create');
    const positioning = container.querySelector<HTMLTextAreaElement>('[aria-label="positioning"]')!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(positioning, '我的独立定位');
      positioning.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await choose('选题库', idea.title);
    expect(container.querySelector<HTMLTextAreaElement>('[aria-label="positioning"]')?.value).toBe('我的独立定位');
    await click('开始写作');
    expect(api.post).toHaveBeenCalledWith('/dy/tasks', expect.objectContaining({ kind: 'article', idea_id: 'i1', positioning: '我的独立定位' }), expect.anything());
  });

  it('filters review and task requests by creator, with an explicit all-accounts option', async () => {
    await render('/?view=review&owned=a1');
    expect(api.get).toHaveBeenCalledWith('/dy/publications', expect.objectContaining({ account: 'a1' }));
    expect(api.get).toHaveBeenCalledWith('/dy/publications/summary', { account: 'a1' });
    expect(api.get).toHaveBeenCalledWith('/dy/tasks', expect.objectContaining({ target_account: 'a1', kind: 'review,refresh' }));
    await choose('复盘账号', '全部我的账号');
    expect(container.querySelector('output')?.textContent).not.toContain('owned=');
    expect(api.get).toHaveBeenCalledWith('/dy/publications', { page: 1 });
  });

  it('restores an old topic snapshot instead of silently using a newer voice', async () => {
    const get = vi.mocked(api.get).getMockImplementation()!;
    const topics = { ...task, id: 'topics1', kind: 'topics', output: { topics: [{ title: '历史选题', angle: '角度' }], creation_context: { target_account_id: 'a1', account_name: '账号1', voice_version_number: 7 } } };
    vi.mocked(api.get).mockImplementation(async (...args) => args[0].endsWith('/tasks') ? { count: 1, results: [topics] } : get(...args));
    await render('/?view=create&owned=a1&source=topics1&topic=0&mode=write');
    expect(container.textContent).toContain('文风 v7');
    expect(container.textContent).not.toContain('当前创作对象：账号1 · 文风 v1');
    await click('开始写作');
    expect(api.post).toHaveBeenCalledWith('/dy/tasks', { kind: 'article', source_task_id: 'topics1', topic_index: 0, target_account_id: 'a1' }, expect.anything());
  });

  it('offers saved articles as expression-experiment sources', async () => {
    const get = vi.mocked(api.get).getMockImplementation()!;
    vi.mocked(api.get).mockImplementation(async (...args) => args[0].endsWith('/tasks') ? { count: 1, results: [{ ...task, created_at: '2026-10-01T00:00:00Z' }] } : get(...args));
    await render('/?view=create&owned=a1&mode=variants');
    const selector = document.querySelector('[aria-label="来源文案"]')!.closest('.ant-select')!.querySelector('.ant-select-selector')!;
    await act(async () => selector.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })));
    const option = [...document.querySelectorAll<HTMLElement>('.ant-select-item-option-content')].find(el => el.textContent?.includes(idea.title));
    expect(option).toBeDefined(); await act(async () => option!.click());
    await click('生成候选表达');
    expect(api.post).toHaveBeenCalledWith('/dy/tasks', { kind: 'variants', source_version_id: 'saved1' }, expect.anything());
  });

  it('opens legacy rewrite history inside the central creation workspace', async () => {
    const get = vi.mocked(api.get).getMockImplementation()!;
    const rewrite = { ...task, id: 'rewrite1', account_id: 'ref1', kind: 'rewrite', output: {}, copy_context: { source_text: '原文', work_title: '参考作品', source_task_id: 'transcribe1' } };
    vi.mocked(api.get).mockImplementation(async (...args) => args[0].endsWith('/tasks/rewrite1') ? rewrite : args[0].endsWith('/versions') ? [{ id: 'copy1', revision: 1, content: { text: '已保存改写' } }] : get(...args));
    await render('/?view=create&task=rewrite1&entry=apps');
    expect(container.querySelector('output')?.textContent).toContain('mode=rewrite');
    expect(container.textContent).toContain('参考作品');
    expect(api.post).not.toHaveBeenCalled();
  });

  it.each(['missing', 'throwing', 'absent'])('submits and retries direct writing in simulated HTTP crypto %s', async mode => {
    vi.stubGlobal('crypto', mode === 'absent' ? undefined : mode === 'missing' ? {} : { randomUUID: () => { throw new Error('HTTP'); } });
    vi.mocked(api.post).mockRejectedValueOnce(new Error('Network Error')).mockResolvedValue(task);
    await render('/?view=create&owned=a1&idea=i1');
    await click('开始写作'); await click('开始写作'); await click('开始写作');
    const calls = vi.mocked(api.post).mock.calls;
    expect(calls).toHaveLength(3);
    expect(calls[0][2]?.headers?.['Idempotency-Key']).toBe(calls[1][2]?.headers?.['Idempotency-Key']);
    expect(calls[2][2]?.headers?.['Idempotency-Key']).not.toBe(calls[1][2]?.headers?.['Idempotency-Key']);
  });
});
