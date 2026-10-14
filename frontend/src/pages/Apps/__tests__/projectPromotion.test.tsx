// @vitest-environment jsdom
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { ConfigProvider } from 'antd';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { api } from '@/services/api';
import { ProjectPromotionWorkspace } from '../ProjectPromotionPage';
import { promotionApi, materialTypes, explorationFocusDescriptions, type PromotionRecord, type CopyBody, type Version, type Task } from '@/services/projectPromotion';

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
afterEach(async () => { await act(async () => root.unmount()); container.remove(); vi.useRealTimers(); vi.restoreAllMocks(); vi.resetAllMocks(); vi.unstubAllGlobals(); });

async function choose(label: string, value: string) {
  const el = field(label);
  await act(async () => { el.value = value; el.dispatchEvent(new Event('change', { bubbles: true })); });
}

async function checkMaterial(title: string) {
  const label = [...document.querySelectorAll<HTMLLabelElement>('.promotion-material-option')].find(el => el.textContent?.startsWith(title));
  expect(label).toBeDefined();
  await act(async () => label!.querySelector('input')!.click());
}

it('keeps factual material fields separate from case fields and filters types', async () => {
  rows.cases.push({ ...story, id: 'feature1', title: '任务编排', data: { material_type: 'architecture', summary: '技术设计资料' } });
  await render();
  await choose('素材类型筛选', 'architecture');
  expect(container.textContent).toContain('任务编排');
  expect(container.textContent).not.toContain('排版演示');
  await click('新增素材');
  expect(document.body.textContent).toContain('事实资料');
  expect(document.body.textContent).not.toContain('遇到什么问题');
  await input('名称', '架构设计'); await input('素材摘要', '设计摘要'); await input('事实资料', '文档声明的设计');
  await choose('素材类型', 'architecture');
  await click('保存');
  expect(api.post).toHaveBeenLastCalledWith('/promotion/cases', expect.objectContaining({ data: expect.objectContaining({ material_type: 'architecture', facts: '文档声明的设计' }) }));
});

it('creates and edits topics with multiple materials, thesis and outline', async () => {
  rows.cases.push({ ...story, id: 'feature1', title: '任务编排', data: { material_type: 'feature' } });
  rows.topics = [{ ...idea, case_ids: ['case1', 'feature1'], data: { direction: 'workflow', thesis: '完整工作流', outline: '输入到输出' } }];
  await render('topics');
  expect(container.textContent).toContain('来源：排版演示、任务编排');
  expect(container.textContent).toContain('完整工作流');
  await click('编辑与审核');
  expect([...document.querySelectorAll<HTMLInputElement>('.promotion-modal input[type="checkbox"]')].filter(el => el.checked)).toHaveLength(2);
  await input('核心观点', '组合能力'); await input('内容结构', '先介绍输入，再展示结果');
  await click('保存');
  expect(api.patch).toHaveBeenLastCalledWith('/promotion/topics/topic1', expect.objectContaining({ case_ids: ['case1', 'feature1'], data: expect.objectContaining({ thesis: '组合能力', outline: '先介绍输入，再展示结果' }) }));
});

it.each(['missing', 'throwing', 'absent'])('generates topics from multiple materials with stable retry keys when crypto is %s', async mode => {
  vi.stubGlobal('crypto', mode === 'absent' ? undefined : mode === 'missing' ? {} : { randomUUID: () => { throw new Error('insecure'); } });
  rows.cases.push({ ...story, id: 'feature1', title: '任务编排', data: { material_type: 'feature' } });
  rows.cases.push({ ...story, id: 'draft1', title: '待审核资料', status: 'draft' });
  await render('topics');
  expect(button('生成选题建议').disabled).toBe(true);
  await checkMaterial('排版演示'); await checkMaterial('任务编排');
  const draft = [...document.querySelectorAll<HTMLLabelElement>('.promotion-material-option')].find(el => el.textContent?.startsWith('待审核资料'))!;
  expect(draft.querySelector('input')!.disabled).toBe(true);
  vi.mocked(api.post).mockRejectedValueOnce(new Error('网络失败'));
  await click('生成选题建议');
  const first = vi.mocked(api.post).mock.calls.slice(-1)[0]![1] as Record<string, unknown>;
  expect(first.case_ids).toEqual(['case1', 'feature1']);
  await click('生成选题建议');
  expect((vi.mocked(api.post).mock.calls.slice(-1)[0]![1] as Record<string, unknown>).request_key).toBe(first.request_key);
  await click('生成选题建议');
  expect((vi.mocked(api.post).mock.calls.slice(-1)[0]![1] as Record<string, unknown>).request_key).not.toBe(first.request_key);
});

it('opens the four modules with a bounded page root and an honest empty report', async () => {
  await render();
  expect(container.querySelector('.promotion-page.app-scroll-page')).not.toBeNull();
  for (const label of ['02 · 选题与创作', '03 · 发布看板', '04 · 反馈复盘']) await click(label);
  expect(container.textContent).toContain('暂无效果依据');
  expect(container.textContent).not.toContain('排名');
});

it('retains case edits after a failed save and persists asset links', async () => {
  await render(); await click('新增素材'); await input('名称', '新场景'); await input('已实现能力', 'HTML 输出');
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
  expect(button('探索项目并生成素材').disabled).toBe(true);
  await input('项目绝对路径', 'D:\\workspace\\demo');
  await input('探索方向（可选）', '展示文章排版');
  await choose('探索侧重', 'deployment');
  vi.mocked(api.post).mockRejectedValueOnce(new Error('路径不可访问'));
  await click('探索项目并生成素材');
  const first = vi.mocked(api.post).mock.calls.slice(-1)[0]![1] as Record<string, unknown>;
  expect(first).toEqual(expect.objectContaining({ kind: 'project', exploration_mode: 'overview', exploration_focus: 'deployment', project_path: 'D:\\workspace\\demo', instruction: '展示文章排版', request_key: expect.any(String) }));
  expect(field('项目绝对路径').value).toBe('D:\\workspace\\demo');
  expect(container.textContent).toContain('路径不可访问');
  await click('探索项目并生成素材');
  expect((vi.mocked(api.post).mock.calls.slice(-1)[0]![1] as Record<string, unknown>).request_key).toBe(first.request_key);
  await click('探索项目并生成素材');
  expect((vi.mocked(api.post).mock.calls.slice(-1)[0]![1] as Record<string, unknown>).request_key).not.toBe(first.request_key);
});

it('requires an explicit direction before deep exploration and changes retry keys across modes', async () => {
  await render();
  await input('项目绝对路径', '/workspace/project');
  await choose('探索模式', 'deep');
  expect(button('探索项目并生成素材').disabled).toBe(true);
  await input('深入方向（必填）', '任务调度与失败恢复');
  vi.mocked(api.post).mockRejectedValueOnce(new Error('网络失败'));
  await click('探索项目并生成素材');
  const deep = vi.mocked(api.post).mock.calls.slice(-1)[0]![1] as Record<string, unknown>;
  expect(deep).toEqual(expect.objectContaining({ exploration_mode: 'deep', instruction: '任务调度与失败恢复' }));
  await choose('探索模式', 'overview');
  await click('探索项目并生成素材');
  const overview = vi.mocked(api.post).mock.calls.slice(-1)[0]![1] as Record<string, unknown>;
  expect(overview.exploration_mode).toBe('overview');
  expect(overview.request_key).not.toBe(deep.request_key);
});

it('opens a source-backed material as a deep exploration direction without submitting automatically', async () => {
  rows.cases = [{ ...story, data: { ...story.data, material_type: 'deployment' }, source_snapshot: { origin: { path: '/workspace/original' } } }];
  await render();
  await click('深入此方向');
  expect(field('项目绝对路径').value).toBe('/workspace/original');
  expect(field('探索模式').value).toBe('deep');
  expect(field('探索侧重').value).toBe('deployment');
  expect(field('深入方向（必填）').value).toContain('排版演示');
  expect(api.post).not.toHaveBeenCalled();
  await click('探索项目并生成素材');
  expect(api.post).toHaveBeenLastCalledWith('/promotion/ai/tasks', expect.objectContaining({ exploration_mode: 'deep', project_path: '/workspace/original' }));
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

it('opens active execution history and updates tool status through polling without losing failed history', async () => {
  vi.useFakeTimers();
  const task: Task = { id: 'live', kind: 'project', status: 'running', applied: false, request: {}, result: {}, error: '', created_at: '2026-10-14',
    activity: { dropped: 0, items: [{ id: 'read', title: '读取文件', detail: 'cat app.py <script>not executable</script>', status: 'running', created_at: '2026-10-14T10:00:00Z', updated_at: '2026-10-14T10:00:00Z' }] } };
  taskRows = [task];
  await act(async () => root.render(createElement(MemoryRouter, {}, createElement(ProjectPromotionWorkspace, { base, root: '/tenant' }))));
  expect(container.querySelector<HTMLDetailsElement>('.promotion-task-section > details')?.open).toBe(true);
  expect(container.querySelector('.promotion-activity')?.textContent).toContain('正在执行');
  expect(container.querySelector('script')).toBeNull();
  taskRows = [{ ...task, status: 'failed', error: '模型中断', activity: { dropped: 0, items: [{ ...task.activity!.items[0], status: 'failed' }] } }];
  await act(async () => vi.advanceTimersByTimeAsync(3000));
  expect(container.querySelector('.promotion-activity')?.textContent).toContain('失败');
  expect(container.querySelector('.promotion-activity')?.textContent).toContain('cat app.py');
  expect(container.querySelector<HTMLDetailsElement>('.promotion-task-section > details')?.open).toBe(true);
  expect(button('取消生成')).toBeUndefined();
});

it('limits long histories, expands older steps, and marks unfinished cancelled tools honestly', async () => {
  taskRows = [{ id: 'history', kind: 'project', status: 'cancelled', applied: false, request: {}, result: {}, error: '', created_at: '2026-10-14',
    activity: { dropped: 2, items: Array.from({ length: 12 }, (_, i) => ({ id: String(i), title: `步骤 ${i}`, detail: `命令 ${i}`, status: i === 11 ? 'running' : 'completed', created_at: '2026-10-14T10:00:00Z', updated_at: '2026-10-14T10:00:00Z' })) } }];
  await render();
  expect(container.querySelectorAll('.promotion-activity-item')).toHaveLength(8);
  expect(container.querySelector('.promotion-activity')?.textContent).toContain('未完成');
  expect(container.querySelector('.promotion-activity')?.textContent).toContain('较早的 2 条记录已省略');
  await click('展开全部 12 条记录');
  expect(container.querySelectorAll('.promotion-activity-item')).toHaveLength(12);
  await click('只看最近 8 条');
  expect(container.querySelectorAll('.promotion-activity-item')).toHaveLength(8);
});

it.each([
  { files_read: 2, files_total: 10, note: '静态阅读' },
  { files_cited: 2, files_total: 10, note: '静态阅读' },
])('previews and edits legacy cases without source citations (%j)', async coverage => {
  const evidence = { path: 'app.py', start: 1, end: 2, quote: '<script>never execute</script>', sha256: 'abcdef' };
  const source = { origin: { path: '/project', commit: 'abc123' }, coverage, evidence: { e1: evidence, e2: { ...evidence, start: 3, end: 4 }, e3: { ...evidence, path: 'src/render.ts' } } };
  const cases = [{ title: '源码排版案例', data: { problem: '排版耗时', implemented: '格式化', evidence: 'app.py\nsrc/render.ts' }, source_snapshot: source }, { title: '另一场景', data: {}, source_snapshot: source }];
  const task: Task = { id: 'project1', kind: 'project', status: 'succeeded', applied: false, request: {}, result: { analysis: '两条案例', cases }, error: '', created_at: '2026-10-14' };
  taskRows = [task]; await render();
  expect(container.textContent).toContain('源码排版案例');
  const expectNoCitations = (element: Element | null) => {
    for (const text of ['源码依据', 'app.py', 'src/render.ts', 'never execute', 'abcdef']) expect(element?.textContent).not.toContain(text);
    for (const textarea of element?.querySelectorAll('textarea') || []) expect(textarea.value).not.toContain('app.py');
  };
  expectNoCitations(container);
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
  expectNoCitations(document.querySelector('.promotion-modal'));
  expect(field('名称').value).toBe('源码排版案例');
});

it('shows material names in version history without exposing historical code excerpts', async () => {
  const previous = vi.mocked(api.get).getMockImplementation()!;
  vi.mocked(api.get).mockImplementation(async url => url.endsWith('/versions') ? [{ ...version, snapshot: { cases: [{ ...story, source_snapshot: { evidence: { e1: { path: 'private.py', quote: 'legacy-code-excerpt' } } } }] } }] : previous(url));
  await render('channels');
  await click('编辑文案');
  const modal = document.querySelector('.promotion-modal')!;
  expect(modal.textContent).toContain('本版本的关联素材');
  expect(modal.textContent).toContain('排版演示 · 修订 0');
  expect(modal.textContent).not.toContain('private.py');
  expect(modal.textContent).not.toContain('legacy-code-excerpt');
});


it('offers every material category as a focus with explanations and preserves retry keys until focus changes', async () => {
  await render();
  const select = field('探索侧重') as unknown as HTMLSelectElement;
  expect(select.value).toBe('all');
  expect(container.textContent).toContain('当前为综合视角，可生成多种素材分类');
  expect([...select.querySelectorAll('optgroup')].map(group => group.label)).toEqual(['综合视角', '素材分类']);
  const categoryOptions = [...select.querySelectorAll('optgroup[label="素材分类"] option')] as HTMLOptionElement[];
  expect(categoryOptions.map(option => [option.value, option.text])).toEqual(Object.entries(materialTypes));
  expect(categoryOptions).toHaveLength(21);
  for (const focus of ['overview', 'application_overview', 'deployment', 'security', 'performance', 'roadmap']) {
    await choose('探索侧重', focus);
    expect(container.textContent).toContain(`当前仅生成「${materialTypes[focus]}」素材`);
    expect(container.textContent).not.toContain('当前为综合视角');
    expect(document.getElementById(select.getAttribute('aria-describedby')!)?.textContent).toBe(explorationFocusDescriptions[focus]);
  }
  await input('项目绝对路径', '/workspace/project');
  vi.mocked(api.post).mockRejectedValueOnce(new Error('网络失败')).mockRejectedValueOnce(new Error('网络失败'));
  await click('探索项目并生成素材');
  const first = vi.mocked(api.post).mock.calls.slice(-1)[0]![1] as Record<string, unknown>;
  expect(first.exploration_focus).toBe('roadmap');
  await click('探索项目并生成素材');
  expect((vi.mocked(api.post).mock.calls.slice(-1)[0]![1] as Record<string, unknown>).request_key).toBe(first.request_key);
  await choose('探索侧重', 'cost');
  await click('探索项目并生成素材');
  const next = vi.mocked(api.post).mock.calls.slice(-1)[0]![1] as Record<string, unknown>;
  expect(next.exploration_focus).toBe('cost');
  expect(next.exploration_mode).toBe('overview');
  expect(next.request_key).not.toBe(first.request_key);
});

it('filters and edits new material categories', async () => {
  rows.cases.push({ ...story, id: 'deployment1', title: '运行条件', data: { material_type: 'deployment', summary: '部署说明', facts: '本地运行' } });
  await render();
  await choose('素材类型筛选', 'deployment');
  expect(container.textContent).toContain('运行条件');
  expect(container.textContent).not.toContain('排版演示');
  await click('编辑与审核');
  expect(field('素材类型').value).toBe('deployment');
  await choose('素材类型', 'cost');
  await click('保存');
  expect(api.patch).toHaveBeenLastCalledWith('/promotion/cases/deployment1', expect.objectContaining({ data: expect.objectContaining({ material_type: 'cost' }) }));
});


it('keeps project and application overviews separate in filters, editing and deep exploration', async () => {
  rows.cases = [
    { ...story, id: 'project-overview', title: '创作平台整体介绍', data: { material_type: 'overview' } },
    { ...story, id: 'application-overview', title: '项目宣传助手介绍', data: { material_type: 'application_overview' }, source_snapshot: { origin: { path: '/workspace/platform' } } },
  ];
  await render();
  await choose('素材类型筛选', 'application_overview');
  expect(container.textContent).toContain('项目宣传助手介绍');
  expect(container.textContent).not.toContain('创作平台整体介绍');
  await click('深入此方向');
  expect(field('探索侧重').value).toBe('application_overview');
  expect(field('深入方向（必填）').value).toContain('项目宣传助手介绍');
  await click('编辑与审核');
  expect(field('素材类型').value).toBe('application_overview');
  await click('保存');
  expect(api.patch).toHaveBeenLastCalledWith('/promotion/cases/application-overview', expect.objectContaining({ data: expect.objectContaining({ material_type: 'application_overview' }) }));
});
