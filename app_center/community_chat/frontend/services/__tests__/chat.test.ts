// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { api } from '@/services/api';
import { connectChat, createDraft, mergeMessageChanges, mergeMessages, sendDraft, type ChatMessage } from '../chat';

vi.mock('@/services/api', () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() } }));
afterEach(() => { vi.resetAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers(); });

it.each(['missing', 'throwing', 'absent'])('sends under %s crypto, reuses retry key and changes new submission key', async mode => {
  vi.stubGlobal('crypto', mode === 'absent' ? undefined : mode === 'missing' ? {} : { randomUUID: () => { throw new Error('insecure context'); } });
  const draft = createDraft('lobby', 'hello', []);
  vi.mocked(api.post).mockRejectedValueOnce(new Error('network')).mockResolvedValueOnce({ id: 1 });
  await expect(sendDraft(draft, vi.fn())).rejects.toThrow('network');
  await sendDraft(draft, vi.fn());
  const next = createDraft('lobby', 'hello', []);
  await sendDraft(next, vi.fn());
  expect(api.post).toHaveBeenCalledWith('/community-chat/rooms/lobby/messages/', { text: 'hello', attachments: [], request_key: draft.key });
  expect(vi.mocked(api.post).mock.calls[1][1]).toEqual(vi.mocked(api.post).mock.calls[0][1]);
  expect(next.key).not.toBe(draft.key);
  expect(createDraft('lobby', 'changed', []).key).not.toBe(next.key);
});

it('retries a failed second upload without uploading the first again', async () => {
  const draft = createDraft('group', 'files', [new File(['first'], 'one.txt'), new File(['second'], 'two.txt')]);
  vi.mocked(api.post).mockResolvedValueOnce({ id: 'one' }).mockRejectedValueOnce(new Error('upload failed'));
  await expect(sendDraft(draft, vi.fn())).rejects.toThrow('upload failed');
  expect(draft.uploaded).toHaveLength(1);
  vi.mocked(api.post).mockResolvedValueOnce({ id: 'two' }).mockResolvedValueOnce({ id: 123 });
  await sendDraft(draft, vi.fn());
  expect(api.post).toHaveBeenCalledTimes(4);
  expect(vi.mocked(api.post).mock.calls[3][1]).toEqual({ text: 'files', attachments: ['one', 'two'], request_key: draft.key });
});

it('rejects invalid payloads and merges duplicate/out-of-order message updates', () => {
  expect(() => createDraft('room', ' ', [])).toThrow();
  expect(() => createDraft('room', '', Array.from({ length: 10 }, () => new File(['a'], 'a')))).toThrow();
  expect(() => createDraft('room', '', [new File([], 'empty')])).toThrow();
  const original = { id: 1, revision: 1, text: 'hello' } as ChatMessage;
  const withdrawn = { ...original, revision: 3, text: '', withdrawn: true };
  expect(mergeMessages([withdrawn], [original, withdrawn])).toEqual([withdrawn]);
  const recent = { ...original, id: 50 };
  expect(mergeMessageChanges([recent], [withdrawn])).toEqual([recent]);
  // Explicit history loading still includes that withdrawn message.
  expect(mergeMessages([recent], [withdrawn])).toEqual([withdrawn, recent]);
});

class FakeSocket {
  static instances: FakeSocket[] = [];
  onopen?: () => void;
  onmessage?: (event: { data: string }) => void;
  onclose?: () => void;
  onerror?: () => void;
  send = vi.fn();
  close = vi.fn(() => this.onclose?.());
  constructor(public url: string) { FakeSocket.instances.push(this); }
  emit(data: unknown) { this.onmessage?.({ data: JSON.stringify(data) }); }
}

beforeEach(() => { FakeSocket.instances = []; });
it('polls offline every 5s, authenticates without URL secrets, reconciles reconnect and ignores duplicate events', async () => {
  vi.useFakeTimers(); vi.stubGlobal('WebSocket', FakeSocket);
  vi.mocked(api.post).mockResolvedValue({ ticket: 'secret-ticket' });
  const refresh = vi.fn(); const status = vi.fn();
  const stop = connectChat(refresh, status);
  await vi.advanceTimersByTimeAsync(0);
  const socket = FakeSocket.instances[0];
  expect(socket.url).not.toContain('secret-ticket');
  socket.onopen?.();
  expect(socket.send).toHaveBeenCalledWith(JSON.stringify({ ticket: 'secret-ticket' }));
  await vi.advanceTimersByTimeAsync(5000);
  expect(refresh).toHaveBeenCalled();
  socket.emit({ type: 'ready' }); refresh.mockClear();
  socket.emit({ type: 'changed', room: 'r', version: 1, event_id: 'event-one' });
  socket.emit({ type: 'changed', room: 'r', version: 1, event_id: 'event-one' });
  expect(refresh).toHaveBeenCalledTimes(1);
  socket.close();
  await vi.advanceTimersByTimeAsync(1000);
  const next = FakeSocket.instances[1];
  refresh.mockClear(); next.emit({ type: 'ready' });
  expect(refresh).toHaveBeenCalledTimes(1);
  stop(); refresh.mockClear();
  await vi.advanceTimersByTimeAsync(60000);
  expect(refresh).not.toHaveBeenCalled();
});
