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

describe('idle conversation refresh', () => {
  const invalidDetails = [
    ['HTML fallback', '<!doctype html><html><body><div id="root"></div></body></html>'],
    ['null body', null],
    ['missing id', { messages: [] }],
    ['wrong conversation', { ...conversation('other') }],
    ['missing messages', { id: 'old', title: 'summary' }],
    ['invalid messages', { ...conversation('old'), messages: null }],
    ['invalid message entry', { ...conversation('old'), messages: [null] }],
  ] as const;

  it.each(invalidDetails)('preserves history after %s and accepts the next valid refresh', async (_label, invalid) => {
    const store = createConversationStore(undefined, api);
    const history = { ...conversation('old'), messages: [
      { id: 'm1', role: 'user' as const, content: 'Existing history', created_at: '' },
    ] };
    const recovered = { ...history, title: 'Recovered' };
    vi.spyOn(api, 'get').mockResolvedValueOnce(invalid).mockResolvedValueOnce(recovered);
    store.getState().setCurrentConversation(history);
    await expect(store.getState().refreshIfIdle('old')).rejects.toThrow('对话接口返回的数据格式异常');
    expect(store.getState().currentConversation).toBe(history);
    expect(store.getState().error).toBeNull();
    await store.getState().refreshIfIdle('old');
    expect(store.getState().currentConversation).toEqual(recovered);
  });

  it.each(invalidDetails)('rejects %s during detail loading without corrupting existing history', async (_label, invalid) => {
    const store = createConversationStore(undefined, api);
    const history = conversation('old');
    vi.spyOn(api, 'get').mockResolvedValueOnce(invalid).mockResolvedValueOnce(history);
    store.getState().setCurrentConversation(history);
    await expect(store.getState().fetchConversationDetail('old')).rejects.toThrow('对话接口返回的数据格式异常');
    expect(store.getState().currentConversation).toBe(history);
    expect(store.getState().isLoading).toBe(false);
    expect(store.getState().error).toContain('对话接口返回的数据格式异常');
    await store.getState().fetchConversationDetail('old');
    expect(store.getState().currentConversation).toEqual(history);
    expect(store.getState().error).toBeNull();
  });

  it('accepts a valid empty conversation instead of treating response size as validity', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ ...conversation('29'), id: 29 });
    await useConversationStore.getState().fetchConversationDetail('29');
    expect(useConversationStore.getState().currentConversation).toEqual(conversation('29'));
  });

  it('deduplicates concurrent refreshes and allows a later refresh', async () => {
    const pending = deferred<unknown>();
    const get = vi.spyOn(api, 'get').mockReturnValue(pending.promise as never);
    useConversationStore.getState().setCurrentConversation(conversation('old'));
    const first = useConversationStore.getState().refreshIfIdle('old');
    await useConversationStore.getState().refreshIfIdle('old');
    expect(get).toHaveBeenCalledOnce();
    pending.resolve({ ...conversation('old'), title: 'updated' });
    await first;
    expect(useConversationStore.getState().currentConversation?.title).toBe('updated');
    await useConversationStore.getState().refreshIfIdle('old');
    expect(get).toHaveBeenCalledTimes(2);
  });

  it('allows retry after a refresh fails', async () => {
    const get = vi.spyOn(api, 'get').mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce(conversation('old'));
    useConversationStore.getState().setCurrentConversation(conversation('old'));
    await expect(useConversationStore.getState().refreshIfIdle('old')).rejects.toThrow('offline');
    await useConversationStore.getState().refreshIfIdle('old');
    expect(get).toHaveBeenCalledTimes(2);
  });

  it('does not refresh another conversation or one with a pending outgoing message', async () => {
    const get = vi.spyOn(api, 'get');
    useConversationStore.getState().setCurrentConversation(conversation('old'));
    await useConversationStore.getState().refreshIfIdle('other');
    useConversationStore.setState({ streamingMessageId: 'pending' });
    await useConversationStore.getState().refreshIfIdle('old');
    expect(get).not.toHaveBeenCalled();
  });

  it('does not overwrite a message submitted while the refresh was in flight', async () => {
    const pending = deferred<unknown>();
    vi.spyOn(api, 'get').mockReturnValue(pending.promise as never);
    const stream = vi.spyOn(runStream, 'streamRunEvents');
    useConversationStore.getState().setCurrentConversation(conversation('old'));
    const refreshing = useConversationStore.getState().refreshIfIdle('old');
    const sending = { ...conversation('old'), messages: [
      { id: 'pending', role: 'user' as const, content: 'hello', created_at: '' },
    ] };
    useConversationStore.setState({ currentConversation: sending, streamingMessageId: 'pending' });
    pending.resolve({ ...conversation('old'), active_run: run });
    await refreshing;
    expect(useConversationStore.getState().currentConversation).toBe(sending);
    expect(stream).not.toHaveBeenCalled();
  });

  it('isolates pending refreshes across conversation changes', async () => {
    const old = deferred<unknown>();
    const next = deferred<unknown>();
    const get = vi.spyOn(api, 'get').mockReturnValueOnce(old.promise as never)
      .mockReturnValueOnce(next.promise as never);
    useConversationStore.getState().setCurrentConversation(conversation('old'));
    const first = useConversationStore.getState().refreshIfIdle('old');
    useConversationStore.getState().setCurrentConversation(conversation('new'));
    const second = useConversationStore.getState().refreshIfIdle('new');
    old.resolve({ ...conversation('old'), active_run: run });
    await first;
    await useConversationStore.getState().refreshIfIdle('new');
    expect(get).toHaveBeenCalledTimes(2);
    expect(useConversationStore.getState().currentConversation?.id).toBe('new');
    next.resolve({ ...conversation('new'), title: 'new update' });
    await second;
    expect(useConversationStore.getState().currentConversation?.title).toBe('new update');
  });
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
