import { describe, expect, it } from 'vitest';

import { guidedPromptIdentifier } from '@/lib/guidedPrompts';

describe('guidedPromptIdentifier', () => {
  it('uses the prompt id when the API provides one', () => {
    expect(guidedPromptIdentifier({ id: '42', key: 'illustrate-article' })).toBe('42');
  });

  it('falls back to the package key when the prompt has no id', () => {
    expect(guidedPromptIdentifier({ key: 'illustrate-article' })).toBe('illustrate-article');
  });
});
