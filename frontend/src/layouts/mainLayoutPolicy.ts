import type { LayoutMode } from '@/stores/usePreferencesStore';

interface ConversationNavigationPolicyOptions {
  isConversationPage: boolean;
  isRemoteConversationPage?: boolean;
  isMobile: boolean;
  layoutMode: LayoutMode;
}

export const shouldHideConversationMainNavigation = ({
  isConversationPage,
  isRemoteConversationPage = false,
  isMobile,
  layoutMode,
}: ConversationNavigationPolicyOptions) => (
  isMobile
    ? isConversationPage || isRemoteConversationPage
    : isConversationPage && layoutMode === 'left-right'
);
