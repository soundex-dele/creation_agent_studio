// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '@/services/api';
import { OwnedAccounts } from '../douyin/OwnedAccounts';
import { researchTaskStatus } from '@/services/douyinResearch';
import type { CreatorProfile, ResearchTask, VoiceContent, VoiceVersion } from '@/services/douyinResearch';

vi.mock('@/services/api', () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } }));
const content: VoiceContent = { current_positioning: '旧定位', positioning: '实验科普', audience: '好奇的观众', content_pillars: '日常实验', content_boundaries: '不编造', rules: '先讲困惑', examples: '我做过一个小实验。', avoid: '空话', prompt: '用我的实验经历解释问题，不编造事实。' };
const accounts = ['a1', 'a2'].map((id, i) => ({ id, name: i ? '我的美食号' : '我的科普号', is_owned: true, source_url: `https://www.douyin.com/user/${id}`, profile: {}, notes: '', group: '' }));
let profiles: CreatorProfile[]; let tasks: ResearchTask[]; let versions: VoiceVersion[];
let container: HTMLDivElement; let root: Root;
const page = (results: unknown[]) => ({ count: results.length, results });
const samples = [{ id: 's1', profile: 'p1', revision: 1, title: '我的实验', text: '我做过一个小实验。', usage: 'style', work: null, source_task: null, source_url: '', source_missing: false }];
function task(kind: string, output: ResearchTask['output']): ResearchTask { return { id: `t-${kind}`, kind, status: 'succeeded', stage: 'completed', output, error: '', sources: [], work_id: null, run_id: 'r', progress: {}, created_at: '2026-10-09T00:00:00Z' }; }
beforeEach(() => {
  vi.clearAllMocks(); versions = []; tasks = [];
  profiles = accounts.map((a, i) => ({ id: `p${i + 1}`, name: a.name, account: a.id, revision: 1, positioning: '', audience: '', experiences: '', products: '', voice: '', conditions: '', is_default: false, created_at: '', updated_at: '', shared_inspiration_ids: [] }));
  Object.defineProperty(globalThis, 'IS_REACT_ACT_ENVIRONMENT', { configurable: true, value: true });
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() })));
  const original = window.getComputedStyle; vi.spyOn(window, 'getComputedStyle').mockImplementation(el => original(el));
  vi.mocked(api.get).mockImplementation(async (url, params) => {
    if (url === '/dy/accounts') return page(accounts);
    if (url.endsWith('/creator-profiles')) return page(profiles);
    if (url.endsWith('/voice-samples')) return page(params?.profile === 'p1' ? samples : []);
    if (url.endsWith('/voice-versions')) return versions;
    if (url === '/dy/tasks') return page(params?.target_account === 'a1' ? tasks : []);
    return page([]);
  });
  vi.mocked(api.post).mockImplementation(async (url, body) => {
    const data = body as Record<string, unknown>;
    if (url.endsWith('/voice-versions')) {
      versions = [{ id: 'v1', number: 1, profile: 'p1', content: data.content as VoiceContent, evidence: [], source_task: null, created_at: '' }];
      profiles[0] = { ...profiles[0], revision: 2, active_version: 'v1', active_version_number: 1 };
      return { version: versions[0], revision: 2 };
    }
    if (url === '/dy/tasks') {
      const value = data.kind === 'voice_analysis' ? task('voice_analysis', { content, voice_evidence: [], findings: [], warning: '初步分析' }) : task('topics', { topics: [{ title: '实验主题', angle: '日常现象', hook: '试过吗', pillar: '实验', reason: '适合定位', materials_needed: '真实过程', duplicate_note: '仅覆盖已采集样本' }], creation_context: { account_name: '我的科普号', voice_version_number: 1 } });
      tasks = [value, ...tasks]; return value;
    }
    return {};
  });
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
async function render() { await act(async () => root.render(<MemoryRouter initialEntries={['/?view=owned&owned=a1']}><OwnedAccounts base="/dy" openAccount={vi.fn()} /></MemoryRouter>)); }
async function click(text: string) { const el = [...document.querySelectorAll<HTMLElement>('button,[role="tab"]')].find(el => el.textContent === text); expect(el, text).toBeDefined(); await act(async () => el!.click()); }
async function changeAccount(name: string) {
  const input = container.querySelector('[aria-label="当前创作账号"]')!;
  await act(async () => input.closest('.ant-select')!.querySelector('.ant-select-selector')!.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })));
  const option = [...document.querySelectorAll<HTMLElement>('.ant-select-item-option-content')].find(el => el.textContent === name);
  expect(option).toBeDefined(); await act(async () => option!.click());
}

describe('owned account workflow', () => {
  it('writes the selected topic as an article and opens its saved body', async () => {
    const post = vi.mocked(api.post).getMockImplementation()!;
    const get = vi.mocked(api.get).getMockImplementation()!;
    const written = { title: '我的文章', body: '先讲一个真实的问题。\n\n再把观点说清楚。', notes: [] };
    vi.mocked(api.get).mockImplementation(async (url, params, config) => url.endsWith('/tasks/t-article/versions')
      ? [{ id: 'article-v1', revision: 1, content: written, created_at: '' }] : get(url, params, config));
    vi.mocked(api.post).mockImplementation(async (url, body, config) => {
      if ((body as Record<string, unknown>).kind === 'article') { const value = task('article', written); tasks = [value, ...tasks]; return value; }
      if (url.endsWith('/tasks/t-article/versions')) return { id: 'article-v2', revision: 2, content: (body as Record<string, unknown>).content, created_at: '' };
      return post(url, body, config);
    });
    await render(); await click('2 · 分析定位与文风'); await click('分析有效样本的定位与文风');
    await click('编辑分析结果并确认'); await click('确认并启用新版本');
    await click('4 · 按账号创作'); await click('生成3个账号专属选题'); await click('开始写作');
    expect(api.post).toHaveBeenCalledWith('/dy/tasks', { kind: 'article', source_task_id: 't-topics', topic_index: 0, target_account_id: 'a1' }, expect.any(Object));
    expect(container.querySelector<HTMLTextAreaElement>('[aria-label="文章正文"]')?.value).toBe(written.body);
    expect(container.textContent).toContain('复制正文');
    expect(container.textContent).not.toContain('分镜与拍摄');
    const editor = container.querySelector<HTMLTextAreaElement>('[aria-label="文章正文"]')!;
    await act(async () => { Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(editor, '我修改后的真实表达。'); editor.dispatchEvent(new Event('input', { bubbles: true })); });
    expect(container.textContent).toContain('有未保存的文章修改');
    await click('保存文章新版本');
    expect(api.post).toHaveBeenCalledWith('/dy/tasks/t-article/versions', { revision: 1, content: { ...written, body: '我修改后的真实表达。' } });
    expect(container.textContent).toContain('文章已保存为新版本');
  });
  it.each([
    ['queued', 'queued', '排队中'],
    ['running', 'queued', '正在执行'],
    ['running', '分析账号定位与文风', '分析账号定位与文风'],
    ['succeeded', 'queued', '已完成'],
    ['failed', 'queued', '失败'],
    ['cancelled', 'queued', '已取消'],
  ])('displays run status %s even if the stage is %s', (status, stage, expected) => {
    expect(researchTaskStatus({ status, stage })).toBe(expected);
  });
  it('polls a running analysis through completion instead of leaving queued on screen', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
    try {
      const running = { ...task('voice_analysis', {}), status: 'running', stage: 'queued' };
      vi.mocked(api.post).mockImplementation(async () => { tasks = [running]; return running; });
      await render(); await click('2 · 分析定位与文风'); await click('分析有效样本的定位与文风');
      expect(container.textContent).toContain('正在执行');
      expect(container.querySelector('[role="status"]')?.textContent).not.toContain('queued');
      tasks = [{ ...running, progress: { ai_preview: { text: '{"content":{"positioning":"正在形成的账号定位', state: 'receiving' } } }];
      await act(async () => { await vi.advanceTimersByTimeAsync(2500); });
      expect(container.textContent).toContain('正在形成的账号定位');
      expect(container.textContent).not.toContain('编辑分析结果并确认');
      tasks = [task('voice_analysis', { content, findings: [], voice_evidence: [] })];
      await act(async () => { await vi.advanceTimersByTimeAsync(2500); });
      expect(container.textContent).toContain('已完成');
      expect(container.textContent).toContain('编辑分析结果并确认');
      expect(container.querySelector('[aria-label="AI 生成预览"]')).toBeNull();
    } finally { vi.useRealTimers(); }
  });
  it('recovers automatically after a transient task polling failure', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
    try {
      await render(); await click('2 · 分析定位与文风');
      const get = vi.mocked(api.get).getMockImplementation()!;
      let fail = true;
      vi.mocked(api.get).mockImplementation(async (url, params, config) => {
        if (url === '/dy/tasks' && fail) { fail = false; throw new Error('Network Error'); }
        return get(url, params, config);
      });
      await click('分析有效样本的定位与文风');
      expect(container.textContent).toContain('任务状态刷新失败，正在重试');
      await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
      expect(container.textContent).not.toContain('任务状态刷新失败');
      expect(container.textContent).toContain('已完成');
    } finally { vi.useRealTimers(); }
  });
  it('imports an image caption and never starts a video transcription', async () => {
    const get = vi.mocked(api.get).getMockImplementation()!;
    let imported = false;
    const caption = '第一段自己的观点。\n第二段详细表达。';
    vi.mocked(api.get).mockImplementation(async (url, params, config) => {
      if (url === '/dy/works') return page([{ id: 'image-work', title: '图文作品', kind: 'image_album', description: caption }]);
      if (url === '/dy/voice-samples') return page(imported ? [{ ...samples[0], text: caption, work: 'image-work', work_kind: 'image_album' }] : []);
      return get(url, params, config);
    });
    vi.mocked(api.post).mockImplementation(async url => {
      expect(url).toBe('/dy/voice-samples'); imported = true;
      return { ...samples[0], text: caption, work: 'image-work', work_kind: 'image_album' };
    });
    await render(); await click('作为样本添加');
    expect(container.textContent).toContain(caption);
    expect(container.textContent).toContain('不含图片内文字识别');
    expect(container.textContent).not.toContain('重新转写');
    expect(api.post).toHaveBeenCalledTimes(1);
  });
  it('offers caption recovery for older empty image samples instead of transcription', async () => {
    const get = vi.mocked(api.get).getMockImplementation()!;
    let recovered = false;
    vi.mocked(api.get).mockImplementation(async (url, params, config) => url === '/dy/voice-samples'
      ? page([{ ...samples[0], text: recovered ? '已恢复发布文案' : '', work: 'image-work', work_kind: 'image_album' }]) : get(url, params, config));
    vi.mocked(api.patch).mockImplementation(async () => { recovered = true; return {}; });
    await render();
    expect(container.textContent).not.toContain('重新转写');
    await click('补充已采集发布文案');
    expect(api.patch).toHaveBeenCalledWith('/dy/voice-samples/s1', { revision: 1, import_caption: true });
    expect(container.textContent).toContain('已恢复发布文案');
  });
  it('does not run analysis on opening and isolates samples when switching accounts', async () => {
    await render(); expect(container.textContent).toContain('我的实验'); expect(api.post).not.toHaveBeenCalled();
    await changeAccount('我的美食号');
    expect(container.textContent).not.toContain('我的实验');
    expect(api.get).toHaveBeenCalledWith('/dy/voice-samples', expect.objectContaining({ profile: 'p2' }));
    expect(api.get).toHaveBeenCalledWith('/dy/tasks', expect.objectContaining({ target_account: 'a2' }));
  });
  it.each(['missing', 'throwing', 'absent'])('analyzes, confirms and creates with crypto %s', async mode => {
    vi.stubGlobal('crypto', mode === 'absent' ? undefined : mode === 'missing' ? {} : { randomUUID: () => { throw new Error('HTTP'); } });
    await render(); await click('2 · 分析定位与文风');
    await click('分析有效样本的定位与文风');
    expect(api.post).toHaveBeenCalledWith('/dy/tasks', { kind: 'voice_analysis', target_account_id: 'a1' }, expect.objectContaining({ headers: { 'Idempotency-Key': expect.any(String) } }));
    expect(container.textContent).toContain('初步分析'); await click('编辑分析结果并确认');
    await click('确认并启用新版本');
    expect(api.post).toHaveBeenCalledWith('/dy/creator-profiles/p1/voice-versions', { revision: 1, content, source_task_id: 't-voice_analysis' });
    await click('4 · 按账号创作'); await click('生成3个账号专属选题');
    expect(api.post).toHaveBeenCalledWith('/dy/tasks', expect.objectContaining({ target_account_id: 'a1', theme: '', kind: 'topics' }), expect.any(Object));
    expect(container.textContent).toContain('实验主题'); expect(container.textContent).toContain('适合定位'); expect(container.textContent).toContain('文风 v1');
  });
  it('keeps the sample on failed submission and reuses the key until success', async () => {
    await render(); await click('2 · 分析定位与文风');
    vi.mocked(api.post).mockRejectedValueOnce(new Error('Network Error'));
    await click('分析有效样本的定位与文风');
    const key = vi.mocked(api.post).mock.calls[0][2]?.headers?.['Idempotency-Key'];
    await click('分析有效样本的定位与文风');
    expect(vi.mocked(api.post).mock.calls[1][2]?.headers?.['Idempotency-Key']).toBe(key);
    await click('分析有效样本的定位与文风');
    expect(vi.mocked(api.post).mock.calls[2][2]?.headers?.['Idempotency-Key']).not.toBe(key);
  });
  it('asks before discarding an unsaved sample on account switch', async () => {
    await render(); await click('粘贴自己的文案'); await changeAccount('我的美食号');
    expect(document.body.textContent).toContain('有未保存的编辑');
    await click('返回编辑'); expect(document.body.textContent).toContain('样本文案与用途');
  });
});
