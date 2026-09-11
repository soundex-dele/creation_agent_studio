import { describe, expect, it } from 'vitest';

import { resolveApiBaseUrl } from '../apiBaseUrl';


describe('resolveApiBaseUrl', () => {
  it('uses the same-origin /api gateway by default', () => {
    expect(resolveApiBaseUrl()).toBe('/api');
    expect(resolveApiBaseUrl('')).toBe('/api');
  });

  it('normalizes an explicitly configured gateway', () => {
    expect(resolveApiBaseUrl('http://localhost:8080/api/')).toBe(
      'http://localhost:8080/api',
    );
  });
});
