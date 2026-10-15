// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { ConfigProvider } from 'antd';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '@platform/http';
import type { RepoDetail, RepoTask } from '../../services/repoExplainer';
import RepoExplainerPage from '../RepoExplainerPage';

vi.mock('@/services/api', () => ({ api: { get: vi.fn(), post: vi.fn() } }));
vi.mock('@/stores/useOrganizationStore', () => ({ useOrganizationStore: (select: (s: unknown) => unknown) => select({ currentOrganizationId: 'org' }) }));
vi.mock('@/stores/useAuthStore', () => ({ useAuthStore: (select: (s: unknown) => unknown) => select({ user: { id: 'user' } }) }));
vi.mock('@/features/run-stream/index', () => ({ useRunStream: () => ({ state: {}, connected: false, error: null }) }));
vi.setConfig({ testTimeout: 30000, hookTimeout: 30000 });
let root: Root;
let container: HTMLDivElement;
let detail: RepoDetail;
let location = '';
let mount = 0;
const topicTask = (id = 'topics-1', status = 'succeeded'): RepoTask => ({
  id, kind: 'topics', status, snapshot_id: 's1', created_at: '2026-10-10T00:00:00Z', error: '', progress: {}, options: { direction: '资料问答' },
  output: { topics: Array.from({ length: 5 }, (_, index) => ({ id: `t${index + 1}`, title: `选题 ${index + 1}`, angle: '资料研究中的提问',
    audience: '研究人员', outline: ['阅读资料', '核对源码'], evidence_ids: ['e1'], notes: ['运行效果待核实'] })),
    evidence: { e1: { id: 'e1', path: 'app.py', start: 1, end: 2, quote: 'def search(): pass' } },
    coverage: { files_read: 1, files_total: 2, chunks_read: 1, chunks_total: 2, incomplete: true, note: '静态读取' } },
});
function Location() { location = useLocation().search; return null; }
const render = (query = 'project=p&view=topics&entry=home&embedded=1&standalone=1') => act(async () => {
  root.render(<MemoryRouter key={++mount} initialEntries={[`/applications/7/repo-explainer?${query}`]}>
    <ConfigProvider theme={{ token: { motion: false } }}><Location /><Routes><Route path="/applications/:applicationId/repo-explainer" element={<RepoExplainerPage />} /></Routes></ConfigProvider>
  </MemoryRouter>);
});
const button = (label: string) => [...container.querySelectorAll<HTMLButtonElement>('button')].find(el => el.textContent?.replace(/\s/g, '') === label)!;
const click = (element: HTMLElement) => act(async () => element.click());
const tab = (label: string) => click([...container.querySelectorAll<HTMLElement>('[role="tab"]')].find(el => el.textContent === label)!);
const select = async (label: string, option: string) => {
  await act(async () => container.querySelector(`[aria-label="${label}"]`)!.closest('.ant-select')!.querySelector('.ant-select-selector')!
    .dispatchEvent(new MouseEvent('mousedown', { bubbles: true })));
  await click([...document.querySelectorAll<HTMLElement>('.ant-select-item-option-content')].find(el => el.textContent === option)!);
};
beforeEach(() => {
  vi.useFakeTimers(); vi.resetAllMocks();
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() })));
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
  const computed = window.getComputedStyle.bind(window);
  vi.spyOn(window, 'getComputedStyle').mockImplementation(element => computed(element));
  detail = { id: 'p', title: '示例仓库', archived: false, updated_at: '', contents: [], handoffs: [], limits: {}, tasks: [],
    snapshots: ['s1', 's2'].map(id => ({ id, status: 'ready', origin: { kind: 'zip', filename: id }, created_at: '2026-10-10T00:00:00Z', digest: id, error: '', coverage: {} })) };
  vi.mocked(api.get).mockImplementation(async url => {
    if (url.endsWith('/projects')) return [{ id: 'p', title: '示例仓库' }, { id: 'p2', title: '另一项目' }];
    if (url.endsWith('/integrations')) return [];
    if (url.includes('/evidence')) return { text: 'def search(): pass', source_url: '' };
    if (url.includes('/tasks/')) throw new Error('批次不存在');
    return structuredClone(detail);
  });
  vi.mocked(api.post).mockImplementation(async (url, body) => {
    if (url.endsWith('/cancel')) { detail.tasks[0].status = 'cancelled'; return {}; }
    const values = body as Record<string, unknown>;
    const task = values.kind === 'topics' ? { ...topicTask(`topics-${detail.tasks.length + 1}`, 'queued'), options: values, output: {} }
      : { ...topicTask(`write-${detail.tasks.length + 1}`, 'queued'), kind: 'write', options: values, output: {} };
    detail.tasks.unshift(task); return structuredClone(task);
  });
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount()); container.remove();
  vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals();
});

describe('snapshot → optional direction → topics → copy', () => {
  it.each(['missing', 'throwing', 'absent'])('runs without analysis and survives HTTP crypto %s', async mode => {
    vi.stubGlobal('crypto', mode === 'absent' ? undefined : mode === 'missing' ? {} : { randomUUID: () => { throw new Error('HTTP'); } });
    await render();
    if (mode !== 'missing') await act(async () => {
      const input = container.querySelector<HTMLTextAreaElement>('#repo-topic-direction')!;
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(input, '资料问答');
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });
    vi.mocked(api.post).mockRejectedValueOnce(new Error('network'));
    await click(button('生成5个选题'));
    await click(button('生成5个选题'));
    const calls = vi.mocked(api.post).mock.calls;
    expect(calls[0][1]).toEqual({ kind: 'topics', snapshot_id: 's1', direction: mode === 'missing' ? '' : '资料问答' });
    expect(calls[0][2]?.headers?.['Idempotency-Key']).toBe(calls[1][2]?.headers?.['Idempotency-Key']);
    expect(container.textContent).toContain('选题正在生成');
    detail.tasks[0] = { ...topicTask(), options: detail.tasks[0].options };
    await act(async () => { await vi.advanceTimersByTimeAsync(2600); });
    expect(container.querySelectorAll('.repo-topic-card')).toHaveLength(5);
    await click(button('用此选题写文案'));
    expect(location).toContain('topic=t1'); expect(location).toContain('topics=topics-1');
    for (const param of ['entry=home', 'embedded=1', 'standalone=1']) expect(location).toContain(param);
    await click(button('生成文案'));
    expect(calls[2][1]).toMatchObject({ kind: 'write', topic_task_id: 'topics-1', topic_id: 't1', output: 'video', audience: '研究人员' });
    expect(calls[2][1]).not.toHaveProperty('analysis_id');
    await select('文案类型', '图文文案');
    await click(button('生成文案'));
    expect(calls[3][1]).toMatchObject({ output: 'image_text', topic_id: 't1' });
    await tab('选题策划');
    await click(button('生成5个选题'));
    expect(calls[4][2]?.headers?.['Idempotency-Key']).not.toBe(calls[1][2]?.headers?.['Idempotency-Key']);
    expect(location).toContain('topics=topics-1'); expect(location).toContain('topic=t1');
  });

  it('restores an exact historical selection and does not replace it with a newer batch', async () => {
    detail.tasks = [topicTask('new'), topicTask('old')];
    await render('project=p&view=content&topics=old&topic=t4&snapshot=s1');
    expect(container.querySelector('.repo-selected-topic')?.textContent).toContain('选题 4');
    await click(button('生成文案'));
    expect(vi.mocked(api.post).mock.calls[0][1]).toMatchObject({ topic_task_id: 'old', topic_id: 't4' });
    const url = location.slice(1); await render(url);
    expect(container.querySelector('.repo-selected-topic')?.textContent).toContain('选题 4');
    await tab('选题策划');
    await select('历史选题批次', `${new Date('2026-10-10T00:00:00Z').toLocaleString()} · 资料问答`);
    expect(location).not.toContain('topic=t4');
  });

  it('loads a pinned historical task beyond the recent task list', async () => {
    const original = vi.mocked(api.get).getMockImplementation()!;
    vi.mocked(api.get).mockImplementation((...args) => args[0].endsWith('/tasks/old') ? Promise.resolve(topicTask('old')) : original(...args));
    await render('project=p&view=content&topics=old&topic=t2');
    expect(container.querySelector('.repo-selected-topic')?.textContent).toContain('选题 2');
  });

  it.each(['unknown-task', 'unknown-topic', 'snapshot-mismatch'])('blocks %s without silently using the latest topic', async problem => {
    detail.tasks = [topicTask()];
    await render(`project=p&view=content&topics=${problem === 'unknown-task' ? 'missing' : 'topics-1'}&topic=${problem === 'unknown-topic' ? 't99' : 't1'}&snapshot=${problem === 'snapshot-mismatch' ? 's2' : 's1'}`);
    expect(button('生成文案').disabled).toBe(true);
    expect(container.textContent).toContain('所选选题不可用');
    expect(api.post).not.toHaveBeenCalled();
  });

  it('clears selected topics when switching snapshots or projects', async () => {
    detail.tasks = [topicTask()];
    await render('project=p&view=topics&topics=topics-1&topic=t1&snapshot=s1&entry=apps');
    const snapshotOptions = detail.snapshots.map(s => `${new Date(s.created_at).toLocaleString()} · ${s.origin.kind} · ${s.status}`);
    // Both snapshots have the same display timestamp; select the second option explicitly.
    await act(async () => container.querySelector('[aria-label="选题源码快照"]')!.closest('.ant-select')!.querySelector('.ant-select-selector')!
      .dispatchEvent(new MouseEvent('mousedown', { bubbles: true })));
    await click([...document.querySelectorAll<HTMLElement>('.ant-select-item-option-content')].filter(el => el.textContent === snapshotOptions[1])[1]);
    expect(location).toContain('snapshot=s2'); expect(location).not.toContain('topic='); expect(location).not.toContain('topics=');
    await render('project=p&view=topics&topics=topics-1&topic=t1&snapshot=s1&entry=apps');
    await select('当前项目', '另一项目');
    expect(location).toContain('project=p2'); expect(location).not.toContain('topic='); expect(location).toContain('entry=apps');
  });

  it('shows failed topic progress and allows cancellation of queued generation', async () => {
    detail.tasks = [{ ...topicTask('failed', 'failed'), error: '源码资料不足' }];
    await render('project=p&view=topics&topics=failed');
    expect(container.textContent).toContain('源码资料不足');
    await click(button('生成5个选题'));
    expect(container.textContent).toContain('排队中');
    await click(button('取消任务'));
    expect(vi.mocked(api.post).mock.calls.slice(-1)[0]?.[0]).toContain('/cancel');
    expect(container.textContent).toContain('已取消');
  });
});
