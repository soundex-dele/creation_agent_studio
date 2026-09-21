import { describe, expect, it } from 'vitest';
import { shouldHideConversationMainNavigation } from '../mainLayoutPolicy';

describe('main layout navigation policy', () => {
  it('hides the main navigation for desktop conversations in left-right layout', () => {
    expect(shouldHideConversationMainNavigation({
      isConversationPage: true,
      isMobile: false,
      layoutMode: 'left-right',
    })).toBe(true);
  });

  it.each([
    { isConversationPage: true, isMobile: false, layoutMode: 'top-bottom' as const },
    { isConversationPage: true, isMobile: true, layoutMode: 'left-right' as const },
    { isConversationPage: false, isMobile: false, layoutMode: 'left-right' as const },
  ])('keeps the main navigation outside that layout', (options) => {
    expect(shouldHideConversationMainNavigation(options)).toBe(false);
  });
});
