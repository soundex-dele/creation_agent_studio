// @vitest-environment jsdom
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { ConfigProvider } from 'antd';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { api } from '@/services/api';
import { ProjectPromotionWorkspace } from '../ProjectPromotionPage';
import { promotionApi, type PromotionRecord, type CopyBody, type Version, type Task } from '@/services/projectPromotion';

vi.mock('@/services/api', () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() } }));
let root: Root; let container: HTMLDivElement;
const base = '/promotion';
const story: PromotionRecord = { id: 'case1', title: '排版演示', status: 'confirmed', revision: 0, archived: false, data: { audience: '创作者', problem: '排版耗时', case_type: 'demo', assets: [] } };
const idea: PromotionRecord = { ...story, id: 'topic1', title: '从文章到排版', case_id: story.id, data: { direction: 'demo', angle: '演示流程' } };
const body: CopyBody = { title: '排版演示', body: '真实功能文案', cover: '封面', pages: '', script: '', materials: '截图', shots: '', checks: '', formatted_html: '' };
const version: Version = { id: 'v1', number: 1, body, snapshot: { case: story }, created_at: '2026-10-14' };
const channel: PromotionRecord = { ...story, id: 'channel1', title: '公众号内容', status: 'ready', topic_id: idea.id, platform: 'wechat', confirmed_version_id: 'v1', latest_version: version, data: {} };
const rows: Record<string, PromotionRecord[]> = {};
let taskRows: Task[] = [];
const settle = async () => act(async () => { await new Promise(resolve => setTimeout(resolve, 10)); });
function button(label: string) { return [...document.querySelectorAll<HTMLButtonElement>('button')].find(b => b.textContent?.replace(/\s/g, '') === label.replace(/\s/g, ''))!; }
async function click(label: string) { expect(button(label)).toBeDefined(); await act(async () => button(label).click()); await settle(); }
function field(label: string) {
  const node = [...document.querySelectorAll<HTMLLabelElement>('label')].find(l => l.textContent === label);
  expect(node).toBeDefined(); return document.getElementById(node!.htmlFor) as HTMLInputElement;
}
async function input(label: string, value: string) {
  const el = field(label);
  await act(async () => { Object.getOwnPropertyDescriptor(el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype, 'value')!.set!.call(el, value); el.dispatchEvent(new Event('input', { bubbles: true })); });
}
async function render(tab = 'cases') {
  await act(async () => root.render(createElement(MemoryRouter, { initialEntries: [`/?tab=${tab}`] }, createElement(ConfigProvider, { theme: { token: { motion: false } } }, createElement(ProjectPromotionWorkspace, { base, root: '/tenant' })))));
  await settle();
}
beforeEach(() => {
  taskRows = [];
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} })));
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
  const computed = window.getComputedStyle.bind(window); vi.spyOn(window, 'getComputedStyle').mockImplementation(el => computed(el));
  Object.keys(rows).forEach(k => delete rows[k]); Object.assign(rows, { cases: [story], topics: [idea], channels: [channel], feedback: [] });
  vi.mocked(api.get).mockImplementation(async (url) => {
    if (url.endsWith('/ai/tasks')) return { results: taskRows, next: null, count: taskRows.length };
    if (url.endsWith('/report')) return { publications: [], groups: { platforms: [], cases: [] }, note: '未知数据留空', unknown_source_count: 0 };
    if (url.endsWith('/integrations') || url.endsWith('/handoffs')) return [];
    if (url.endsWith('/versions')) return [version];
    if (url.endsWith('/channels/channel1')) return { ...channel, revision: 1 };
    const result = rows[url.split('/').pop()!] || [];
    return { results: result, next: null, count: result.length };
  });
  vi.mocked(api.post).mockResolvedValue({ id: 'task1', kind: 'copy', status: 'failed', request: { kind: 'copy', channel_id: 'channel1' }, result: {}, error: '失败', created_at: '2026-10-14' });
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); vi.restoreAllMocks(); vi.resetAllMocks(); vi.unstubAllGlobals(); });

it('opens the four modules with a bounded page root and an honest empty report', async () => {
  await render();
  expect(container.querySelector('.promotion-page.app-scroll-page')).not.toBeNull();
  for (const label of ['02 · 选题与创作', '03 · 发布看板', '04 · 反馈复盘']) await click(label);
  expect(container.textContent).toContain('暂无效果依据');
  expect(container.textContent).not.toContain('排名');
});

it('retains case edits after a failed save and persists asset links', async () => {
  await render(); await click('新增案例'); await input('名称', '新场景'); await input('已实现能力', 'HTML 输出');
  await click('添加素材链接'); await input('素材 1 名称', '演示'); await input('HTTP(S) 链接', 'https://example.com/demo');
  vi.mocked(api.post).mockRejectedValueOnce(new Error('网络失败'));
  await click('保存'); expect(field('名称').value).toBe('新场景'); expect(document.body.textContent).toContain('网络失败');
  vi.mocked(api.post).mockResolvedValueOnce(story); await click('保存');
  expect(api.post).toHaveBeenLastCalledWith('/promotion/cases', expect.objectContaining({ title: '新场景', data: expect.objectContaining({ implemented: 'HTML 输出', assets: [expect.objectContaining({ url: 'https://example.com/demo' })] }) }));
});

it.each(['missing', 'throwing', 'absent'])('submits and retries channel generation on phone HTTP when crypto is %s', async mode => {
  vi.stubGlobal('crypto', mode === 'absent' ? undefined : mode === 'missing' ? {} : { randomUUID: () => { throw new Error('insecure'); } });
  await render('channels');
  vi.mocked(api.post).mockRejectedValueOnce(new Error('网络失败'));
  await click('生成新草稿');
  const first = vi.mocked(api.post).mock.calls.slice(-1)[0]![1] as Record<string, unknown>;
  expect(first.request_key).toEqual(expect.any(String));
  await click('生成新草稿');
  const retry = vi.mocked(api.post).mock.calls.slice(-1)[0]![1] as Record<string, unknown>;
  expect(retry.request_key).toBe(first.request_key);
  await click('生成新草稿');
  expect((vi.mocked(api.post).mock.calls.slice(-1)[0]![1] as Record<string, unknown>).request_key).not.toBe(first.request_key);
});

it('uses a new request key when failed payload changes for every task kind', async () => {
  const client = promotionApi(base);
  for (const kind of ['case', 'project', 'topics', 'review', 'copy']) {
    vi.mocked(api.post).mockRejectedValueOnce(new Error('network'));
    await expect(client.start({ kind, instruction: '原始' })).rejects.toThrow('network');
    const old = vi.mocked(api.post).mock.calls.slice(-1)[0]![1] as Record<string, unknown>;
    await client.start({ kind, instruction: '新的' });
    expect((vi.mocked(api.post).mock.calls.slice(-1)[0]![1] as Record<string, unknown>).request_key).not.toBe(old.request_key);
  }
});

it('keeps unsaved version changes on failure and prevents confirming the old version', async () => {
  await render('channels'); await click('编辑文案'); await input('正文／发布配文', '修改后的草稿');
  expect(button('确认此版本待发布').disabled).toBe(true);
  vi.mocked(api.post).mockRejectedValueOnce(new Error('保存失败')); await click('保存为新版本');
  expect(field('正文／发布配文').value).toBe('修改后的草稿');
  vi.mocked(api.post).mockResolvedValueOnce({ ...version, id: 'v2', number: 2, body: { ...body, body: '修改后的草稿' } });
  await click('保存为新版本');
  expect(api.post).toHaveBeenLastCalledWith('/promotion/channels/channel1/versions', expect.objectContaining({ revision: 0, body: expect.objectContaining({ body: '修改后的草稿' }) }));
  expect(button('确认此版本待发布').disabled).toBe(false);
});

it('creates another channel separately from the already published content', async () => {
  rows.channels = [{ ...channel, status: 'published' }]; await render('topics');
  vi.mocked(api.post).mockResolvedValueOnce({ ...channel, id: 'xiaohongshu', platform: 'xiaohongshu', status: 'draft' });
  await click('准备小红书');
  expect(api.post).toHaveBeenCalledWith('/promotion/channels', { title: idea.title, topic_id: 'topic1', platform: 'xiaohongshu' });
  expect(api.patch).not.toHaveBeenCalled();
});

it('preserves unknown feedback metrics and attribution', async () => {
  await render('feedback'); await click('记录反馈'); await input('名称', '咨询问题'); await input('私信中反复出现的问题', '可以接入资料吗？'); await click('保存');
  expect(api.post).toHaveBeenLastCalledWith('/promotion/feedback', expect.objectContaining({ channel_id: null, data: expect.objectContaining({ questions: '可以接入资料吗？' }) }));
  const payload = vi.mocked(api.post).mock.calls.slice(-1)[0]![1] as { data: Record<string, unknown> };
  expect(payload.data.views).toBeUndefined(); expect(payload.data.inquiries).toBeUndefined();
});

it.each(['missing', 'throwing', 'absent'])('retains project path and retries with the same key when crypto is %s', async mode => {
  vi.stubGlobal('crypto', mode === 'absent' ? undefined : mode === 'missing' ? {} : { randomUUID: () => { throw new Error('insecure'); } });
  await render();
  expect(button('探索项目并生成案例').disabled).toBe(true);
  await input('项目绝对路径', 'D:\\workspace\\demo');
  await input('探索方向（可选）', '展示文章排版');
  vi.mocked(api.post).mockRejectedValueOnce(new Error('路径不可访问'));
  await click('探索项目并生成案例');
  const first = vi.mocked(api.post).mock.calls.slice(-1)[0]![1] as Record<string, unknown>;
  expect(first).toEqual(expect.objectContaining({ kind: 'project', project_path: 'D:\\workspace\\demo', instruction: '展示文章排版', request_key: expect.any(String) }));
  expect(field('项目绝对路径').value).toBe('D:\\workspace\\demo');
  expect(container.textContent).toContain('路径不可访问');
  await click('探索项目并生成案例');
  expect((vi.mocked(api.post).mock.calls.slice(-1)[0]![1] as Record<string, unknown>).request_key).toBe(first.request_key);
  await click('探索项目并生成案例');
  expect((vi.mocked(api.post).mock.calls.slice(-1)[0]![1] as Record<string, unknown>).request_key).not.toBe(first.request_key);
});

it('displays project exploration progress and cancels through the task API', async () => {
  const task: Task = { id: 'project1', kind: 'project', status: 'running', stage: '正在读取源码', applied: false, request: { kind: 'project', project_path: '/workspace/project' }, result: {}, error: '', created_at: '2026-10-14' };
  taskRows = [task]; await render();
  expect(container.textContent).toContain('正在读取源码');
  expect(container.textContent).toContain('/workspace/project');
  vi.mocked(api.post).mockImplementationOnce(async () => { taskRows = [{ ...task, status: 'cancelled' }]; return taskRows[0]; });
  await click('取消生成');
  expect(api.post).toHaveBeenLastCalledWith('/promotion/ai/tasks/project1/cancel');
  expect(container.textContent).toContain('已取消，可重新生成');
  expect(button('取消生成')).toBeUndefined();
});

it('previews source-backed cases, applies the batch, and keeps provenance visible while editing', async () => {
  const source = { origin: { path: '/project', commit: 'abc123' }, coverage: { files_read: 2, files_total: 10, note: '静态阅读' }, evidence: { e1: { path: 'app.py', start: 1, end: 2, quote: '<script>never execute</script>', sha256: 'abcdef' } } };
  const cases = [{ title: '源码排版案例', data: { problem: '排版耗时', implemented: '格式化', evidence: 'app.py:1-2' }, source_snapshot: source }, { title: '另一场景', data: {}, source_snapshot: source }];
  const task: Task = { id: 'project1', kind: 'project', status: 'succeeded', applied: false, request: {}, result: { analysis: '两条案例', cases }, error: '', created_at: '2026-10-14' };
  taskRows = [task]; await render();
  expect(container.textContent).toContain('源码排版案例');
  expect(container.textContent).toContain('读取 2 / 10 个文本文件');
  expect(container.textContent).toContain('app.py:1-2');
  expect(container.querySelector('script')).toBeNull();
  vi.mocked(api.post).mockImplementationOnce(async () => {
    taskRows = [{ ...task, applied: true }];
    rows.cases = [{ ...story, ...cases[0], status: 'draft' }];
    return taskRows[0];
  });
  await click('加入可编辑草稿');
  expect(api.post).toHaveBeenLastCalledWith('/promotion/ai/tasks/project1/apply');
  expect(button('已加入草稿').disabled).toBe(true);
  await click('编辑与审核');
  expect(document.querySelector('.promotion-modal .promotion-source')?.textContent).toContain('abcdef');
  expect(field('名称').value).toBe('源码排版案例');
});
