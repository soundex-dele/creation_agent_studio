import { afterEach, describe, expect, it, vi } from 'vitest';
import { DriveTransfers, sha256 } from '../driveTransfers';
import type { DriveClient, DriveUpload } from '../myDrive';

const file = () => new File(['abcdefgh'], 'video.mp4', { lastModified: 100 });
const upload = (id = '1'): DriveUpload => ({ id, parent: null, entry: null, name: 'video.mp4', size: 8, last_modified: 100, offset: 0, chunk_size: 4, state: 'uploading', updated_at: '' });
function setup(initial = upload()) {
  const client: DriveClient = {
    list: vi.fn(), folder: vi.fn(), action: vi.fn(), access: vi.fn(),
    uploads: vi.fn().mockResolvedValue({ results: [initial], count: 1, next: null }),
    createUpload: vi.fn().mockResolvedValue(initial), upload: vi.fn().mockResolvedValue(initial),
    chunk: vi.fn(async (id, offset, _hash, data) => ({ ...initial, id, offset: offset + data.size })),
    complete: vi.fn().mockResolvedValue({ ...initial, offset: 8, state: 'completed', entry: 'file-1' }),
    cancel: vi.fn().mockResolvedValue({ ...initial, state: 'cancelling' }),
  };
  const changed = vi.fn(), completed = vi.fn();
  const manager = new DriveTransfers(client, changed, completed);
  return { client, manager, changed, completed };
}
afterEach(() => vi.restoreAllMocks());

describe('resumable drive transfers', () => {
  it('uploads bounded chunks in order and completes', async () => {
    const { client, manager, completed } = setup();
    await manager.add(file(), null);
    await vi.waitFor(() => expect(manager.tasks[0].status).toBe('completed'));
    expect(vi.mocked(client.chunk).mock.calls.map((args) => args[1])).toEqual([0, 4]);
    expect(client.chunk).toHaveBeenCalledWith('1', 0, await sha256(new Blob(['abcd'])), expect.any(Blob), expect.any(AbortSignal));
    expect(completed).toHaveBeenCalledOnce();
    expect(manager.tasks[0].file).toBeUndefined();
    manager.dispose();
  });

  it('restores server sessions, verifies original chunks and resumes confirmed offset', async () => {
    const initial = { ...upload(), offset: 4, chunks: [{ offset: 0, size: 4, sha256: await sha256(new Blob(['abcd'])) }] };
    const { client, manager } = setup(initial);
    await manager.load();
    expect(manager.tasks[0].status).toBe('paused');
    expect(() => manager.resume('1')).toThrow('原文件');
    manager.resume('1', file());
    await vi.waitFor(() => expect(manager.tasks[0].status).toBe('completed'));
    expect(client.chunk).toHaveBeenCalledTimes(1);
    expect(vi.mocked(client.chunk).mock.calls[0][1]).toBe(4);
    manager.dispose();
  });

  it('rejects a changed original despite matching file metadata', async () => {
    const initial = { ...upload(), offset: 4, chunks: [{ offset: 0, size: 4, sha256: await sha256(new Blob(['abcd'])) }] };
    const { client, manager } = setup(initial);
    await manager.load(); manager.resume('1', new File(['xxxxefgh'], 'video.mp4', { lastModified: 100 }));
    await vi.waitFor(() => expect(manager.tasks[0].status).toBe('error'));
    expect(manager.tasks[0].error).toContain('内容已变化');
    expect(client.chunk).not.toHaveBeenCalled();
    manager.dispose();
  });

  it('pauses requests and continues using refreshed server progress', async () => {
    const { client, manager } = setup();
    vi.mocked(client.chunk).mockImplementationOnce((_id, _offset, _hash, _data, signal) => new Promise((_, reject) => signal?.addEventListener('abort', () => reject(new Error('aborted')))));
    await manager.add(file(), null);
    await vi.waitFor(() => expect(client.chunk).toHaveBeenCalledOnce());
    manager.pause('1');
    expect(manager.tasks[0].status).toBe('paused');
    manager.resume('1');
    await vi.waitFor(() => expect(manager.tasks[0].status).toBe('completed'));
    expect(client.upload).toHaveBeenCalledTimes(2);
    manager.dispose();
  });

  it('limits concurrent files to three and cancellation advances the queue', async () => {
    const { client, manager } = setup();
    let id = 0;
    vi.mocked(client.createUpload).mockImplementation(async () => upload(String(++id)));
    vi.mocked(client.upload).mockImplementation(async (pk) => upload(pk));
    vi.mocked(client.chunk).mockImplementation((_id, _offset, _hash, _data, signal) => new Promise((_, reject) => signal?.addEventListener('abort', () => reject(new Error('aborted')))));
    await Promise.all([1, 2, 3, 4].map(() => manager.add(file(), null)));
    await vi.waitFor(() => expect(client.chunk).toHaveBeenCalledTimes(3));
    expect(manager.tasks.filter((task) => task.status === 'queued')).toHaveLength(1);
    await manager.cancel('1');
    await vi.waitFor(() => expect(client.chunk).toHaveBeenCalledTimes(4));
    manager.dispose();
  });

  it('reports failure, allows retry and refreshes cleanup status', async () => {
    const { client, manager } = setup();
    vi.mocked(client.chunk).mockRejectedValueOnce({ response: { status: 400, data: { detail: '分片错误' } } });
    await manager.add(file(), null);
    await vi.waitFor(() => expect(manager.tasks[0].status).toBe('error'));
    expect(manager.tasks[0].error).toBe('分片错误');
    manager.resume('1');
    await vi.waitFor(() => expect(manager.tasks[0].status).toBe('completed'));
    manager.dispose();
  });
});
