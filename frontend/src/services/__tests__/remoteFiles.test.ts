import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { createHash } from 'node:crypto';
import { File as NodeFile } from 'node:buffer';
import { encodeFileChunk, FILE_CHUNK, MAX_FILE_SIZE } from '../remoteFiles';
import { RemoteFileQueue } from '../remoteFileQueue';

beforeEach(() => vi.useFakeTimers());
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
const file = (size: number, name = '中文.txt') => new NodeFile([new Uint8Array(size).fill(97)], name) as unknown as File;
const ok = (value: unknown) => new Response(JSON.stringify(value), { headers: { 'Content-Type': 'application/json' } });

it('hashes and reads only one bounded slice, including the final remainder, over HTTP', async () => {
  const source = file(FILE_CHUNK + 3);
  const slice = vi.spyOn(source, 'slice');
  const first = await encodeFileChunk(source, 0);
  const last = await encodeFileChunk(source, FILE_CHUNK);
  expect(atob(first.data).length).toBe(FILE_CHUNK);
  expect(atob(last.data)).toBe('aaa');
  expect(last.sha256).toBe(createHash('sha256').update('aaa').digest('hex'));
  expect(slice.mock.calls).toEqual([[0, FILE_CHUNK], [FILE_CHUNK, FILE_CHUNK * 2]]);
});

it('retries a lost chunk acknowledgment with its original key, never appending duplicate data', async () => {
  let offset = 0; let lost = false;
  const chunks: { offset: number; key: string }[] = [];
  const request = vi.fn(async (url: string, options: RequestInit) => {
    const body = options.body ? JSON.parse(String(options.body)) : {};
    if (url.endsWith('/chunk/')) {
      chunks.push({ offset: body.offset, key: (options.headers as Record<string, string>)['Idempotency-Key'] });
      offset = Math.max(offset, body.offset + atob(body.data).length);
      if (!lost) { lost = true; throw new TypeError('Disconnected after commit'); }
    }
    return ok({ id: 'a'.repeat(32), direction: 'upload', name: '中文 (1).txt', size: FILE_CHUNK + 3, offset,
      state: url.endsWith('/complete/') ? 'completed' : 'transferring' });
  });
  vi.stubGlobal('fetch', request);
  const queue = new RemoteFileQueue('computer-a');
  queue.add('upload', '/home', '中文.txt', FILE_CHUNK + 3, file(FILE_CHUNK + 3));
  await vi.advanceTimersByTimeAsync(3000);
  expect(chunks.map(chunk => chunk.offset)).toEqual([0, 0, FILE_CHUNK]);
  expect(chunks[0].key).toBe(chunks[1].key);
  expect(chunks[2].key).not.toBe(chunks[1].key);
  expect(queue.getSnapshot()[0]).toMatchObject({ status: 'completed', name: '中文 (1).txt', offset: FILE_CHUNK + 3, file: undefined });
  queue.dispose();
});

it('limits two uploads per computer, retains work without subscribers and cancels queued files', async () => {
  const request = vi.fn((_url: string, _options: RequestInit) => new Promise<Response>(() => undefined));
  vi.stubGlobal('fetch', request);
  const queue = new RemoteFileQueue('a');
  const other = new RemoteFileQueue('b');
  const unsubscribe = queue.subscribe(vi.fn());
  for (let i = 0; i < 3; i++) queue.add('upload', '/home', `${i}.txt`, 1, file(1));
  unsubscribe();
  other.add('upload', '/home', 'other.txt', 1, file(1));
  expect(request).toHaveBeenCalledTimes(3);
  expect(request.mock.calls.map(call => String(call[0]))).toEqual([
    expect.stringContaining('/devices/a/'), expect.stringContaining('/devices/a/'), expect.stringContaining('/devices/b/'),
  ]);
  const pending = queue.getSnapshot()[2];
  expect(pending.status).toBe('queued');
  queue.cancel(pending.key);
  expect(queue.getSnapshot()[2]).toMatchObject({ status: 'cancelled', file: undefined });
  expect(() => queue.add('upload', '/home', 'huge', MAX_FILE_SIZE + 1)).toThrow('2 GiB');
  queue.dispose(); other.dispose();
});

it('queries the computer offset on manual retry and stops on permission denial', async () => {
  let denied = true;
  const offsets: number[] = [];
  vi.stubGlobal('fetch', vi.fn(async (url: string, options: RequestInit) => {
    if (url.endsWith('/chunk/')) {
      const body = JSON.parse(String(options.body)); offsets.push(body.offset);
      if (denied) return new Response(JSON.stringify({ detail: '权限关闭' }), { status: 403 });
    }
    return ok({ id: 'b'.repeat(32), direction: 'upload', name: 'x', size: FILE_CHUNK + 3,
      offset: url.includes('/transfers/') ? FILE_CHUNK : url.endsWith('/chunk/') ? FILE_CHUNK + 3 : 0,
      state: url.endsWith('/complete/') ? 'completed' : 'transferring' });
  }));
  const queue = new RemoteFileQueue('a');
  queue.add('upload', '/', 'x', FILE_CHUNK + 3, file(FILE_CHUNK + 3));
  await vi.advanceTimersByTimeAsync(50);
  expect(queue.getSnapshot()[0]).toMatchObject({ status: 'failed', detail: '权限关闭' });
  denied = false; queue.retry(queue.getSnapshot()[0].key);
  await vi.advanceTimersByTimeAsync(50);
  expect(offsets).toEqual([0, FILE_CHUNK]);
  expect(queue.getSnapshot()[0].status).toBe('completed');
  queue.dispose();
});

it('cancels after an in-flight creation settles and never starts sending file content', async () => {
  let created!: (value: Response) => void;
  const request = vi.fn((url: string) => url.endsWith('/uploads/') ? new Promise<Response>(resolve => { created = resolve; }) : Promise.resolve(ok({})));
  vi.stubGlobal('fetch', request);
  const queue = new RemoteFileQueue('computer');
  queue.add('upload', '/', 'cancel.txt', 1, file(1));
  queue.cancel(queue.getSnapshot()[0].key);
  expect(queue.getSnapshot()[0].status).toBe('cancelling');
  created(ok({ id: 'c'.repeat(32), state: 'ready', offset: 0 }));
  await vi.advanceTimersByTimeAsync(1);
  expect(request.mock.calls.map(call => call[0])).toEqual([
    expect.stringContaining('/uploads/'), expect.stringContaining('/transfers/' + 'c'.repeat(32) + '/cancel/'),
  ]);
  expect(queue.getSnapshot()[0]).toMatchObject({ status: 'cancelled', file: undefined });
  queue.dispose();
});

it('discovers orphaned tasks after reload for cancellation without uploading unavailable files', async () => {
  const request = vi.fn(async (url: string) => url.endsWith('/transfers/') ? ok({ transfers: [
    { id: 'd'.repeat(32), direction: 'upload', name: 'orphan', path: '/', size: 1, offset: 0, state: 'ready' },
  ] }) : new Response(JSON.stringify({ detail: 'Already removed' }), { status: 404 }));
  vi.stubGlobal('fetch', request);
  const queue = new RemoteFileQueue('computer');
  await queue.discover(); await queue.discover();
  expect(queue.getSnapshot()).toHaveLength(1);
  expect(queue.getSnapshot()[0]).toMatchObject({ recovered: true, status: 'failed', name: 'orphan' });
  queue.cancel(queue.getSnapshot()[0].key);
  await vi.advanceTimersByTimeAsync(1);
  expect(queue.getSnapshot()[0].status).toBe('cancelled');
  expect(request.mock.calls.some(call => call[0].includes('/uploads/'))).toBe(false);
  queue.dispose();
});

it('allows cancelling an unsuccessful creation when the file has disappeared', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ detail: 'File missing' }), { status: 404 })));
  const queue = new RemoteFileQueue('computer');
  queue.add('download', '/missing', 'missing', 1);
  await vi.advanceTimersByTimeAsync(1);
  expect(queue.getSnapshot()[0].status).toBe('failed');
  queue.cancel(queue.getSnapshot()[0].key);
  await vi.advanceTimersByTimeAsync(1);
  expect(queue.getSnapshot()[0].status).toBe('cancelled');
  queue.dispose();
});
