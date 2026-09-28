import { webcrypto } from 'node:crypto';
import { afterEach, expect, it, vi } from 'vitest';
import { createUuid } from '../uuid';

afterEach(() => vi.unstubAllGlobals());

it('uses native UUIDs in secure contexts', () => {
  const uuid = '550e8400-e29b-41d4-a716-446655440000';
  vi.stubGlobal('crypto', { randomUUID: () => uuid });
  expect(createUuid()).toBe(uuid);
});

it.each(['missing', 'throws'])('creates distinct valid UUID v4 values when randomUUID %s', mode => {
  vi.stubGlobal('crypto', {
    randomUUID: mode === 'missing' ? undefined : () => { throw new Error('Secure context required'); },
    getRandomValues: webcrypto.getRandomValues.bind(webcrypto),
  });
  const ids = Array.from({ length: 100 }, createUuid);
  expect(new Set(ids).size).toBe(ids.length);
  for (const id of ids) {
    expect(id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  }
});

it('explains when the browser has no random source', () => {
  vi.stubGlobal('crypto', undefined);
  expect(createUuid).toThrow('当前浏览器无法生成操作标识');
});
