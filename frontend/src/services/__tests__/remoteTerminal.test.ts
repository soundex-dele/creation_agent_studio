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
  const input = new TerminalInput('computer', 'session', vi.fn());
  input.setOnline(true); input.write('a');
  await vi.advanceTimersByTimeAsync(25);
  input.write('b'); input.setOnline(false); input.write('offline');
  resolve({}); await vi.advanceTimersByTimeAsync(30);
  expect(post).toHaveBeenCalledTimes(1);
  input.setOnline(true); input.write('a'); await vi.advanceTimersByTimeAsync(25);
  expect(post.mock.calls.map(call => call[1])).toEqual([
    { client_id: expect.any(String), sequence: 1, data: 'a' },
    { client_id: expect.any(String), sequence: 2, data: 'a' },
  ]);
  input.dispose();
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
