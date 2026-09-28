import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { api } from '@/services/api';
import * as runStream from '@/services/runStream';
import { createConversationStore } from '../useConversationStore';

let store: ReturnType<typeof createConversationStore>;
let options: runStream.RunStreamOptions;
let sequence: number;
const history = { id: 'history', role: 'assistant' as const, content: '# History\n'.repeat(2000), created_at: '' };
const conversation = { id: 'chat', title: 'Chat', created_at: '', updated_at: '', messages: [history] };
const run = { id: 'run', organization_id: 'org', status: 'running' };

beforeEach(() => {
  vi.useFakeTimers();
  sequence = 0;
  store = createConversationStore(undefined, api);
  vi.spyOn(api, 'post').mockResolvedValue(run);
  vi.spyOn(api, 'get').mockResolvedValue({ ...conversation, active_run: run });
  vi.spyOn(runStream, 'streamRunEvents').mockImplementation(value => {
    options = value;
    return { abort: vi.fn(), cursor: 0, done: new Promise(() => undefined) };
  });
});

afterEach(() => {
  store.getState().disconnect();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

async function start(restored = false) {
  if (restored) {
    await store.getState().fetchConversationDetail('chat');
  } else {
    store.getState().setCurrentConversation(conversation);
    await store.getState().sendMessageStream('chat', 'Continue').submitted;
  }
}

function emit(type: string, payload: Record<string, unknown> = {}) {
  void options.onEvent({ schema_version: 1, run_id: 'run', attempt_id: null,
    sequence: ++sequence, type, payload, created_at: '' });
}

const lastMessage = () => store.getState().currentConversation!.messages.slice(-1)[0];

it.each([false, true])('bounds long-stream publications without losing text (restored=%s)', async restored => {
  await start(restored);
  const updates = vi.fn();
  const unsubscribe = store.subscribe(updates);
  const chunk = '持续生成的长内容。'.repeat(16);
  for (let index = 0; index < 1000; index++) {
    emit('output.delta', { text: chunk });
    emit('agent.item', { id: 'reply', type: 'agentMessage', delta: chunk });
  }
  expect(updates).toHaveBeenCalledTimes(1);
  expect(lastMessage().content).toBe(chunk); // First output remains immediate.
  vi.advanceTimersByTime(80);
  expect(updates).toHaveBeenCalledTimes(2);
  expect(lastMessage().content).toBe(chunk.repeat(1000));
  expect(lastMessage().metadata?.agent?.activity.items.reply.text).toBe(chunk.repeat(1000));
  expect(store.getState().currentConversation!.messages[0]).toBe(history);
  vi.advanceTimersByTime(1000);
  expect(updates).toHaveBeenCalledTimes(2);
  unsubscribe();
});

it('continues publishing during an uninterrupted stream instead of debouncing forever', async () => {
  await start();
  for (let index = 0; index < 50; index++) {
    emit('output.delta', { text: 'x' });
    vi.advanceTimersByTime(20);
    if (index % 4 === 3) expect(lastMessage().content).toBe('x'.repeat(index + 1));
  }
  vi.advanceTimersByTime(80);
  expect(lastMessage().content).toBe('x'.repeat(50));
});

it('flushes text before questions and starts the resumed reply separately', async () => {
  await start();
  emit('output.delta', { text: 'A' });
  emit('output.delta', { text: 'B' });
  emit('input.required', { input_request_id: 'question', input_kind: 'answer', question: '继续吗？' });
  expect(lastMessage().content).toContain('AB\n\n继续吗？');
  expect(store.getState().streamingMessageId).toBeNull();
  emit('input.resolved');
  emit('output.delta', { text: 'New' });
  expect(lastMessage().content).toBe('New');
  vi.advanceTimersByTime(1000);
  expect(lastMessage().content).toBe('New');
});

it('applies authoritative output and failure immediately, with no stale timer overwrite', async () => {
  await start();
  emit('output.delta', { text: 'draft' });
  emit('output.delta', { text: ' pending' });
  emit('output.snapshot', { text: 'Final document' });
  expect(lastMessage().content).toBe('Final document');
  emit('output.delta', { text: ' A' });
  emit('output.delta', { text: ' B' });
  emit('run.failed', { message: '失败原因' });
  expect(lastMessage().content).toBe('Final document A B');
  expect(store.getState().error).toBe('失败原因');
  expect(store.getState().streamingMessageId).toBeNull();
  vi.advanceTimersByTime(1000);
  expect(lastMessage().content).toBe('Final document A B');
});

it.each(['run.succeeded', 'run.cancelled'])('flushes the final text before %s refreshes history', async type => {
  await start();
  vi.mocked(api.get).mockImplementation(() => new Promise(() => undefined));
  emit('output.delta', { text: 'A' });
  emit('output.delta', { text: 'B' });
  emit(type);
  expect(lastMessage().content).toBe('AB');
  expect(store.getState().streamingMessageId).toBeNull();
  expect(vi.getTimerCount()).toBe(0);
});

it.each([false, true])('preserves transport errors when text is pending (restored=%s)', async restored => {
  await start(restored);
  emit('output.delta', { text: 'A' });
  emit('output.delta', { text: 'B' });
  options.onError?.(new Error('连接已断开'));
  expect(lastMessage().content).toBe('AB');
  vi.advanceTimersByTime(1000);
  expect(store.getState().error).toContain('连接已断开');
});

it('flushes pending text when the stream handle is aborted', async () => {
  store.getState().setCurrentConversation(conversation);
  const controller = store.getState().sendMessageStream('chat', 'Continue');
  await controller.submitted;
  emit('output.delta', { text: 'A' });
  emit('output.delta', { text: 'B' });
  controller.abort();
  expect(lastMessage().content).toBe('AB');
  expect(vi.getTimerCount()).toBe(0);
});

it.each([false, true])('cleans pending updates on disconnect and conversation switch (restored=%s)', async restored => {
  await start(restored);
  emit('output.delta', { text: 'A' });
  emit('output.delta', { text: 'B' });
  store.getState().disconnect();
  expect(lastMessage().content).toBe('AB');
  store.getState().setCurrentConversation({ ...conversation, id: 'other', messages: [] });
  emit('output.delta', { text: 'late' });
  vi.advanceTimersByTime(1000);
  expect(store.getState().currentConversation?.messages).toEqual([]);
  expect(vi.getTimerCount()).toBe(0);
});
