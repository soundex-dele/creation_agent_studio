// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import AnimationTaskDetails from '../animation/AnimationTaskDetails';
import type { ApplicationRuntimeClient } from '@/services/applicationRuntime';
import type { AnimationRun } from '@/services/animationStudio';
import type { RunStreamOptions } from '@/services/runStream';

let root: Root; let host: HTMLDivElement;
let callbacks: Pick<RunStreamOptions, 'onEvent' | 'onSnapshot' | 'onError' | 'onConnectionChange'>;
const abort = vi.fn(); const close = vi.fn();
const subscribeRun = vi.fn((_id, value) => { callbacks = value; return { abort }; });
const runtime = { subscribeRun } as unknown as ApplicationRuntimeClient;
const run = { id: 'task-1', status: 'running', input: {}, artifacts: [] } as unknown as AnimationRun;
async function render(value = run) { await act(async () => root.render(<AnimationTaskDetails run={value} runtime={runtime} onClose={close} />)); }
async function event(sequence: number, type: string, payload: Record<string, unknown> = {}, id = run.id) {
  await act(async () => callbacks.onEvent({ schema_version: 1, run_id: id, attempt_id: null, sequence, type, payload, created_at: '2026-09-29T12:00:00Z' }));
}
beforeEach(() => {
  vi.clearAllMocks();
  Object.defineProperty(globalThis, 'IS_REACT_ACT_ENVIRONMENT', { value: true, configurable: true });
  const computed = window.getComputedStyle.bind(window);
  vi.spyOn(window, 'getComputedStyle').mockImplementation(element => computed(element));
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.useRealTimers(); });

describe('animation task details', () => {
  it('keeps each repair error as plain text through later progress and task completion', async () => {
    await render();
    for (let attempt = 1; attempt <= 3; attempt++) {
      await event(attempt * 2, 'progress.updated', { stage: 'build_failed', attempt, scene_id: 'two', scene_title: '第二幕',
        error_message: `错误 ${attempt}\n<img src=x onerror=alert(1)>`, will_retry: attempt < 3 });
      if (attempt < 3) await event(attempt * 2 + 1, 'progress.updated', { stage: 'repairing', attempt: attempt + 1, scene_id: 'two' });
    }
    expect(document.querySelectorAll('.animation-task-error')).toHaveLength(3);
    expect(document.body.textContent).toContain('首次构建失败');
    expect(document.body.textContent).toContain('第 1 次修复后仍失败');
    expect(document.body.textContent).toContain('第 2 次修复后仍失败');
    expect(document.querySelector('.animation-task-error pre')?.textContent).toBe('错误 1\n<img src=x onerror=alert(1)>');
    expect(document.querySelector('.animation-task-error img')).toBeNull();
    await act(async () => {
      for (let i = 7; i < 112; i++) callbacks.onEvent({ schema_version: 1, run_id: run.id, attempt_id: null,
        sequence: i, type: 'progress.updated', payload: { stage: 'generating', scene_id: String(i) }, created_at: '2026-09-29T12:00:00Z' });
    });
    await event(112, 'run.failed');
    expect(document.querySelectorAll('.animation-task-error')).toHaveLength(3);
    expect(document.querySelectorAll('.animation-task-log li')).toHaveLength(103);
  });

  it('restores a failure from a compacted snapshot with its repair number and reason', async () => {
    await render();
    await act(async () => callbacks.onSnapshot?.({ schema_version: 1, run_id: run.id, through_sequence: 30,
      created_at: '2026-09-29T12:00:00Z', updated_at: '2026-09-29T12:01:00Z',
      projection: { runId: run.id, nextSequence: 31, status: 'running', output: '',
        progress: { stage: 'build_failed', attempt: 2, error_message: '播放器初始化失败', will_retry: true }, tools: {}, pendingInput: null, artifactIds: [] } }));
    expect(document.querySelector('.animation-task-error pre')?.textContent).toBe('播放器初始化失败');
    expect(document.body.textContent).toContain('接下来进行第 2 次修复');
  });

  it('shows real scene, retry and AI response updates while coalescing repeated activity', async () => {
    await render();
    expect(subscribeRun).toHaveBeenCalledWith(run.id, expect.any(Object));
    await event(1, 'progress.updated', { stage: 'storyboard' });
    await event(2, 'progress.updated', { stage: 'generating', scene_id: 'two', scene_index: 2, scene_total: 5, scene_title: '第二幕', attempt: 1 });
    await event(3, 'progress.updated', { stage: 'generating', scene_id: 'two', scene_index: 2, scene_total: 5, scene_title: '第二幕', attempt: 1, activity: 'responding', characters: 200 });
    expect(document.querySelector('.animation-task-current')?.textContent).toContain('第 2 / 5 幕');
    expect(document.querySelector('.animation-task-current')?.textContent).toContain('已接收 200 字符');
    expect(document.querySelectorAll('.animation-task-log li')).toHaveLength(2);
    await event(4, 'progress.updated', { stage: 'repairing', scene_id: 'two', attempt: 2 });
    expect(document.querySelector('.animation-task-current')?.textContent).toContain('第 1 次修复');
    await event(4, 'progress.updated', { stage: 'saving' });
    await event(10, 'progress.updated', { stage: 'saving' }, 'another-run');
    expect(document.querySelector('.animation-task-current')?.textContent).toContain('修复');
    await event(5, 'agent.item', { type: 'reasoning', text: 'private-reasoning' });
    await event(6, 'output.delta', { text: 'raw source code' });
    expect(document.body.textContent).not.toContain('private-reasoning');
    expect(document.body.textContent).not.toContain('raw source code');
  });

  it('restores compacted progress and shows terminal outcomes without closing the dialog', async () => {
    await render();
    await act(async () => callbacks.onSnapshot?.({ schema_version: 1, run_id: run.id, through_sequence: 30,
      created_at: '2026-09-29T12:00:00Z', updated_at: '2026-09-29T12:01:00Z',
      projection: { runId: run.id, nextSequence: 31, status: 'running', output: '', progress: { stage: 'building_cover' }, tools: {}, pendingInput: null, artifactIds: [] } }));
    expect(document.body.textContent).toContain('较早记录已归档');
    expect(document.querySelector('.animation-task-current')?.textContent).toContain('生成封面');
    await event(31, 'run.failed', { error_message: '场景校验失败' });
    expect(document.querySelector('[role="dialog"]')).not.toBeNull();
    expect(document.body.textContent).toContain('场景校验失败');
    expect(document.querySelector('.animation-task-current')?.textContent).toContain('任务已结束');
    await render({ ...run, status: 'failed', error_message: '场景构建失败，已尝试修复两次。' });
    expect(document.querySelector('.ant-alert-description')?.textContent).toBe('场景构建失败，已尝试修复两次。');
  });

  it('supports reconnect and unsubscribes on close without cancelling the task', async () => {
    vi.useFakeTimers(); await render();
    const oldCallbacks = callbacks;
    await act(async () => callbacks.onError?.(new Error('offline')));
    expect(document.body.textContent).toContain('制作任务仍在后台执行');
    await act(async () => Array.from(document.querySelectorAll('button')).find(b => b.textContent === '重新连接')!.click());
    expect(subscribeRun).toHaveBeenCalledTimes(2); expect(abort).toHaveBeenCalledTimes(1);
    await act(async () => oldCallbacks.onEvent({ schema_version: 1, run_id: run.id, sequence: 99, attempt_id: null, type: 'progress.updated', payload: { stage: 'saving' }, created_at: '' }));
    expect(document.querySelector('.animation-task-current')?.textContent).not.toContain('保存');
    await act(async () => document.querySelector<HTMLButtonElement>('.ant-modal-footer button')!.click());
    expect(abort).toHaveBeenCalledTimes(2);
    await act(async () => vi.advanceTimersByTimeAsync(500));
    expect(close).toHaveBeenCalled();
  });

  it('caps long histories and respects the polled terminal status', async () => {
    await render();
    await act(async () => {
      for (let i = 1; i <= 105; i++) callbacks.onEvent({ schema_version: 1, run_id: run.id, attempt_id: null,
        sequence: i, type: 'progress.updated', payload: { stage: 'generating', scene_id: String(i) }, created_at: '2026-09-29T12:00:00Z' });
    });
    expect(document.querySelectorAll('.animation-task-log li')).toHaveLength(100);
    await render({ ...run, status: 'succeeded' });
    expect(document.querySelector('.animation-task-current')?.textContent).toContain('已完成');
    expect(document.querySelector('[role="dialog"]')).not.toBeNull();
  });
});
