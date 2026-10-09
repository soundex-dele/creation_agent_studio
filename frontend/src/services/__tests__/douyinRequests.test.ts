import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api';
import { douyinApi } from '../douyinBenchmark';
import { researchApi } from '../douyinResearch';

vi.mock('../api', () => ({ api: { post: vi.fn() } }));
beforeEach(() => { vi.mocked(api.post).mockReset().mockResolvedValue({}); });
afterEach(() => { vi.unstubAllGlobals(); });
const keyAt = (index: number) => vi.mocked(api.post).mock.calls[index][2]?.headers?.['Idempotency-Key'];

describe.each(['missing', 'throwing', 'absent'])('Douyin requests with crypto %s', mode => {
  beforeEach(() => {
    vi.stubGlobal('crypto', mode === 'absent' ? undefined : mode === 'missing' ? {} : {
      randomUUID: () => { throw new Error('Insecure context'); },
    });
  });

  it.each(['account', 'task', 'research', 'refresh', 'voice', 'owned-topics', 'article'])('submits %s and keeps the key until success', async operation => {
    const client = douyinApi('/dy');
    const research = researchApi('/dy');
    const submit = () => {
      if (operation === 'account') return client.create({ source: 'https://www.douyin.com/user/test', count: 50, group: '', notes: '' });
      if (operation === 'task') return client.start('a1', { kind: 'collect', count: 50 });
      if (operation === 'research') return research.start({ kind: 'radar', days: 7 });
      if (operation === 'voice') return research.start({ kind: 'voice_analysis', target_account_id: 'a1' });
      if (operation === 'article') return research.start({ kind: 'article', source_task_id: 'topics1', topic_index: 1 });
      if (operation === 'owned-topics') return research.start({ kind: 'topics', target_account_id: 'a1', theme: '' });
      return research.refresh('s1');
    };
    vi.mocked(api.post).mockRejectedValueOnce(new Error('Network Error'));
    await expect(submit()).rejects.toThrow('Network Error');
    const first = keyAt(0);
    expect(first).toEqual(expect.any(String));
    expect(String(first).length).toBeLessThanOrEqual(160);
    await submit();
    expect(keyAt(1)).toBe(first);
    await submit();
    expect(keyAt(2)).not.toBe(first);
    expect(api.post).toHaveBeenCalledTimes(3);
  });

  it('changes the key when the payload changes and isolates account endpoints', async () => {
    const client = douyinApi('/dy');
    vi.mocked(api.post).mockRejectedValue(new Error('Network Error'));
    await client.start('a1', { kind: 'collect', count: 20 }).catch(() => {});
    await client.start('a1', { kind: 'collect', count: 50 }).catch(() => {});
    await client.start('a2', { kind: 'collect', count: 50 }).catch(() => {});
    expect(new Set([keyAt(0), keyAt(1), keyAt(2)]).size).toBe(3);
    await client.start('a1', { kind: 'collect', count: 50 }).catch(() => {});
    expect(keyAt(3)).toBe(keyAt(1));
  });
});

it('does not clear a newer retry key when an older response arrives', async () => {
  const client = douyinApi('/dy');
  let finish!: (value: unknown) => void;
  vi.mocked(api.post).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }))
    .mockRejectedValueOnce(new Error('Network Error'));
  const older = client.start('a1', { kind: 'collect', count: 20 });
  await expect(client.start('a1', { kind: 'collect', count: 50 })).rejects.toThrow();
  finish({});
  await older;
  await client.start('a1', { kind: 'collect', count: 50 });
  expect(keyAt(2)).toBe(keyAt(1));
});
