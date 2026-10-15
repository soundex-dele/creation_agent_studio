// @vitest-environment jsdom
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { ConfigProvider } from 'antd';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { api } from '@platform/http';
import { ProjectPromotionWorkspace } from '../ProjectPromotionPage';
import { promotionApi, materialTypes, explorationFocusDescriptions, type Handoff, type PromotionRecord, type Task } from '../../services/projectPromotion';

const { navigate } = vi.hoisted(() => ({ navigate: vi.fn() }));
vi.mock('react-router-dom', async importOriginal => ({ ...await importOriginal<typeof import('react-router-dom')>(), useNavigate: () => navigate }));
vi.mock('@/services/api', () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() } }));
let root: Root; let container: HTMLDivElement;
const base = '/promotion';
const story: PromotionRecord = { id: 'case1', title: '排版演示', status: 'confirmed', revision: 0, archived: false, data: { audience: '创作者', problem: '排版耗时', case_type: 'demo', assets: [] } };
const idea: PromotionRecord = { ...story, id: 'topic1', title: '从文章到排版', case_id: story.id, data: { direction: 'demo', angle: '演示流程' } };
const rows: Record<string, PromotionRecord[]> = {};
let taskRows: Task[] = [];
let handoffRows: Handoff[] = [];
let popup: { opener: Window | null; closed: boolean; location: { replace: ReturnType<typeof vi.fn> }; close: ReturnType<typeof vi.fn> };
const destinations = [
  { id: 10, slug: 'wechat-viral-article', name: '公众号爆款写作' },
  { id: 11, slug: 'write-image-text-copy', name: '图文文案' },
  { id: 12, slug: 'write-short-video-copy', name: '短视频文案' },
  { id: 13, slug: 'topic-explorer', name: '选题探索' },
];
function handoff(platform: string, slug = 'wechat-viral-article', conversation = ''): Handoff {
  const target = destinations.find(d => d.slug === slug)!;
  return { id: 'handoff1', topic_id: idea.id, platform, version_id: null, target_application_id: target.id, kind: slug,
    url: `/applications/${target.id}/chat?slug=${slug}&promotionApplication=1&promotionHandoff=handoff1${conversation ? `&conversation=${conversation}` : ''}`, status: '', target_id: conversation };
}
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
async function selectCategories(values: string[]) {
  const boxes = [...container.querySelectorAll<HTMLInputElement>('.promotion-material-picker input[type="checkbox"]')];
  for (const box of boxes) if (box.checked !== values.includes(box.value)) await act(async () => box.click());
}
async function render(tab = 'cases', presentation = '') {
  await act(async () => root.render(createElement(MemoryRouter, { initialEntries: [`/?tab=${tab}&${presentation}`] }, createElement(ConfigProvider, { theme: { token: { motion: false } } }, createElement(ProjectPromotionWorkspace, { base, root: '/tenant' })))));
  await settle();
}
beforeEach(() => {
  taskRows = []; handoffRows = [];
  popup = { opener: window, closed: false, location: { replace: vi.fn() }, close: vi.fn() };
  vi.spyOn(window, 'open').mockReturnValue(popup as unknown as Window);
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} })));
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
  const computed = window.getComputedStyle.bind(window); vi.spyOn(window, 'getComputedStyle').mockImplementation(el => computed(el));
  Object.keys(rows).forEach(k => delete rows[k]); Object.assign(rows, { cases: [story], topics: [idea], channels: [], feedback: [] });
  vi.mocked(api.get).mockImplementation(async (url) => {
    if (url.endsWith('/ai/tasks')) return { results: taskRows, next: null, count: taskRows.length };
    if (url.endsWith('/report')) return { publications: [], groups: { platforms: [], cases: [] }, note: '未知数据留空', unknown_source_count: 0 };
    if (url.endsWith('/integrations')) return destinations;
    if (url.endsWith('/handoffs')) return handoffRows;
    const result = rows[url.split('/').pop()!] || [];
    return { results: result, next: null, count: result.length };
  });
  vi.mocked(api.post).mockResolvedValue({ id: 'task1', kind: 'topics', status: 'failed', request: { kind: 'topics', case_ids: ['case1'] }, result: {}, error: '失败', created_at: '2026-10-14' });
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); vi.useRealTimers(); vi.restoreAllMocks(); vi.resetAllMocks(); vi.unstubAllGlobals(); });

it.each(['cases', 'topics', 'channels', 'feedback'])('only exposes materials and topics, including legacy tab=%s', async tab => {
  taskRows = [{ id: 'legacy', kind: 'review', status: 'succeeded', request: {}, result: {}, error: '', applied: false, created_at: '' }];
  await render(tab);
  expect(container.querySelector('.promotion-page.app-scroll-page')).not.toBeNull();
  expect([...container.querySelectorAll('.promotion-nav button')].map(b => b.textContent)).toEqual(['01 · 项目素材库', '02 · 选题与创作']);
  for (const text of ['发布看板', '反馈复盘', '回存', '已发布内容', '重新生成']) expect(container.textContent).not.toContain(text);
  expect(vi.mocked(api.get).mock.calls.some(([url]) => /\/(channels|feedback|report)(\/|$)/.test(url))).toBe(false);
  if (tab === 'channels' || tab === 'feedback') expect(button('新增素材')).toBeDefined();
});

it.each([
  ['wechat', '公众号', 'wechat-viral-article', 'entry=home'],
  ['xiaohongshu', '小红书', 'write-image-text-copy', 'entry=apps'],
  ['douyin', '抖音', 'write-short-video-copy', 'standalone=1'],
  ['moments', '朋友圈', 'write-image-text-copy', 'embedded=1'],
])('prepares %s in a separate creative app window', async (platform, label, slug, presentation) => {
  await render('topics', presentation);
  const transfer = handoff(platform, slug);
  vi.mocked(api.post).mockResolvedValueOnce(transfer);
  await click(`准备${label}`);
  expect(api.post).toHaveBeenCalledExactlyOnceWith('/promotion/handoffs', { topic_id: idea.id, platform });
  expect(window.open).toHaveBeenCalledExactlyOnceWith('about:blank', '_blank');
  expect(popup.opener).toBeNull();
  expect(popup.location.replace).toHaveBeenCalledExactlyOnceWith(`${transfer.url}&entry=apps&standalone=1`);
  expect(navigate).not.toHaveBeenCalled();
  expect(button('新增选题')).toBeDefined();
  expect(document.querySelector('[role="dialog"]')).toBeNull();
});

it('reopens the existing creative conversation instead of a copy editor', async () => {
  handoffRows = [handoff('wechat', 'wechat-viral-article', '42')];
  await render('topics');
  vi.mocked(api.post).mockResolvedValueOnce(handoffRows[0]);
  await click('打开公众号');
  expect(popup.location.replace).toHaveBeenCalledWith(`${handoffRows[0].url}&entry=apps&standalone=1`);
  expect(navigate).not.toHaveBeenCalled();
  expect(document.querySelector('[role="dialog"]')).toBeNull();
});

it('shows progress, prevents duplicate requests, and retains a retry path near the topic', async () => {
  await render('topics');
  let reject!: (reason: Error) => void;
  vi.mocked(api.post).mockImplementationOnce(() => new Promise((_resolve, fail) => { reject = fail; }));
  await act(async () => { button('准备公众号').click(); button('准备公众号').click(); });
  expect(api.post).toHaveBeenCalledTimes(1);
  expect(window.open).toHaveBeenCalledTimes(1);
  expect(popup.location.replace).not.toHaveBeenCalled();
  expect(button('准备公众号').className).toContain('ant-btn-loading');
  await act(async () => reject(new Error('网络失败，请重试')));
  expect(button('准备公众号').closest('article')?.querySelector('[role="alert"]')?.textContent).toContain('网络失败');
  expect(navigate).not.toHaveBeenCalled();
  expect(popup.close).toHaveBeenCalledOnce();
  vi.mocked(api.post).mockResolvedValueOnce(handoff('wechat'));
  await click('准备公众号');
  expect(api.post).toHaveBeenLastCalledWith('/promotion/handoffs', { topic_id: idea.id, platform: 'wechat' });
  expect(window.open).toHaveBeenCalledTimes(2);
  expect(popup.location.replace).toHaveBeenCalledWith(`${handoff('wechat').url}&entry=apps&standalone=1`);
  expect(navigate).not.toHaveBeenCalled();
});

it('shows a blocked-window error without preparing a handoff and allows retry', async () => {
  await render('topics');
  vi.mocked(window.open).mockReturnValueOnce(null);
  await click('准备公众号');
  expect(api.post).not.toHaveBeenCalled();
  expect(button('准备公众号').closest('article')?.querySelector('[role="alert"]')?.textContent).toContain('请允许弹出窗口后重试');
  vi.mocked(api.post).mockResolvedValueOnce(handoff('wechat'));
  await click('准备公众号');
  expect(popup.location.replace).toHaveBeenCalledWith(`${handoff('wechat').url}&entry=apps&standalone=1`);
  expect(navigate).not.toHaveBeenCalled();
});

it('explains an unavailable target app without creating a channel or opening a modal', async () => {
  const original = vi.mocked(api.get).getMockImplementation()!;
  vi.mocked(api.get).mockImplementation(async url => url.endsWith('/integrations') ? [] : original(url));
  await render('topics'); await click('准备公众号');
  expect(button('准备公众号').closest('article')?.querySelector('[role="alert"]')?.textContent).toContain('公众号爆款写作');
  expect(api.post).not.toHaveBeenCalled(); expect(navigate).not.toHaveBeenCalled();
  expect(window.open).not.toHaveBeenCalled();
});

it('explains that draft topics need review before launching an app', async () => {
  rows.topics = [{ ...idea, status: 'draft' }];
  await render('topics');
  expect(button('准备公众号').disabled).toBe(true);
  expect(button('准备公众号').closest('article')?.textContent).toContain('编辑与审核');
  await click('编辑与审核');
  expect(field('状态').value).toBe('draft');
});

async function choose(label: string, value: string) {
  const el = field(label);
  await act(async () => { el.value = value; el.dispatchEvent(new Event('change', { bubbles: true })); });
}

it.each(['entry=home', 'entry=apps', 'standalone=1', 'embedded=1'])('explores selected materials with explicit scope in %s', async presentation => {
  rows.cases = [story, { ...story, id: 'case2', title: '第二份素材' }];
  await render('topics', presentation);
  expect(button('探索选题').disabled).toBe(true);
  await checkMaterial(story.title); await checkMaterial('第二份素材');
  await choose('目标读者（可选）', '实际使用者');
  await choose('发布渠道（可选）', 'xiaohongshu');
  await choose('介绍角度（可选）', 'workflow');
  await input('本次方向与补充要求（可选）', '不做功能清单');
  const transfer = { ...handoff('xiaohongshu', 'topic-explorer'), topic_id: null };
  vi.mocked(api.post).mockResolvedValueOnce(transfer);
  await click('探索选题');
  expect(api.post).toHaveBeenCalledExactlyOnceWith('/promotion/handoffs', {
    case_ids: ['case1', 'case2'], platform: 'xiaohongshu', audience: '实际使用者', direction: '完整流程', requirements: '不做功能清单',
  });
  expect(popup.location.replace).toHaveBeenCalledWith(`${transfer.url}&entry=apps&standalone=1`);
  expect(popup.opener).toBeNull();
  expect(button('生成选题建议')).toBeDefined();
});

it('keeps material selection after exploration failure, prevents duplicates and retries', async () => {
  await render('topics'); await checkMaterial(story.title);
  let reject!: (reason: Error) => void;
  vi.mocked(api.post).mockImplementationOnce(() => new Promise((_resolve, fail) => { reject = fail; }));
  await act(async () => { button('探索选题').click(); button('探索选题').click(); });
  expect(api.post).toHaveBeenCalledTimes(1);
  expect(button('探索选题').disabled).toBe(true);
  await act(async () => reject(new Error('网络失败')));
  expect(container.textContent).toContain('网络失败');
  expect(popup.close).toHaveBeenCalledOnce();
  expect(button('探索选题').disabled).toBe(false);
  vi.mocked(api.post).mockResolvedValueOnce({ ...handoff('', 'topic-explorer'), topic_id: null });
  await click('探索选题');
  expect(vi.mocked(api.post).mock.calls[0][1]).toEqual(vi.mocked(api.post).mock.calls[1][1]);
});

it('reports missing exploration app and blocked windows without creating a handoff', async () => {
  const original = vi.mocked(api.get).getMockImplementation()!;
  vi.mocked(api.get).mockImplementation(async url => url.endsWith('/integrations') ? destinations.filter(d => d.slug !== 'topic-explorer') : original(url));
  await render('topics'); await checkMaterial(story.title); await click('探索选题');
  expect(container.textContent).toContain('没有可运行的「选题探索」');
  expect(api.post).not.toHaveBeenCalled(); expect(window.open).not.toHaveBeenCalled();
});

it('retains exploration input when the browser blocks the new window', async () => {
  await render('topics'); await checkMaterial(story.title);
  vi.mocked(window.open).mockReturnValueOnce(null);
  await click('探索选题');
  expect(container.textContent).toContain('请允许弹出窗口后重试');
  expect(api.post).not.toHaveBeenCalled();
  expect(button('探索选题').disabled).toBe(false);
});

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

it('keeps brand references out of material creation after choosing a brand for topics', async () => {
  rows.profiles = [{ id: 'brand1', application_id: 99, name: '测试品牌' }] as unknown as PromotionRecord[];
  await render();
  expect(container.textContent).not.toContain('引用品牌资料');
  expect(vi.mocked(api.get).mock.calls.some(([url]) => url.includes('/brand-library/'))).toBe(false);
  await input('开发记录或资料原文', '已实现导出功能');
  await click('02 · 选题与创作');
  expect(field('本次方向与补充要求（可选）').value).toBe('');
  await act(async () => container.querySelector<HTMLElement>('.ant-collapse-header')!.click());
  await settle();
  await act(async () => field('品牌或账号').dispatchEvent(new MouseEvent('mousedown', { bubbles: true })));
  const option = [...document.querySelectorAll<HTMLElement>('.ant-select-item-option')].find(el => el.textContent === '测试品牌');
  expect(option).toBeDefined();
  await act(async () => option!.click());
  await checkMaterial('排版演示');
  await input('本次方向与补充要求（可选）', '讲清使用价值');
  await click('生成选题建议');
  expect(api.post).toHaveBeenLastCalledWith('/promotion/ai/tasks', expect.objectContaining({ brand_reference: expect.objectContaining({ profile_id: 'brand1' }) }));
  await click('01 · 项目素材库');
  expect(container.textContent).not.toContain('引用品牌资料');
  expect(container.querySelector('[aria-label="选题生成选项"]')).toBeNull();
  expect(field('开发记录或资料原文').value).toBe('已实现导出功能');
  await click('整理为素材草稿');
  expect(api.post).toHaveBeenLastCalledWith('/promotion/ai/tasks', expect.objectContaining({ kind: 'case', instruction: '已实现导出功能', brand_reference: null }));
  await input('项目绝对路径', 'D:\\workspace\\demo');
  await click('探索项目并生成素材');
  expect(api.post).toHaveBeenLastCalledWith('/promotion/ai/tasks', expect.objectContaining({ kind: 'project', brand_reference: null }));
  await click('02 · 选题与创作');
  expect(container.textContent).toContain('引用品牌资料 · 测试品牌');
});

it.each(['case', 'project'])('clears legacy brand references when regenerating a %s task', async kind => {
  taskRows = [{ id: 'old', kind, status: 'failed', applied: false, error: '', result: {}, created_at: '2026-10-14', request: { kind, instruction: '历史素材', brand_reference: { profile_id: 'old-brand' } } }];
  await render(); await click('重新生成');
  expect(api.post).toHaveBeenLastCalledWith('/promotion/ai/tasks', expect.objectContaining({ kind, brand_reference: null }));
});

it('submits optional topic preferences and restores automatic choices', async () => {
  await render('topics'); await checkMaterial('排版演示');
  const label = '生成选题建议';
  await click(label);
  expect(vi.mocked(api.post).mock.calls.slice(-1)[0]![1]).not.toHaveProperty('topic_options');
  await choose('介绍角度（可选）', 'application_overview');
  await choose('目标读者（可选）', '开发者与技术团队');
  await choose('发布渠道（可选）', 'wechat');
  await choose('选题数量', '3');
  await input('本次方向与补充要求（可选）', '围绕编辑器介绍');
  await click(label);
  expect(api.post).toHaveBeenLastCalledWith('/promotion/ai/tasks', expect.objectContaining({
    kind: 'topics', instruction: '围绕编辑器介绍',
    topic_options: { direction: 'application_overview', audience: '开发者与技术团队', platform: 'wechat', count: 3 },
  }));
  for (const field of ['介绍角度（可选）', '目标读者（可选）', '发布渠道（可选）', '选题数量']) await choose(field, '');
  await click(label);
  expect(vi.mocked(api.post).mock.calls.slice(-1)[0]![1]).not.toHaveProperty('topic_options');
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
  await choose('介绍角度（可选）', 'workflow');
  await choose('选题数量', '3');
  vi.mocked(api.post).mockRejectedValueOnce(new Error('网络失败'));
  await click('生成选题建议');
  const first = vi.mocked(api.post).mock.calls.slice(-1)[0]![1] as Record<string, unknown>;
  expect(first.case_ids).toEqual(['case1', 'feature1']);
  expect(first.topic_options).toEqual({ direction: 'workflow', count: 3 });
  await click('生成选题建议');
  expect((vi.mocked(api.post).mock.calls.slice(-1)[0]![1] as Record<string, unknown>).request_key).toBe(first.request_key);
  await click('生成选题建议');
  expect((vi.mocked(api.post).mock.calls.slice(-1)[0]![1] as Record<string, unknown>).request_key).not.toBe(first.request_key);
  vi.mocked(api.post).mockRejectedValueOnce(new Error('网络失败'));
  await click('生成选题建议');
  const pending = vi.mocked(api.post).mock.calls.slice(-1)[0]![1] as Record<string, unknown>;
  await choose('选题数量', '5');
  await click('生成选题建议');
  const changed = vi.mocked(api.post).mock.calls.slice(-1)[0]![1] as Record<string, unknown>;
  expect(changed.topic_options).toEqual({ direction: 'workflow', count: 5 });
  expect(changed.request_key).not.toBe(pending.request_key);
});


it('retains case edits after a failed save and persists asset links', async () => {
  await render(); await click('新增素材'); await input('名称', '新场景'); await input('已实现能力', 'HTML 输出');
  await click('添加素材链接'); await input('素材 1 名称', '演示'); await input('HTTP(S) 链接', 'https://example.com/demo');
  vi.mocked(api.post).mockRejectedValueOnce(new Error('网络失败'));
  await click('保存'); expect(field('名称').value).toBe('新场景'); expect(document.body.textContent).toContain('网络失败');
  vi.mocked(api.post).mockResolvedValueOnce(story); await click('保存');
  expect(api.post).toHaveBeenLastCalledWith('/promotion/cases', expect.objectContaining({ title: '新场景', data: expect.objectContaining({ implemented: 'HTML 输出', assets: [expect.objectContaining({ url: 'https://example.com/demo' })] }) }));
});


it('uses a new request key when failed payload changes for every task kind', async () => {
  const client = promotionApi(base);
  for (const kind of ['case', 'project', 'topics']) {
    vi.mocked(api.post).mockRejectedValueOnce(new Error('network'));
    await expect(client.start({ kind, instruction: '原始' })).rejects.toThrow('network');
    const old = vi.mocked(api.post).mock.calls.slice(-1)[0]![1] as Record<string, unknown>;
    await client.start({ kind, instruction: '新的' });
    expect((vi.mocked(api.post).mock.calls.slice(-1)[0]![1] as Record<string, unknown>).request_key).not.toBe(old.request_key);
  }
});




it.each(['missing', 'throwing', 'absent'])('retains project path and retries with the same key when crypto is %s', async mode => {
  vi.stubGlobal('crypto', mode === 'absent' ? undefined : mode === 'missing' ? {} : { randomUUID: () => { throw new Error('insecure'); } });
  await render();
  expect(button('探索项目并生成素材').disabled).toBe(true);
  await input('项目绝对路径', 'D:\\workspace\\demo');
  await input('探索方向（可选）', '展示文章排版');
  await selectCategories(['deployment', 'security']);
  vi.mocked(api.post).mockRejectedValueOnce(new Error('路径不可访问'));
  await click('探索项目并生成素材');
  const first = vi.mocked(api.post).mock.calls.slice(-1)[0]![1] as Record<string, unknown>;
  expect(first).toEqual(expect.objectContaining({ kind: 'project', exploration_mode: 'overview', material_types: ['deployment', 'security'], project_path: 'D:\\workspace\\demo', instruction: '展示文章排版', request_key: expect.any(String) }));
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
  await selectCategories(['deployment', 'security']);
  await choose('探索模式', 'deep');
  expect(container.querySelector('.promotion-material-picker')).toBeNull();
  expect(button('探索项目并生成素材').disabled).toBe(true);
  await input('深入方向（必填）', '任务调度与失败恢复');
  vi.mocked(api.post).mockRejectedValueOnce(new Error('网络失败'));
  await click('探索项目并生成素材');
  const deep = vi.mocked(api.post).mock.calls.slice(-1)[0]![1] as Record<string, unknown>;
  expect(deep).toEqual(expect.objectContaining({ exploration_mode: 'deep', instruction: '任务调度与失败恢复' }));
  expect(deep).not.toHaveProperty('material_types');
  expect(deep).not.toHaveProperty('exploration_focus');
  await choose('探索模式', 'overview');
  await click('探索项目并生成素材');
  const overview = vi.mocked(api.post).mock.calls.slice(-1)[0]![1] as Record<string, unknown>;
  expect(overview.exploration_mode).toBe('overview');
  expect(overview.material_types).toEqual(['deployment', 'security']);
  expect(overview.request_key).not.toBe(deep.request_key);
});

it('opens a source-backed material as a deep exploration direction without submitting automatically', async () => {
  rows.cases = [{ ...story, data: { ...story.data, material_type: 'deployment' }, source_snapshot: { origin: { path: '/workspace/original' } } }];
  await render();
  await click('深入此方向');
  expect(field('项目绝对路径').value).toBe('/workspace/original');
  expect(field('探索模式').value).toBe('deep');
  expect(container.querySelector('.promotion-material-picker')).toBeNull();
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



it('offers only multi-select material categories and preserves retry keys until categories change', async () => {
  await render();
  const picker = container.querySelector('.promotion-material-picker')!;
  expect(picker.querySelector('legend')?.textContent).toBe('素材分类');
  const boxes = [...picker.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')];
  expect(boxes.map(box => [box.value, box.getAttribute('aria-label')])).toEqual(Object.entries(materialTypes));
  expect(boxes.filter(box => box.checked).map(box => box.value)).toEqual(['overview']);
  expect(container.textContent).not.toContain('综合视角');
  expect(container.textContent).not.toContain('探索侧重');
  for (const key of Object.keys(materialTypes)) {
    expect(picker.textContent).toContain(explorationFocusDescriptions[key]);
  }
  await input('项目绝对路径', '/workspace/project');
  await selectCategories([]);
  expect(button('探索项目并生成素材').disabled).toBe(true);
  expect(picker.textContent).toContain('请选择至少一种素材分类');
  await selectCategories(['deployment', 'roadmap']);
  vi.mocked(api.post).mockRejectedValueOnce(new Error('网络失败')).mockRejectedValueOnce(new Error('网络失败'));
  await click('探索项目并生成素材');
  const first = vi.mocked(api.post).mock.calls.slice(-1)[0]![1] as Record<string, unknown>;
  expect(first.material_types).toEqual(['deployment', 'roadmap']);
  await click('探索项目并生成素材');
  expect((vi.mocked(api.post).mock.calls.slice(-1)[0]![1] as Record<string, unknown>).request_key).toBe(first.request_key);
  await selectCategories(['deployment', 'cost']);
  await click('探索项目并生成素材');
  const next = vi.mocked(api.post).mock.calls.slice(-1)[0]![1] as Record<string, unknown>;
  expect(next.material_types).toEqual(['deployment', 'cost']);
  expect(next.exploration_mode).toBe('overview');
  expect(next.request_key).not.toBe(first.request_key);
});

it.each([
  [{ exploration_mode: 'overview', material_types: ['deployment', 'security'] }, '全面概览 · 部署运维、安全隐私'],
  [{ exploration_mode: 'overview', exploration_focus: 'technical' }, '全面概览 · 技术实现与设计'],
  [{ exploration_mode: 'deep', material_types: ['deployment'], exploration_focus: 'technical' }, '指定方向深挖 · 项目：'],
])('shows current and historical project category summaries (%j)', async (request, expected) => {
  taskRows = [{ id: 'categories-history', kind: 'project', status: 'failed', request: { ...request, project_path: '/project' }, result: {}, error: '', applied: false, created_at: '' }];
  await render();
  expect(container.querySelector('.promotion-task-section')?.textContent).toContain(expected);
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
  expect(container.querySelector('.promotion-material-picker')).toBeNull();
  expect(field('深入方向（必填）').value).toContain('项目宣传助手介绍');
  await click('编辑与审核');
  expect(field('素材类型').value).toBe('application_overview');
  await click('保存');
  expect(api.patch).toHaveBeenLastCalledWith('/promotion/cases/application-overview', expect.objectContaining({ data: expect.objectContaining({ material_type: 'application_overview' }) }));
});
