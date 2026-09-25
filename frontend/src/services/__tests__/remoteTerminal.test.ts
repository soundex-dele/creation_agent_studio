import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { api } from '../api';
import { TerminalFrameBuffer, TerminalInput, terminalKey, terminalPost, terminalStream } from '../remoteTerminal';
import { registerAuthSession } from '../authSession';

beforeEach(() => { vi.useFakeTimers(); });
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it('retries a lost response with the same explicit key, independent of input text', async () => {
  const post = vi.spyOn(api, 'post').mockRejectedValueOnce({ response: { status: 503 } }).mockResolvedValue({ sequence: 1 });
  const result = terminalPost('computer', 'session/input/', { data: 'same' }, 'batch-1');
  await vi.advanceTimersByTimeAsync(500);
  await result;
  expect(post).toHaveBeenCalledTimes(2);
  expect(post.mock.calls.map(call => call[2]?.headers?.['Idempotency-Key'])).toEqual(['batch-1', 'batch-1']);
  await terminalPost('computer', 'session/input/', { data: 'same' }, 'batch-2');
  expect(post.mock.calls[2][2]?.headers?.['Idempotency-Key']).toBe('batch-2');
});

it('serializes input batches and discards pending input on disconnect', async () => {
  let resolve!: (value: unknown) => void;
  const post = vi.spyOn(api, 'post').mockImplementationOnce(() => new Promise(done => { resolve = done; })).mockResolvedValue({});
  const onError = vi.fn();
  const input = new TerminalInput('computer', 'session', onError);
  input.setOnline(true); input.write('a');
  await vi.advanceTimersByTimeAsync(25);
  input.write('b'); input.setOnline(false); input.write('offline');
  resolve({}); await vi.advanceTimersByTimeAsync(30);
  expect(post).toHaveBeenCalledTimes(1);
  expect(onError).toHaveBeenCalledOnce();
  expect(onError.mock.calls[0][0].message).toContain('尚未发送的输入已取消');
  input.setOnline(true); input.write('a'); await vi.advanceTimersByTimeAsync(25);
  expect(post.mock.calls.map(call => call[1])).toEqual([
    { client_id: expect.any(String), sequence: 1, data: 'a' },
    { client_id: expect.any(String), sequence: 2, data: 'a' },
  ]);
  input.dispose();
});

it('splits large Unicode pastes into ordered byte-bounded batches without losing characters', async () => {
  const post = vi.spyOn(api, 'post').mockResolvedValue({});
  const onError = vi.fn();
  const input = new TerminalInput('computer', 'session', onError);
  const text = '\ufeff' + 'a'.repeat(16379) + '😀中文'.repeat(6000) + '\ufeff\r';
  input.setOnline(true); input.write(text);
  await vi.advanceTimersByTimeAsync(25);
  const batches = post.mock.calls.map(call => call[1] as { data: string; sequence: number; client_id: string });
  expect(batches.length).toBeGreaterThan(1);
  expect(batches.map(batch => batch.data).join('')).toBe(text);
  expect(batches.map(batch => batch.sequence)).toEqual(batches.map((_, index) => index + 1));
  expect(new Set(batches.map(batch => batch.client_id)).size).toBe(1);
  expect(batches.every(batch => new TextEncoder().encode(batch.data).length <= 16384)).toBe(true);
  expect(onError).not.toHaveBeenCalled();
  input.dispose();
});

it('preserves all pending keystrokes while a slow batch is awaiting acknowledgement', async () => {
  let resolve!: (value: unknown) => void;
  const post = vi.spyOn(api, 'post').mockImplementationOnce(() => new Promise(done => { resolve = done; })).mockResolvedValue({});
  const input = new TerminalInput('computer', 'session', vi.fn());
  input.setOnline(true); input.write('start');
  await vi.advanceTimersByTimeAsync(25);
  const pending = '中文😀\x1b[A\t'.repeat(4000) + '\r';
  for (const character of pending) input.write(character);
  await vi.advanceTimersByTimeAsync(5000);
  expect(post).toHaveBeenCalledTimes(1);
  resolve({}); await vi.advanceTimersByTimeAsync(25);
  expect(post.mock.calls.map(call => (call[1] as { data: string }).data).join('')).toBe('start' + pending);
  input.dispose();
});

it('retries an input batch with the same sequence and key before draining the next batch', async () => {
  const post = vi.spyOn(api, 'post').mockRejectedValueOnce({ response: { status: 503 } }).mockResolvedValue({});
  const input = new TerminalInput('computer', 'session', vi.fn());
  input.setOnline(true); input.write('first');
  await vi.advanceTimersByTimeAsync(25);
  input.write('next\r');
  await vi.advanceTimersByTimeAsync(1000);
  expect(post).toHaveBeenCalledTimes(3);
  expect(post.mock.calls[0][1]).toEqual(post.mock.calls[1][1]);
  expect(post.mock.calls[0][2]?.headers?.['Idempotency-Key']).toBe(post.mock.calls[1][2]?.headers?.['Idempotency-Key']);
  expect(post.mock.calls[2][1]).toMatchObject({ sequence: 2, data: 'next\r' });
  input.dispose();
});

it('pauses on queue overflow instead of sending a command with missing characters', async () => {
  const post = vi.spyOn(api, 'post').mockResolvedValue({});
  const onError = vi.fn();
  const input = new TerminalInput('computer', 'session', onError);
  input.setOnline(true); input.write('pending'); input.write('a'.repeat(256 * 1024)); input.write('\r');
  await vi.advanceTimersByTimeAsync(25);
  expect(input.paused).toBe(true);
  expect(input.writable).toBe(false);
  expect(post).not.toHaveBeenCalled();
  expect(onError.mock.calls[0][0].message).toContain('输入已暂停');
  input.dispose();
});

it('does not send or report discarded input after disposal', async () => {
  const post = vi.spyOn(api, 'post').mockResolvedValue({});
  const onError = vi.fn();
  const input = new TerminalInput('computer', 'session', onError);
  input.setOnline(true); input.write('pending'); input.dispose(); input.setOnline(true); input.write('later');
  await vi.advanceTimersByTimeAsync(1000);
  expect(post).not.toHaveBeenCalled();
  expect(onError).not.toHaveBeenCalled();
  expect(input.writable).toBe(false);
});

it('freezes new input after an uncertain write failure', async () => {
  const post = vi.spyOn(api, 'post').mockRejectedValue({ response: { status: 503 } });
  const onError = vi.fn();
  const input = new TerminalInput('computer', 'session', onError);
  input.setOnline(true); input.write('run\r');
  await vi.advanceTimersByTimeAsync(2000);
  expect(post).toHaveBeenCalledTimes(3);
  expect(onError).toHaveBeenCalledOnce();
  expect(input.paused).toBe(true);
  input.setOnline(true); input.write('later'); await vi.advanceTimersByTimeAsync(30);
  expect(post).toHaveBeenCalledTimes(3);
  input.dispose();
});

it('parses split output, replay gaps and exit without interpreting escape sequences', () => {
  const frames = new TerminalFrameBuffer();
  expect(frames.push(': heartbeat\n\ndata: {"type":"out')).toEqual([]);
  expect(frames.push('put","sequence":1,"data":"中文\\u001b[31m"}\n\n')).toEqual([
    { type: 'output', sequence: 1, data: '中文\x1b[31m' },
  ]);
  expect(frames.push('data: {"type":"truncated","sequence":4}\n\ndata: {"type":"exit","exit_code":0}\n\n')).toHaveLength(2);
  expect(terminalKey()).toMatch(/^[0-9a-f]{32}$/);
});

it('refreshes stream authentication and keeps the selected computer and cursor', async () => {
  let token = 'old';
  const refresh = vi.fn(async () => { token = 'fresh'; });
  registerAuthSession({ accessToken: () => token, refresh, clear: vi.fn() });
  const fetchMock = vi.fn().mockResolvedValueOnce(new Response('{}', { status: 401 })).mockResolvedValueOnce(
    new Response('data: {"type":"ready"}\n\ndata: {"type":"exit","exit_code":0}\n\n'));
  vi.stubGlobal('fetch', fetchMock);
  const events: unknown[] = [];
  await terminalStream('selected', 'session', 7, new AbortController().signal, async event => { events.push(event); });
  expect(refresh).toHaveBeenCalledOnce();
  expect(fetchMock.mock.calls[1][0]).toContain('/remote/devices/selected/proxy/remote-access/terminals/session/stream/?after=7');
  expect(fetchMock.mock.calls[1][1].headers.Authorization).toBe('Bearer fresh');
  expect(events).toEqual([{ type: 'ready' }, { type: 'exit', exit_code: 0 }]);
});
