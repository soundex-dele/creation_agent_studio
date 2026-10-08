// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '@/services/api';
import { createConversationStore } from '../useConversationStore';

const detail = (id: string) => ({ id, title: id, messages: [], created_at: '', updated_at: '' });

beforeEach(() => vi.useFakeTimers());
afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); });

describe('conversation detail loading recovery', () => {
  it.each([
    { code: 'ECONNABORTED' }, { code: 'ETIMEDOUT' }, { code: 'ERR_NETWORK' },
    { response: { status: 502 } }, { response: { status: 503 } }, { response: { status: 504 } },
  ])('recovers a transient failure with one bounded retry: %j', async (failure) => {
    const store = createConversationStore(undefined, api);
    const get = vi.spyOn(api, 'get').mockRejectedValueOnce(failure).mockResolvedValueOnce(detail('1'));
    const loading = store.getState().fetchConversationDetail('1');
    await vi.advanceTimersByTimeAsync(499);
    expect(get).toHaveBeenCalledOnce();
    expect(store.getState()).toMatchObject({ error: null, isLoading: true });
    await vi.advanceTimersByTimeAsync(1);
    await loading;
    expect(get).toHaveBeenCalledTimes(2);
    expect(get).toHaveBeenLastCalledWith('/conversations/1/', undefined, {
      timeout: 30000, signal: expect.any(AbortSignal),
    });
    expect(store.getState()).toMatchObject({ currentConversation: detail('1'), error: null, isLoading: false });
  });

  it('recovers a failed initial load on returning or reconnecting, even without history', async () => {
    const store = createConversationStore(undefined, api);
    const failure = { code: 'ECONNABORTED' };
    const get = vi.spyOn(api, 'get').mockRejectedValue(failure);
    const failed = expect(store.getState().fetchConversationDetail('1')).rejects.toBe(failure);
    await vi.runAllTimersAsync();
    await failed;
    expect(get).toHaveBeenCalledTimes(2);
    expect(store.getState()).toMatchObject({ currentConversation: null, isLoading: false });
    expect(store.getState().error).toContain('超时');
    get.mockResolvedValue(detail('1'));
    await store.getState().refreshIfIdle('1');
    expect(store.getState()).toMatchObject({ currentConversation: detail('1'), error: null });
  });

  it.each([401, 403, 404, 500])('does not automatically retry HTTP %s', async (status) => {
    const store = createConversationStore(undefined, api);
    const failure = { response: { status, data: { detail: 'Server explanation' } } };
    const get = vi.spyOn(api, 'get').mockRejectedValue(failure);
    await expect(store.getState().fetchConversationDetail('1')).rejects.toBe(failure);
    await store.getState().refreshIfIdle('1');
    expect(get).toHaveBeenCalledOnce();
    expect(store.getState().error).toBe('Server explanation');
  });

  it('cancels the retry delay when switching history and never restores the old conversation', async () => {
    const store = createConversationStore(undefined, api);
    const get = vi.spyOn(api, 'get').mockRejectedValueOnce({ code: 'ERR_NETWORK' })
      .mockResolvedValueOnce(detail('2'));
    const first = store.getState().fetchConversationDetail('1');
    await vi.advanceTimersByTimeAsync(100);
    await store.getState().fetchConversationDetail('2');
    await first;
    await vi.runAllTimersAsync();
    expect(get).toHaveBeenCalledTimes(2);
    expect(get.mock.calls[0][2]?.signal?.aborted).toBe(true);
    expect(store.getState()).toMatchObject({ currentConversation: detail('2'), error: null, isLoading: false });
  });

  it('aborts an in-flight detail request on reset without publishing an error', async () => {
    const store = createConversationStore(undefined, api);
    const get = vi.spyOn(api, 'get').mockImplementation((_path, _params, config) => new Promise((_resolve, reject) => {
      config?.signal?.addEventListener?.('abort', () => reject({ code: 'ERR_CANCELED' }));
    }));
    const loading = store.getState().fetchConversationDetail('1');
    store.getState().reset();
    await loading;
    expect(get).toHaveBeenCalledOnce();
    expect(store.getState()).toMatchObject({ currentConversation: null, error: null, isLoading: false });
    await store.getState().refreshIfIdle('1');
    expect(get).toHaveBeenCalledOnce();
  });

  it('preserves loaded history on a failed refresh and clears recovery after switching away', async () => {
    const store = createConversationStore(undefined, api);
    store.getState().setCurrentConversation(detail('1'));
    const failure = { code: 'ERR_NETWORK' };
    const get = vi.spyOn(api, 'get').mockRejectedValue(failure);
    const failed = expect(store.getState().fetchConversationDetail('1')).rejects.toBe(failure);
    await vi.runAllTimersAsync();
    await failed;
    expect(store.getState().currentConversation).toEqual(detail('1'));
    store.getState().setCurrentConversation(detail('2'));
    await store.getState().refreshIfIdle('1');
    expect(get).toHaveBeenCalledTimes(2);
    expect(store.getState().currentConversation).toEqual(detail('2'));
  });
});
