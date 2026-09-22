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
    { isConversationPage: false, isMobile: false, layoutMode: 'left-right' as const },
    { isConversationPage: false, isMobile: true, layoutMode: 'left-right' as const },
    { isConversationPage: false, isMobile: true, layoutMode: 'top-bottom' as const },
    { isConversationPage: false, isRemoteConversationPage: true, isMobile: false, layoutMode: 'left-right' as const },
    { isConversationPage: false, isRemoteConversationPage: true, isMobile: false, layoutMode: 'top-bottom' as const },
  ])('keeps the main navigation outside that layout', (options) => {
    expect(shouldHideConversationMainNavigation(options)).toBe(false);
  });

  it.each(['left-right', 'top-bottom'] as const)('hides mobile navigation in local and remote conversations with %s layout', (layoutMode) => {
    expect(shouldHideConversationMainNavigation({
      isConversationPage: true, isMobile: true, layoutMode,
    })).toBe(true);
    expect(shouldHideConversationMainNavigation({
      isConversationPage: false, isRemoteConversationPage: true, isMobile: true, layoutMode,
    })).toBe(true);
  });
});
