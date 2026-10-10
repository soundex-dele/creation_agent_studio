// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { ConfigProvider } from 'antd';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '@/services/api';
import { streamRunEvents, type RunStreamOptions } from '@/services/runStream';
import type { RepoDetail, RepoTask } from '@/services/repoExplainer';
import { createRunEventState } from '@/entities/run';
import RepoExplainerPage from '../RepoExplainerPage';

const route = vi.hoisted(() => ({ organization: 'org-1' }));
vi.mock('@/services/api', () => ({ api: { get: vi.fn(), post: vi.fn() } }));
vi.mock('@/services/runStream', () => ({ streamRunEvents: vi.fn() }));
vi.mock('react-router-dom', () => ({ useNavigate: () => vi.fn(), useParams: () => ({ applicationId: '39' }),
  useSearchParams: () => [new URLSearchParams('project=p1'), vi.fn()] }));
vi.mock('@/stores/useOrganizationStore', () => ({ useOrganizationStore: (select: (s: unknown) => unknown) => select({ currentOrganizationId: route.organization }) }));
vi.mock('@/stores/useAuthStore', () => ({ useAuthStore: (select: (s: unknown) => unknown) => select({ user: { id: 'owner' } }) }));

let root: Root;
let container: HTMLDivElement;
let project: RepoDetail;
let stream: RunStreamOptions;
let abort: ReturnType<typeof vi.fn<() => void>>;
const task = (kind = 'import'): RepoTask => ({ id: 'task-1', run_id: 'run-1', kind, status: 'queued', event_sequence: 1,
  created_at: new Date().toISOString(), snapshot_id: 'snapshot-1', progress: {}, output: {}, options: {}, error: '' });
const getProjectCalls = () => vi.mocked(api.get).mock.calls.filter(([url]) => url.endsWith('/projects/p1')).length;
const render = () => act(async () => root.render(<ConfigProvider theme={{ token: { motion: false } }}><RepoExplainerPage /></ConfigProvider>));
const send = (sequence: number, type: string, payload = {}) => act(async () => {
  await stream.onEvent({ schema_version: 1, run_id: 'run-1', attempt_id: null, sequence, type, payload, created_at: new Date().toISOString() });
});
const button = (label: string) => [...container.querySelectorAll<HTMLButtonElement>('button')].find(el => el.textContent?.replace(/\s/g, '') === label)!;

beforeEach(() => {
  vi.useFakeTimers(); vi.clearAllMocks(); route.organization = 'org-1';
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() })));
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
  const computed = window.getComputedStyle.bind(window);
  vi.spyOn(window, 'getComputedStyle').mockImplementation(element => computed(element));
  project = { id: 'p1', title: '工具', archived: false, updated_at: '', tasks: [], snapshots: [], contents: [], handoffs: [], limits: {} };
  vi.mocked(api.get).mockImplementation(async url => url.endsWith('/projects/p1') ? structuredClone(project) : []);
  abort = vi.fn();
  vi.mocked(streamRunEvents).mockImplementation(options => {
    stream = options; return { abort, cursor: 0, done: Promise.resolve() };
  });
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount()); container.remove();
  vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals();
});

describe('repository live task workflow', () => {
  it('subscribes immediately after import even when the following project refresh fails', async () => {
    await render();
    const input = container.querySelector<HTMLInputElement>('input[placeholder="https://github.com/owner/repo"]')!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, 'https://github.com/example/tool');
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });
    vi.mocked(api.post).mockResolvedValue(task());
    vi.mocked(api.get).mockRejectedValueOnce(new Error('refresh offline'));
    await act(async () => button('导入并保存快照').click());
    expect(streamRunEvents).toHaveBeenCalledOnce();
    expect(stream).toMatchObject({ organizationId: 'org-1', runId: 'run-1' });
    expect(container.textContent).toContain('等待执行器接单');
    await send(1, 'run.queued'); await send(2, 'run.started');
    expect(container.textContent).toContain('执行器已接单');
    expect(container.textContent).not.toContain('等待执行器接单');
    await send(3, 'progress.updated', { stage: '读取 GitHub 源码' });
    expect(container.textContent).toContain('读取 GitHub 源码');
  });

  it.each(['analyze', 'write'])('shows %s model activity, uses polling on disconnect and rejects stale replay', async kind => {
    project.tasks = [task(kind)]; await render();
    await send(1, 'run.queued'); await send(2, 'run.started');
    await send(3, 'progress.updated', { stage: '生成内容', activity: 'responding', characters: 320 });
    expect(container.textContent).toContain('已接收 320 字符');
    await act(async () => { stream.onConnectionChange?.(false); stream.onError?.(new Error('offline')); });
    expect(container.textContent).toContain('正在重连并定时刷新');
    project.tasks[0] = { ...project.tasks[0], status: 'running', event_sequence: 5, progress: { stage: '校验来源引用' } };
    await act(async () => { await vi.advanceTimersByTimeAsync(2500); });
    expect(container.textContent).toContain('校验来源引用');
    await send(4, 'progress.updated', { stage: '旧阶段' });
    expect(container.textContent).not.toContain('旧阶段');
    expect(streamRunEvents).toHaveBeenCalledOnce();
    await act(async () => { stream.onConnectionChange?.(true); });
    expect(container.textContent).toContain('实时更新已连接');
  });

  it('refreshes results on completion without waiting for the polling timer', async () => {
    project.tasks = [task()]; await render();
    await send(1, 'run.queued'); await send(2, 'run.started');
    const before = getProjectCalls();
    project.tasks[0].status = 'succeeded'; project.tasks[0].event_sequence = 3;
    await send(3, 'run.succeeded');
    expect(getProjectCalls()).toBe(before + 1);
    expect(container.textContent).toContain('已完成');
    expect(container.textContent).toContain('结果已保存');
    expect(abort).toHaveBeenCalled();
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    expect(getProjectCalls()).toBe(before + 1);
  });

  it('restores compacted event progress and retries result loading after a terminal refresh failure', async () => {
    project.tasks = [task('write')]; await render();
    await act(async () => {
      await stream.onSnapshot?.({ schema_version: 1, run_id: 'run-1', through_sequence: 8,
        projection: { ...createRunEventState('run-1', 8), status: 'running', progress: { stage: '恢复后的创作阶段' } },
        created_at: '', updated_at: '' });
    });
    expect(container.textContent).toContain('恢复后的创作阶段');
    vi.mocked(api.get).mockRejectedValueOnce(new Error('temporary offline'));
    await send(9, 'run.succeeded');
    expect(container.textContent).toContain('已完成');
    project.tasks[0].status = 'succeeded'; project.tasks[0].event_sequence = 9;
    const before = getProjectCalls();
    await act(async () => { await vi.advanceTimersByTimeAsync(2500); });
    expect(getProjectCalls()).toBe(before + 1);
    expect(abort).toHaveBeenCalled();
  });

  it('keeps cancellation and failure explicit instead of showing the last running stage', async () => {
    project.tasks = [task()]; await render();
    vi.mocked(api.post).mockImplementation(async () => {
      project.tasks[0].status = 'cancelling'; return {};
    });
    await act(async () => button('取消任务').click());
    expect(api.post).toHaveBeenCalledWith(expect.stringContaining('/tasks/task-1/cancel'), {});
    expect(button('取消任务').disabled).toBe(true);
    expect(container.textContent).toContain('正在停止任务');
    project.tasks[0].status = 'cancelled';
    await act(async () => { await vi.advanceTimersByTimeAsync(2500); });
    expect(container.textContent).toContain('任务已取消');
    expect(button('取消任务')).toBeUndefined();
    project.tasks[0].status = 'failed'; project.tasks[0].error = '模型超时，请重试';
    await act(async () => button('刷新').click());
    expect(container.textContent).toContain('模型超时，请重试');
  });

  it('aborts the old stream and polling when the tenant changes', async () => {
    project.tasks = [task()]; await render();
    const oldStream = stream;
    route.organization = 'org-2'; project.tasks = [];
    await render();
    expect(abort).toHaveBeenCalled();
    await act(async () => { oldStream.onConnectionChange?.(true); });
    expect(container.textContent).not.toContain('实时更新已连接');
    const before = getProjectCalls();
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    expect(getProjectCalls()).toBe(before);
  });
});
