// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '@/services/api';
import * as runStream from '@/services/runStream';
import type { RunResource } from '@/services/applicationRuntime';
import type { RunEventEnvelope } from '@/entities/run';
import { useAuthStore } from '../useAuthStore';
import { createConversationStore, useConversationStore } from '../useConversationStore';

const conversation = (id: string) => ({ id, title: id, created_at: '', updated_at: '', messages: [] });
const run: RunResource = {
  id: 'run-old', organization_id: 'shared-org', status: 'running', version: 1,
  next_event_sequence: 1, definition_snapshot: {}, input: {}, output_summary: {},
};
const user = (id: string) => ({ id, username: id, email: '', role: 'member' as const, created_at: '' });

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((complete) => { resolve = complete; });
  return { promise, resolve };
}

function markRunning() {
  useConversationStore.setState({
    conversations: [conversation('old')], currentConversation: conversation('old'),
    activeRun: run, streamingMessageId: 'old-reply', agentActivity: 'Running',
  });
}

function expectIdle() {
  expect(useConversationStore.getState()).toMatchObject({
    activeRun: null, streamingMessageId: null, pendingQuestion: null,
    agentActivity: null, isLoading: false,
  });
}

beforeEach(() => {
  useAuthStore.setState({ user: user('first'), token: 'first-token', isAuthenticated: true });
  useConversationStore.getState().reset();
});

afterEach(() => {
  useConversationStore.getState().reset();
  useAuthStore.getState().clearAuth();
  vi.restoreAllMocks();
});

describe('conversation session isolation', () => {
  it('does not cancel a different conversation run from a stale view', async () => {
    markRunning();
    const post = vi.spyOn(api, 'post').mockResolvedValue({});
    await useConversationStore.getState().cancelTurn('other');
    expect(post).not.toHaveBeenCalled();
    expect(useConversationStore.getState().activeRun?.id).toBe(run.id);
    await useConversationStore.getState().cancelTurn('old');
    expect(post).toHaveBeenCalledOnce();
  });

  it('clears the running flag when opening a new conversation', () => {
    markRunning();
    useConversationStore.getState().setCurrentConversation(null);
    expectIdle();
    expect(useConversationStore.getState().currentConversation).toBeNull();
  });

  it('clears state on logout without cancelling the server task', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({});
    markRunning();
    await useAuthStore.getState().logout();
    expectIdle();
    expect(useConversationStore.getState().conversations).toEqual([]);
    expect(useConversationStore.getState().currentConversation).toBeNull();
    expect(JSON.parse(localStorage.getItem('conversation-storage')!).state.conversations).toEqual([]);
    expect(post.mock.calls.map(([path]) => path)).toEqual(['/auth/logout/']);
  });

  it('resets the old account on login but not on access-token refresh', async () => {
    markRunning();
    vi.spyOn(api, 'post').mockResolvedValueOnce({ access: 'refreshed' });
    await useAuthStore.getState().refreshAccessToken();
    expect(useConversationStore.getState().activeRun?.id).toBe(run.id);
    vi.mocked(api.post).mockResolvedValueOnce({ user: user('second'), tokens: { access: 'second-token' } });
    await useAuthStore.getState().login('second', 'password');
    expectIdle();
    expect(useConversationStore.getState().conversations).toEqual([]);
  });

  it('ignores conversation history arriving after an account change', async () => {
    const pending = deferred<unknown>();
    vi.spyOn(api, 'get').mockReturnValue(pending.promise as never);
    const loading = useConversationStore.getState().fetchConversations();
    useAuthStore.getState().clearAuth();
    pending.resolve([conversation('old')]);
    await loading;
    expect(useConversationStore.getState().conversations).toEqual([]);
    expectIdle();
  });

  it('ignores an old detail response after opening an empty conversation', async () => {
    const pending = deferred<unknown>();
    vi.spyOn(api, 'get').mockReturnValue(pending.promise as never);
    const stream = vi.spyOn(runStream, 'streamRunEvents');
    const loading = useConversationStore.getState().fetchConversationDetail('old');
    useConversationStore.getState().setCurrentConversation(null);
    pending.resolve({ ...conversation('old'), active_run: run });
    await loading;
    expectIdle();
    expect(useConversationStore.getState().currentConversation).toBeNull();
    expect(stream).not.toHaveBeenCalled();
  });

  it('does not retain the old running state when the next conversation is unavailable', async () => {
    markRunning();
    vi.spyOn(api, 'get').mockRejectedValue(new Error('Not found'));
    await expect(useConversationStore.getState().fetchConversationDetail('missing')).rejects.toThrow();
    expectIdle();
    expect(useConversationStore.getState().currentConversation).toBeNull();
  });

  it('does not insert a conversation created by the previous account', async () => {
    const pending = deferred<unknown>();
    vi.spyOn(api, 'post').mockReturnValue(pending.promise as never);
    const creating = useConversationStore.getState().createConversation();
    const rejected = expect(creating).rejects.toMatchObject({ name: 'AbortError' });
    useAuthStore.getState().clearAuth();
    pending.resolve(conversation('old'));
    await rejected;
    expectIdle();
    expect(useConversationStore.getState().conversations).toEqual([]);
    expect(useConversationStore.getState().error).toBeNull();
  });

  it('aborts the old stream and ignores buffered events after switching conversations', async () => {
    const abort = vi.fn();
    let emit: ((event: RunEventEnvelope) => void) | undefined;
    vi.spyOn(api, 'post').mockResolvedValue(run);
    vi.spyOn(runStream, 'streamRunEvents').mockImplementation((options) => {
      emit = options.onEvent;
      return { abort, cursor: 0, done: new Promise(() => undefined) };
    });
    useConversationStore.getState().setCurrentConversation(conversation('old'));
    const controller = useConversationStore.getState().sendMessageStream('old', 'hello');
    await controller.submitted;
    useConversationStore.getState().setCurrentConversation(conversation('new'));
    emit?.({
      schema_version: 1, run_id: run.id, attempt_id: null, sequence: 1, created_at: '',
      type: 'input.required', payload: { input_request_id: 'old-question', input_kind: 'answer', question: 'Old question' },
    });
    expect(abort).toHaveBeenCalledOnce();
    expectIdle();
    expect(useConversationStore.getState().currentConversation?.messages).toEqual([]);
  });

  it('does not restore an old question when an answer fails after logout', async () => {
    markRunning();
    useConversationStore.setState({ pendingQuestion: {
      id: 'old-question', kind: 'question', header: 'Question', question: 'Old question', options: [],
    } });
    const pending = deferred<void>();
    vi.spyOn(api, 'post').mockImplementation(async () => {
      await pending.promise;
      throw new Error('Old answer failed');
    });
    const answering = useConversationStore.getState().answerQuestion('old', { text: 'Yes' });
    const rejected = expect(answering).rejects.toThrow('Old answer failed');
    useAuthStore.getState().clearAuth();
    pending.resolve();
    await rejected;
    expectIdle();
    expect(useConversationStore.getState().currentConversation).toBeNull();
    expect(useConversationStore.getState().error).toBeNull();
  });

  it('keeps independently running conversations isolated', () => {
    const other = createConversationStore(undefined, api);
    other.setState({ currentConversation: conversation('other'), activeRun: run, streamingMessageId: 'other-reply' });
    markRunning();
    useAuthStore.getState().clearAuth();
    expectIdle();
    expect(other.getState().streamingMessageId).toBe('other-reply');
    other.getState().reset();
  });
});
