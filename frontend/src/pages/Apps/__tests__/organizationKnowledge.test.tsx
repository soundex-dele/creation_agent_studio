// @vitest-environment jsdom
import { act, useState } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '@/services/api';
import { researchApi } from '@/services/douyinResearch';
import type { KnowledgeCard, KnowledgeShare, OrganizationKnowledgeSnapshot } from '@/services/douyinKnowledge';
import { KnowledgeShareDrawer, OrganizationKnowledgePicker, OrganizationKnowledgeReferences } from '../douyin/OrganizationKnowledge';
import { CreationCenter } from '../douyin/CreationCenter';

vi.mock('@/services/api', () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } }));
const base = '/organizations/org/applications/1/douyin-benchmark';
const card: KnowledgeCard = { id: 'card1', revision: 2, title: '明确受众', text: '参考观点', application_notes: '', tags: [], category: 'content', basis: 'author_view', evidence: [], source_missing: false, index_status: 'ready', index_error: '', created_at: '', updated_at: '' };
const chunk: OrganizationKnowledgeSnapshot = { chunk_id: 7, revision: 3, document_id: 2, knowledge_base_id: 1, knowledge_base_name: '团队资料', title: '受众研究', snippet: '核对受众的真实需求', score: 1, page_number: 2, section_path: ['方法'], citation: '受众研究#chunk-0', provenance: { basis: 'author_view' } };
const shared: KnowledgeShare = { knowledge_base_id: 1, knowledge_base_name: '团队资料', is_active: true, document_id: 2, shared_revision: 1, document_deleted: false, index_status: 'ready', updated_at: '' };
let container: HTMLDivElement; let root: Root;
beforeEach(() => {
  vi.clearAllMocks(); vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  Object.defineProperty(window, 'matchMedia', { writable: true, value: vi.fn(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() })) });
  const style = window.getComputedStyle; vi.spyOn(window, 'getComputedStyle').mockImplementation(el => style(el));
  vi.mocked(api.get).mockImplementation(async url => {
    if (url.endsWith('/knowledge-bases/')) return [{ id: 1, name: '团队资料', is_active: true }];
    if (url.endsWith('/shares')) return { can_share: true, results: [] };
    if (url.includes('/knowledge-cards')) return { count: 1, results: [card] };
    return url.endsWith('/brands') ? [] : { count: 0, results: [] };
  });
  vi.mocked(api.post).mockImplementation(async url => url.endsWith('/knowledge-search/') ? { retrieval_mode: 'lexical', results: [chunk] } : { ...shared, shared_revision: 2 });
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
async function click(label: string) {
  const node = [...document.querySelectorAll<HTMLButtonElement>('button')].find(el => el.textContent?.replace(/\s/g, '') === label.replace(/\s/g, ''));
  expect(node, label).toBeDefined(); await act(async () => node!.click());
}
async function select(label: string, value: string) {
  const node = document.querySelector(`[aria-label="${label}"]`)!.closest('.ant-select')!.querySelector('.ant-select-selector')!;
  await act(async () => node.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })));
  const option = [...document.querySelectorAll<HTMLElement>('.ant-select-item-option-content')].find(el => el.textContent === value);
  expect(option).toBeDefined(); await act(async () => option!.click());
}
async function input(label: string, value: string) {
  const el = document.querySelector<HTMLInputElement | HTMLTextAreaElement>(`[aria-label="${label}"]`)!;
  await act(async () => { Object.getOwnPropertyDescriptor(el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype, 'value')!.set!.call(el, value); el.dispatchEvent(new Event('input', { bubbles: true })); });
}
async function check(label: string) {
  const node = [...document.querySelectorAll('label')].find(el => el.textContent?.includes(label))?.querySelector('input');
  expect(node).toBeDefined(); await act(async () => node!.click());
}

describe('Organization knowledge integration', () => {
  it('shares only after choosing a library, preserves retries and links the document', async () => {
    await act(async () => root.render(<KnowledgeShareDrawer client={researchApi(base)} card={card} onClose={vi.fn()}><p>分享预览</p></KnowledgeShareDrawer>));
    expect(document.body.textContent).toContain('分享后的内容对组织成员可见');
    expect(api.post).not.toHaveBeenCalled();
    await select('目标知识库', '团队资料');
    vi.mocked(api.post).mockRejectedValueOnce(new Error('网络中断'));
    await click('确认分享到组织知识库'); expect(document.body.textContent).toContain('网络中断');
    await click('确认分享到组织知识库');
    const calls = vi.mocked(api.post).mock.calls;
    expect(calls[0][1]).toEqual({ knowledge_base_id: 1, revision: 2 });
    expect(calls[0][2]?.headers?.['Idempotency-Key']).toBe(calls[1][2]?.headers?.['Idempotency-Key']);
    expect(document.querySelector('a')?.getAttribute('href')).toBe('/knowledge?base=1&document=2');
    expect(document.body.textContent).toContain('已分享当前版本');
  });

  it.each(['update', 'deleted', 'failed'])('requires an explicit action for %s', async mode => {
    const record = { ...shared, ...(mode === 'deleted' ? { document_deleted: true, index_status: 'deleted' } : mode === 'failed' ? { shared_revision: 2, index_status: 'failed' } : {}) };
    const get = vi.mocked(api.get).getMockImplementation()!;
    vi.mocked(api.get).mockImplementation(async (...args) => args[0].endsWith('/shares') ? { can_share: true, results: [record] } : get(...args));
    await act(async () => root.render(<KnowledgeShareDrawer client={researchApi(base)} card={card} onClose={vi.fn()}>预览</KnowledgeShareDrawer>));
    await click('选择此库');
    expect(api.post).not.toHaveBeenCalled();
    await click(mode === 'deleted' ? '再次分享到组织知识库' : mode === 'failed' ? '重试索引' : '更新分享');
    expect(vi.mocked(api.post).mock.calls[0][1]).toEqual({ knowledge_base_id: 1, revision: 2, ...(mode === 'deleted' && { recreate: true }) });
  });

  it('disables publication without write permission', async () => {
    const get = vi.mocked(api.get).getMockImplementation()!;
    vi.mocked(api.get).mockImplementation(async (...args) => args[0].endsWith('/shares') ? { can_share: false, results: [] } : get(...args));
    await act(async () => root.render(<KnowledgeShareDrawer client={researchApi(base)} card={card} onClose={vi.fn()}>预览</KnowledgeShareDrawer>));
    expect(document.body.textContent).toContain('需要知识库写入权限');
    await click('确认分享到组织知识库'); expect(api.post).not.toHaveBeenCalled();
  });

  it('does not preselect results, enforces the combined limit and allows removal', async () => {
    const client = researchApi(base);
    function Picker() { const [selected, setSelected] = useState<OrganizationKnowledgeSnapshot[]>([]); return <OrganizationKnowledgePicker client={client} query="受众" personalCount={9} selected={selected} onChange={setSelected} />; }
    await act(async () => root.render(<Picker />)); await click('检索组织知识库');
    await select('检索知识库', '团队资料'); await click('搜索资料');
    expect(container.textContent).toContain('合计 9 / 10');
    expect(api.post).toHaveBeenCalledWith('/organizations/org/knowledge-search/', { query: '受众', knowledge_base_ids: [1], limit: 20 });
    await check('引用 受众研究'); expect(container.textContent).toContain('合计 10 / 10');
    expect(container.textContent).toContain('第 2 页'); expect(container.textContent).toContain('作者观点');
    await check('受众研究 · 团队资料'); expect(container.textContent).toContain('合计 9 / 10');
  });

  it('submits only chunk identifiers and revisions alongside private cards', async () => {
    const run = vi.fn();
    await act(async () => root.render(<MemoryRouter initialEntries={['/?mode=topics']}><CreationCenter client={researchApi(base)} run={run} onProfiles={vi.fn()} /></MemoryRouter>));
    await input('positioning', '科普'); await input('本次主题', '受众');
    await click('推荐相关知识'); await check('使用 明确受众');
    await click('检索组织知识库'); await select('检索知识库', '团队资料'); await click('搜索资料'); await check('引用 受众研究');
    await click('生成3个创作选题');
    expect(run.mock.calls[0][0]).toMatchObject({ knowledge_cards: [{ id: 'card1', revision: 2 }], organization_knowledge_chunks: [{ chunk_id: 7, revision: 3 }] });
    expect(JSON.stringify(run.mock.calls[0][0])).not.toContain(chunk.snippet);
  });

  it('retains frozen text when the original document cannot be loaded', async () => {
    vi.mocked(api.get).mockRejectedValue(new Error('原文已移除'));
    await act(async () => root.render(<OrganizationKnowledgeReferences client={researchApi(base)} items={[chunk]} />));
    await click('查看原文');
    expect(container.textContent).toContain('原文已移除'); expect(container.textContent).toContain(chunk.snippet);
  });

  it('discards a late search response when the creation theme changes', async () => {
    const client = researchApi(base); const onChange = vi.fn();
    let resolve!: (value: unknown) => void;
    const render = (query: string) => root.render(<OrganizationKnowledgePicker client={client} query={query} personalCount={0} selected={[chunk]} onChange={onChange} />);
    await act(async () => render('旧主题')); await click('检索组织知识库'); await select('检索知识库', '团队资料');
    vi.mocked(api.post).mockImplementationOnce(() => new Promise(done => { resolve = done; }));
    await click('搜索资料');
    await act(async () => render('新主题'));
    await act(async () => resolve({ retrieval_mode: 'lexical', results: [{ ...chunk, title: '迟到结果' }] }));
    expect(container.textContent).not.toContain('迟到结果');
    expect((container.querySelector('[aria-label="检索组织资料"]') as HTMLInputElement).value).toBe('新主题');
    expect(container.textContent).toContain('受众研究 · 团队资料');
  });

  it('keeps search errors recoverable and allows continuing without selection', async () => {
    const onChange = vi.fn();
    await act(async () => root.render(<OrganizationKnowledgePicker client={researchApi(base)} query="受众" personalCount={0} selected={[]} onChange={onChange} />));
    await click('检索组织知识库'); await select('检索知识库', '团队资料');
    vi.mocked(api.post).mockRejectedValueOnce(new Error('检索失败'));
    await click('搜索资料'); expect(container.textContent).toContain('可不引用组织资料继续创作');
    await click('搜索资料'); expect(container.textContent).toContain(chunk.snippet);
    expect(onChange).not.toHaveBeenCalled();
  });
});
