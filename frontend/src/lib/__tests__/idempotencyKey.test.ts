import { afterEach, describe, expect, it, vi } from 'vitest';

import { createIdempotencyKey } from '../idempotencyKey';

describe('createIdempotencyKey', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('uses crypto.randomUUID when the browser provides it', () => {
    const randomUUID = vi.fn(() => '550e8400-e29b-41d4-a716-446655440000');
    vi.stubGlobal('crypto', { randomUUID });

    expect(createIdempotencyKey('chat')).toBe('550e8400-e29b-41d4-a716-446655440000');
    expect(randomUUID).toHaveBeenCalledOnce();
  });

  it('falls back when randomUUID is unavailable in an insecure mobile context', () => {
    vi.stubGlobal('crypto', {});
    vi.spyOn(Date, 'now').mockReturnValue(1_700_000_000_000);
    vi.spyOn(Math, 'random').mockReturnValue(0.5);

    const key = createIdempotencyKey('chat');

    expect(key).toMatch(/^chat-loyw3v28-[0-9a-z]+-i$/);
    expect(key.length).toBeLessThanOrEqual(160);
  });

  it('falls back when a browser exposes randomUUID but calling it throws', () => {
    vi.stubGlobal('crypto', {
      randomUUID: () => {
        throw new Error('Secure context required');
      },
    });

    expect(createIdempotencyKey('chat')).toMatch(/^chat-[0-9a-z]+-[0-9a-z]+-[0-9a-z]+$/);
  });
});
