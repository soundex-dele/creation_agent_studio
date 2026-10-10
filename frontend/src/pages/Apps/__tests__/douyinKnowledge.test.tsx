// @vitest-environment jsdom
import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '@/services/api';
import { researchApi, type ResearchTask } from '@/services/douyinResearch';
import type { KnowledgeCard, KnowledgeSnapshot } from '@/services/douyinKnowledge';
import { ExtractKnowledge, KnowledgeCandidates, KnowledgeLibrary, KnowledgePicker, KnowledgeReferences } from '../douyin/CreationKnowledge';
import { CreationCenter } from '../douyin/CreationCenter';

vi.mock('@/services/api', () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } }));
const card: KnowledgeCard = {
  id: 'card1', revision: 1, title: '明确受众', text: '围绕真实问题组织内容', application_notes: '口播选题', tags: ['口播'], category: 'content', basis: 'author_view',
  evidence: [{ ref: 'source:s1', task_id: 'source', work_id: 'w1', account_id: 'a1', account_name: '对标账号', title: '原作品', url: 'https://www.douyin.com/video/123', kind: 'segment', text: '先明确受众的问题', start: 0, end: 4 }],
  source_missing: false, index_status: 'ready', index_error: '', created_at: '', updated_at: '',
};
const candidate = { ...card, candidate_id: 'card-1' };
const task: ResearchTask = { id: 'extract1', kind: 'knowledge_extract', status: 'succeeded', stage: 'completed', error: '', output: { cards: [candidate] }, progress: {}, sources: [], work_id: null, run_id: 'run1', created_at: '' };
let container: HTMLDivElement; let root: Root;
beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  Object.defineProperty(window, 'matchMedia', { writable: true, value: vi.fn(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() })) });
  const getStyle = window.getComputedStyle; vi.spyOn(window, 'getComputedStyle').mockImplementation(el => getStyle(el));
  vi.mocked(api.get).mockImplementation(async url => url.endsWith('/brands') ? [] : url.includes('knowledge-cards') ? { results: [card], count: 1 } : { results: [], count: 0 });
  vi.mocked(api.post).mockResolvedValue({ cards: [card] });
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
async function click(label: string) {
  const target = [...document.querySelectorAll<HTMLElement>('button')].find(el => el.textContent?.replace(/\s/g, '') === label.replace(/\s/g, ''));
  expect(target, label).toBeDefined(); await act(async () => target!.click());
}
async function input(label: string, value: string) {
  const el = document.querySelector<HTMLInputElement | HTMLTextAreaElement>(`[aria-label="${label}"]`)!;
  expect(el).not.toBeNull();
  await act(async () => { Object.getOwnPropertyDescriptor(el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype, 'value')!.set!.call(el, value); el.dispatchEvent(new Event('input', { bubbles: true })); });
}
async function check(label: string) {
  const el = [...document.querySelectorAll('label')].find(el => el.textContent?.includes(label))?.querySelector('input');
  expect(el).toBeDefined(); await act(async () => el!.click());
}

describe('Creative knowledge workflow', () => {
  it('edits candidate text, preserves evidence and confirms only selected cards', async () => {
    await act(async () => root.render(<KnowledgeCandidates client={researchApi('/dy')} task={task} />));
    expect(api.post).not.toHaveBeenCalled();
    await click('编辑'); await input('知识正文', '编辑后的可复用知识'); await click('保存卡片');
    await check('选择 明确受众'); await click('确认入库（1）');
    expect(api.post).toHaveBeenCalledWith('/dy/knowledge-cards/confirm', expect.objectContaining({ task_id: 'extract1', cards: [expect.objectContaining({ candidate_id: 'card-1', text: '编辑后的可复用知识' })] }), expect.anything());
    expect(container.textContent).toContain('已入库 1 张');
    expect(container.textContent).toContain('先明确受众的问题');
    const payload = vi.mocked(api.post).mock.calls[0][1] as { cards: object[] };
    expect(payload.cards[0]).not.toHaveProperty('evidence');
  });

  it('keeps an uncertain confirmation retryable with the same request key', async () => {
    vi.mocked(api.post).mockRejectedValueOnce(new Error('Network Error'));
    await act(async () => root.render(<KnowledgeCandidates client={researchApi('/dy')} task={task} />));
    await check('选择 明确受众'); await click('确认入库（1）');
    expect(container.textContent).not.toContain('已入库 1 张');
    await click('确认入库（1）');
    const calls = vi.mocked(api.post).mock.calls;
    expect(calls[0][2]?.headers?.['Idempotency-Key']).toBe(calls[1][2]?.headers?.['Idempotency-Key']);
  });

  it('does not preselect recommendations and retains selection when the query changes', async () => {
    const client = researchApi('/dy');
    function Picker({ query }: { query: string }) {
      const [selected, setSelected] = useState<KnowledgeSnapshot[]>([]);
      return <KnowledgePicker client={client} query={query} selected={selected} onChange={setSelected} />;
    }
    await act(async () => root.render(<Picker query="科普" />)); await click('推荐相关知识');
    expect(container.textContent).toContain('已选 0 / 10');
    await check('使用 明确受众');
    await act(async () => root.render(<Picker query="美食" />));
    expect(container.textContent).toContain('已选 1 / 10'); expect(container.textContent).toContain('推荐待刷新');
  });

  it('passes only explicitly selected card revisions to topic generation', async () => {
    const run = vi.fn().mockResolvedValue(undefined);
    await act(async () => root.render(<CreationCenter client={researchApi('/dy')} initialIdea={null} run={run} onProfiles={() => {}} />));
    await input('positioning', '科普'); await input('theme', '受众研究');
    await click('生成3个创作选题'); expect(run.mock.calls[0][0]).not.toHaveProperty('knowledge_cards');
    await click('推荐相关知识'); await check('使用 明确受众'); await click('生成3个创作选题');
    expect(run.mock.calls[1][0].knowledge_cards).toEqual([{ id: 'card1', revision: 1 }]);
    expect(run.mock.calls[1][0]).not.toHaveProperty('evidence');
  });

  it('offers extraction only for finished supported analysis and keeps failures visible', async () => {
    const run = vi.fn().mockRejectedValue(new Error('缺少有效正文'));
    await act(async () => root.render(<ExtractKnowledge task={{ ...task, kind: 'breakdown' }} run={run} />));
    await click('提炼知识'); expect(run).toHaveBeenCalledWith({ kind: 'knowledge_extract', source_task_id: task.id });
    expect(container.textContent).toContain('缺少有效正文');
    await act(async () => root.render(<ExtractKnowledge task={{ ...task, kind: 'breakdown', status: 'running' }} run={run} />));
    expect(container.querySelector('button')).toBeNull();
  });

  it('clears selected knowledge when switching creation profiles', async () => {
    vi.mocked(api.get).mockImplementation(async url => {
      if (url.endsWith('/creator-profiles')) return { count: 2, results: [
        { id: 'profile1', name: '账号甲', positioning: '科普', audience: '新手', is_default: true },
        { id: 'profile2', name: '账号乙', positioning: '美食', audience: '家长' },
      ] };
      if (url.includes('knowledge-cards')) return { count: 1, results: [card] };
      return url.endsWith('/brands') ? [] : { count: 0, results: [] };
    });
    await act(async () => root.render(<CreationCenter client={researchApi('/dy')} initialIdea={null} run={vi.fn()} onProfiles={() => {}} />));
    await click('推荐相关知识'); await check('使用 明确受众');
    const selector = document.querySelector('[aria-label="创作档案"]')!.closest('.ant-select')!.querySelector('.ant-select-selector')!;
    await act(async () => selector.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })));
    const option = [...document.querySelectorAll<HTMLElement>('.ant-select-item-option-content')].find(el => el.textContent === '账号乙');
    expect(option).toBeDefined(); await act(async () => option!.click());
    expect(container.textContent).toContain('已选 0 / 10');
    expect(container.textContent).not.toContain('明确受众 · v1');
  }, 15000);

  it('shows frozen references, missing sources and failed index recovery', async () => {
    vi.mocked(api.get).mockResolvedValue({ count: 1, results: [{ ...card, source_missing: true, index_status: 'failed' }] });
    await act(async () => root.render(<><KnowledgeReferences cards={[card]} /><KnowledgeLibrary client={researchApi('/dy')} /></>));
    expect(container.textContent).toContain('本次参考知识（1）'); expect(container.textContent).toContain('来源已移除');
    await click('重试索引'); expect(api.post).toHaveBeenCalledWith('/dy/knowledge-cards/card1/retry-index');
  });
});
