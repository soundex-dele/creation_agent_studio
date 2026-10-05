// @vitest-environment jsdom
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { ConfigProvider } from 'antd';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { GenerationMessages } from '../rental/GenerationMessages';
import { rentalStreamText } from '@/services/rentalStreamText';
import { type Task } from '@/services/rentalGrowth';
import { streamRunEvents, type RunStreamOptions } from '@/services/runStream';

vi.mock('@/services/runStream', () => ({ streamRunEvents: vi.fn() }));
let root: Root; let container: HTMLDivElement; let callbacks: RunStreamOptions;
const abort = vi.fn();
const task: Task = { id: 'task', run_id: 'run1', organization_id: 'org1', kind: 'copy', status: 'running', error: '', applied: false, request: {}, result: {}, created_at: '2026-10-05' };
const event = (sequence: number, type: string, payload: Record<string, unknown>) => ({ schema_version: 1, run_id: 'run1', attempt_id: null, sequence, type, payload, created_at: '2026-10-05' });
async function render(value = task) { await act(async () => root.render(createElement(ConfigProvider, { theme: { token: { motion: false } } }, createElement(GenerationMessages, { task: value })))); }
async function emit(sequence: number, type: string, payload: Record<string, unknown>) { await act(async () => { await callbacks.onEvent(event(sequence, type, payload)); }); }
async function click(label: string) { const button = [...container.querySelectorAll('button')].find(b => b.textContent === label)!; expect(button).toBeDefined(); await act(async () => button.click()); }
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} })));
  vi.mocked(streamRunEvents).mockImplementation(options => { callbacks = options; return { abort, cursor: 0, done: new Promise(() => {}) }; });
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); vi.resetAllMocks(); vi.unstubAllGlobals(); });

it('shows real deltas before the task finishes and replaces authoritative snapshots', async () => {
  await render();
  expect(streamRunEvents).toHaveBeenCalledWith(expect.objectContaining({ runId: 'run1', organizationId: 'org1' }));
  await emit(1, 'progress.updated', { stage: '正在生成文案' });
  await emit(2, 'output.delta', { text: '{"titles":["养猫租房"],"body":"月租' });
  expect(container.textContent).toContain('月租'); expect(container.textContent).not.toContain('"body"');
  await emit(3, 'output.delta', { text: '2800元' });
  await emit(3, 'output.delta', { text: '2800元' });
  expect(container.textContent).toContain('月租2800元'); expect(container.textContent).not.toContain('2800元2800元');
  await emit(4, 'output.snapshot', { text: '{"body":"月租3000元"}' });
  expect(container.textContent).toContain('月租3000元'); expect(container.textContent).not.toContain('2800');
  expect(container.textContent).toContain('尚未校验');
});

it('preserves received copy on disconnect, restores compacted history, and stops on unmount', async () => {
  await render(); await emit(1, 'output.delta', { text: '{"body":"已收到的内容' });
  await act(async () => callbacks.onConnectionChange?.(false));
  expect(container.textContent).toContain('已收到的内容'); expect(container.textContent).toContain('重新连接');
  await act(async () => callbacks.onSnapshot?.({ schema_version: 1, run_id: 'run1', through_sequence: 10, projection: { runId: 'run1', nextSequence: 11, status: 'running', output: '{"body":"恢复的文案', progress: { stage: '继续生成' }, tools: {}, pendingInput: null, artifactIds: [] }, created_at: '', updated_at: '' }));
  await emit(9, 'output.delta', { text: '重复消息' });
  await emit(11, 'output.delta', { text: '，继续输出"}' });
  expect(container.textContent).toContain('恢复的文案，继续输出'); expect(container.textContent).not.toContain('重复消息');
  await click('收起消息'); expect(abort).toHaveBeenCalledTimes(1);
});

it('replays completed history on demand and closes terminal compacted streams', async () => {
  await render({ ...task, status: 'succeeded' }); expect(streamRunEvents).not.toHaveBeenCalled();
  await click('查看消息');
  await act(async () => callbacks.onSnapshot?.({ schema_version: 1, run_id: 'run1', through_sequence: 20, projection: { runId: 'run1', nextSequence: 21, status: 'succeeded', output: '{"body":"最终正文"}', progress: null, tools: {}, pendingInput: null, artifactIds: [] }, created_at: '', updated_at: '' }));
  expect(container.textContent).toContain('最终正文'); expect(abort).toHaveBeenCalledTimes(1);
});

it('retains partial messages when a task fails or is cancelled', async () => {
  await render(); await emit(1, 'output.delta', { text: '{"body":"生成到一半' });
  await emit(2, 'run.failed', {}); await act(async () => callbacks.onConnectionChange?.(false));
  expect(container.textContent).toContain('生成失败'); expect(container.textContent).toContain('生成到一半');
  expect(container.textContent).not.toContain('连接中断');
  await render({ ...task, status: 'cancelled' }); expect(container.textContent).toContain('已取消生成');
});

it('does not force scrolling while the user is reading older messages', async () => {
  await render(); const output = container.querySelector('.rental-message-output') as HTMLDivElement;
  Object.defineProperties(output, { scrollHeight: { value: 1000, configurable: true }, clientHeight: { value: 200, configurable: true } });
  output.scrollTop = 0;
  await act(async () => output.dispatchEvent(new Event('scroll', { bubbles: true })));
  await emit(1, 'output.delta', { text: '{"body":"新消息' });
  expect(output.scrollTop).toBe(0); await click('回到最新消息'); expect(output.scrollTop).toBe(1000);
});

it('decodes fragmented escapes and nested page text without leaking record IDs or JSON fields', () => {
  expect(rentalStreamText('{"body":"第一行\\n第\\u4e')).toBe('发布文案\n第一行\n第');
  expect(rentalStreamText('{"body":"第一行\\n第\\u4e8c行","pages":[{"photo_ref":"private-id:1","caption":"客厅","layout":"顶部留白"}]}')).toContain('第一行\n第二行');
  const output = rentalStreamText('正在整理资料。\n```json\n{"titles":["真实房源"],"pages":[{"photo_ref":"private-id:1","caption":"客厅","layout":"顶部留白"}],"property_ids":["private-id"]}');
  expect(output).toContain('正在整理资料。'); expect(output).toContain('客厅'); expect(output).not.toContain('private-id'); expect(output).not.toContain('photo_ref');
});
