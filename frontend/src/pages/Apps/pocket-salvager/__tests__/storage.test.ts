// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { readPreferences, savePreferences, storageKey } from '../storage';
afterEach(() => { localStorage.clear(); vi.restoreAllMocks(); });
describe('local game preferences', () => {
  it('isolates organizations, players, and applications', () => {
    const key = storageKey('org', 'user', 'app');
    expect(savePreferences(key, { best: 4000, sound: false })).toBe(true);
    expect(readPreferences(key)).toEqual({ best: 4000, sound: false });
    expect(readPreferences(storageKey('other', 'user', 'app')).best).toBe(0);
    expect(readPreferences(storageKey('org', 'other', 'app')).best).toBe(0);
    expect(readPreferences(storageKey('org', 'user', 'other')).best).toBe(0);
  });
  it('handles corrupt and unavailable storage without preventing play', () => {
    localStorage.setItem('test', '{oops'); expect(readPreferences('test').best).toBe(0);
    localStorage.setItem('test', '{"best":-9}'); expect(readPreferences('test').best).toBe(0);
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('QuotaExceeded'); });
    expect(savePreferences('test', { best: 30, sound: true })).toBe(false);
  });
});
