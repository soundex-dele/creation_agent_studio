import { describe, expect, it } from 'vitest';

import { resolveApiBaseUrl } from '../apiBaseUrl';


describe('resolveApiBaseUrl', () => {
  it('uses the versioned same-origin API gateway by default', () => {
    expect(resolveApiBaseUrl()).toBe('/api/v1');
    expect(resolveApiBaseUrl('')).toBe('/api/v1');
  });

  it('normalizes an explicitly configured gateway', () => {
    expect(resolveApiBaseUrl('http://localhost:8080/api/v1/')).toBe(
      'http://localhost:8080/api/v1',
    );
  });
});
