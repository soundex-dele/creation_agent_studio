import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api';
import { repoApi } from '../repoExplainer';

vi.mock('../api', () => ({ api: { post: vi.fn() } }));
beforeEach(() => { vi.mocked(api.post).mockReset().mockResolvedValue({}); });
afterEach(() => vi.unstubAllGlobals());
const key = (i: number) => vi.mocked(api.post).mock.calls[i][2]?.headers?.['Idempotency-Key'];
describe.each(['missing', 'throwing', 'absent'])('repo workflows with crypto %s', mode => {
  beforeEach(() => vi.stubGlobal('crypto', mode === 'absent' ? undefined : mode === 'missing' ? {} : { randomUUID: () => { throw new Error('HTTP'); } }));
  it.each(['import', 'analyze', 'write', 'handoff'])('submits %s, preserves uncertain retries and renews successful requests', async operation => {
    const client = repoApi('/repo');
    const submit = (value = 'first') => operation === 'import' ? client.import('p', { kind: 'github', url: value })
      : operation === 'handoff' ? client.handoff('p', value, 2) : client.task('p', { kind: operation, value });
    vi.mocked(api.post).mockRejectedValueOnce(new Error('network'));
    await expect(submit()).rejects.toThrow();
    await submit(); expect(key(0)).toBeTruthy(); expect(key(1)).toBe(key(0));
    await submit(); expect(key(2)).not.toBe(key(1));
    vi.mocked(api.post).mockRejectedValueOnce(new Error('network'));
    await expect(submit()).rejects.toThrow();
    await submit('changed'); expect(key(4)).not.toBe(key(3));
  });
});
