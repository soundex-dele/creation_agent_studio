import type { LayoutMode } from '@/stores/usePreferencesStore';

interface ConversationNavigationPolicyOptions {
  isConversationPage: boolean;
  isMobile: boolean;
  layoutMode: LayoutMode;
}

export const shouldHideConversationMainNavigation = ({
  isConversationPage,
  isMobile,
  layoutMode,
}: ConversationNavigationPolicyOptions) => (
  isConversationPage && layoutMode === 'left-right' && !isMobile
);
