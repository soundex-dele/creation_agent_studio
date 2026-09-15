import { describe, expect, it } from 'vitest';
import { categoryIcon } from '../categoryIcons';

describe('categoryIcon', () => {
  it('replaces backend English identifiers with display icons', () => {
    expect(categoryIcon('chat', 'chat', 'application')).toBe('💬');
    expect(categoryIcon('edit', 'creative', 'application')).toBe('✍️');
  });

  it('preserves display icons and supplies domain defaults', () => {
    expect(categoryIcon('🎬', 'video', 'agent')).toBe('🎬');
    expect(categoryIcon('', 'unknown', 'agent')).toBe('🤖');
    expect(categoryIcon(undefined, 'unknown', 'application')).toBe('🧩');
  });
});
