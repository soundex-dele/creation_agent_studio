// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '@/services/api';
import { researchApi, citationLocation, type ResearchResult } from '@/services/researchAssistant';
import { applicationPath } from '@/lib/applicationCatalog';
import { ResearchWorkspace, highlightQuote } from '../research/ResearchWorkspace';

vi.mock('@/services/api', () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } }));
const project = { id: 'project-1', title: '行业研究', objective: '比较观点', created_at: '', updated_at: '' };
const source = { id: 's1', title: '报告 A', filename: '报告.pdf', status: 'ready', error: '', metadata: {}, origin: { type: 'upload' } };
const citation = { id: 'e1', number: 1, source_id: 's1', title: '报告 A', quote: '原文依据', chunk_id: 1, page_number: 2, paragraph_number: null, section_path: [], position: 0 };
const output = { title: '研究成果', sections: [{ heading: '关键结论', items: [{ type: 'fact' as const, text: '结论', evidence_ids: ['e1'] }] }], citations: [citation], coverage: [] };
const result: ResearchResult = { id: 'r1', kind: 'report', instruction: '', objective: project.objective, source_ids: ['s1'], run_id: 'run-1', status: 'succeeded', error: '', created_at: '', progress: null, output };
let container: HTMLDivElement; let root: Root;

beforeEach(() => {
  vi.useFakeTimers(); vi.clearAllMocks();
  const getComputedStyle = window.getComputedStyle.bind(window);
  vi.spyOn(window, 'getComputedStyle').mockImplementation((element) => getComputedStyle(element));
  Object.defineProperty(window, 'matchMedia', { writable: true, value: vi.fn().mockImplementation(() => ({ matches: true, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() })) });
  Object.defineProperty(globalThis, 'IS_REACT_ACT_ENVIRONMENT', { configurable: true, value: true });
  vi.mocked(api.get).mockImplementation(async (url) => {
    if (url.endsWith('/integrations')) return { applications: [], limits: { max_sources: 20, max_file_bytes: 52428800, max_text_bytes: 2097152 } };
    if (url.endsWith('/sources')) return [source, { ...source, id: 'pending', title: '待解析资料', status: 'indexing' }];
    if (url.endsWith('/results')) return { count: 1, results: [result] };
    if (url.endsWith('/results/r1')) return result;
    if (url.endsWith('/citations/e1')) return { ...citation, context: '前文。原文依据。后文。' };
    return project;
  });
  vi.mocked(api.patch).mockResolvedValue(project);
  vi.mocked(api.post).mockResolvedValue({ ...result, status: 'queued', output: null });
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); vi.useRealTimers(); vi.restoreAllMocks(); });

const render = async (resultId: string | null = null, citationId: string | null = null) => {
  const navigate = vi.fn();
  await act(async () => { root.render(<MemoryRouter><ResearchWorkspace client={researchApi('/research')} projectId={project.id} resultId={resultId} citationId={citationId} navigate={navigate} onChange={vi.fn()} /></MemoryRouter>); });
  return navigate;
};

describe('research workspace', () => {
  it('registers a dedicated application route', () => {
    expect(applicationPath({ id: 'research-assistant', applicationId: 42, rendererKey: 'research-assistant', kind: 'custom' }, 'apps')).toBe('/applications/42/research-assistant?entry=apps');
  });
  it('selects only ready sources and saves the objective before generation', async () => {
    const navigate = await render();
    const button = [...container.querySelectorAll('button')].find((b) => b.textContent?.includes('基于 1 份资料生成'));
    expect(button).toBeDefined();
    expect(container.textContent).toContain('待解析资料');
    await act(async () => button!.click());
    expect(api.patch).toHaveBeenCalledWith('/research/projects/project-1', { title: project.title, objective: project.objective });
    expect(api.post).toHaveBeenCalledWith('/research/projects/project-1/results', { source_ids: ['s1'], kind: 'report', instruction: '' }, expect.objectContaining({ headers: { 'Idempotency-Key': expect.any(String) } }));
    expect(navigate).toHaveBeenCalledWith(project.id, result.id);
  });
  it('restores a historical result and opens citations by stable identity', async () => {
    const navigate = await render('r1');
    expect(container.textContent).toContain('研究成果');
    const link = container.querySelector<HTMLButtonElement>('button[aria-label="查看出处 1"]');
    expect(link).not.toBeNull();
    await act(async () => link!.click());
    expect(navigate).toHaveBeenCalledWith(project.id, 'r1', 'e1');
  });
  it('loads a linked citation, preserving original text and page location', async () => {
    await render('r1', 'e1');
    expect(document.body.textContent).toContain('第 2 页');
    expect(document.body.querySelector('mark')?.textContent).toBe('原文依据');
    expect(document.body.textContent).toContain('前文。原文依据。后文。');
  });
  it('keeps user-deselected ready sources deselected after refresh', async () => {
    await render();
    const checkbox = container.querySelector<HTMLInputElement>('input[type="checkbox"]');
    expect(checkbox?.checked).toBe(true);
    await act(async () => checkbox!.click());
    await act(async () => { await vi.advanceTimersByTimeAsync(4000); });
    expect(checkbox?.checked).toBe(false);
    expect(container.textContent).toContain('基于 0 份资料生成');
  });
  it('renders quote text as text instead of executing HTML', async () => {
    await act(async () => root.render(<p>{highlightQuote('<script>bad()</script>', 'bad()')}</p>));
    expect(container.querySelector('script')).toBeNull();
    expect(container.querySelector('mark')?.textContent).toBe('bad()');
    expect(citationLocation({ ...citation, page_number: null, paragraph_number: 3, section_path: ['价格'] })).toBe('价格 / 第 3 段');
  });
});
