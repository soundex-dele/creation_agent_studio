import { ReactNode, useEffect, useState } from 'react';
import { Button, Drawer } from 'antd';
import { HistoryOutlined } from '@ant-design/icons';
import { useLocation } from 'react-router-dom';
import Header from '../components/Header/Header';
import Sidebar, { hasSidebarContent } from '../components/Sidebar/Sidebar';
import MobileNavigation from '../components/Navigation/MobileNavigation';
import useMediaQuery from '../hooks/useMediaQuery';
import { usePreferencesStore } from '../stores/usePreferencesStore';
import { shouldHideConversationMainNavigation } from './mainLayoutPolicy';
import './MainLayout.css';

interface MainLayoutProps {
  children: ReactNode;
  /** Hide the left sidebar (header + main only), e.g. for a launched app view. */
  hideSidebar?: boolean;
  /** Hide the top header (nav + account) for a fullscreen launched-app view. */
  hideHeader?: boolean;
  /** Let the child own all viewport spacing, e.g. a workflow or embedded app shell. */
  fullBleed?: boolean;
}

const MainLayout: React.FC<MainLayoutProps> = ({
  children,
  hideSidebar,
  hideHeader,
  fullBleed,
}) => {
  const location = useLocation();
  const isMobile = useMediaQuery('(max-width: 767px)');
  const layoutMode = usePreferencesStore((state) => state.layoutMode);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const searchParams = new URLSearchParams(location.search);
  const embedded = searchParams.get('embedded') === '1';
  const standalone = searchParams.get('standalone') === '1';
  const isConversationPage = location.pathname === '/chat';
  const homeAppsInContent = layoutMode === 'left-right' && !isMobile
    && (location.pathname === '/' || location.pathname === '');
  const hideConversationMainNavigation = shouldHideConversationMainNavigation({
    isConversationPage,
    isMobile,
    layoutMode,
  });
  const shouldHideSidebar = Boolean(
    hideSidebar || embedded || (standalone && !isConversationPage) || homeAppsInContent,
  );
  const shouldHideHeader = Boolean(
    hideHeader || embedded || standalone || hideConversationMainNavigation,
  );
  // Chat page needs full-height content without padding
  const ownsPageSpacing = location.pathname === '/' || location.pathname === ''
    || location.pathname === '/chat';
  const shouldUseFullBleed = Boolean(ownsPageSpacing || fullBleed || embedded);
  const hasContextSidebar = !shouldHideSidebar && hasSidebarContent(location.pathname);
  const showContextToolbar = shouldHideHeader && hasContextSidebar && isMobile;
  const isSideNavigation = layoutMode === 'left-right' && !isMobile && !shouldHideHeader;

  useEffect(() => setMobileSidebarOpen(false), [location.pathname, location.search]);

  useEffect(() => {
    if (!isMobile) setMobileSidebarOpen(false);
  }, [isMobile]);

  const layoutClass = [
    'app-layout',
    shouldHideSidebar && 'app-layout--nosidebar',
    shouldHideHeader && 'app-layout--noheader',
    isSideNavigation && 'app-layout--left-right',
    showContextToolbar && 'app-layout--context-toolbar',
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <div className={layoutClass}>
      {!shouldHideHeader && (
        <Header
          sideNavigation={isSideNavigation}
          mobileMenuOpen={mobileSidebarOpen}
          showMobileMenu={hasContextSidebar}
          onMobileMenuClick={() => setMobileSidebarOpen(true)}
        />
      )}
      {showContextToolbar && (
        <div className="app-context-toolbar">
          <Button
            type="text"
            icon={<HistoryOutlined />}
            aria-expanded={mobileSidebarOpen}
            onClick={() => setMobileSidebarOpen(true)}
          >
            {isConversationPage ? '对话历史' : '当前页面导航'}
          </Button>
        </div>
      )}
      {!shouldHideSidebar && !isMobile && <Sidebar />}
      <main className={`app-main ${shouldUseFullBleed ? '' : 'app-main--padded'}`}>
        {children}
      </main>
      {!shouldHideHeader && isMobile && <MobileNavigation />}
      {hasContextSidebar && isMobile && (
        <Drawer
          title={isConversationPage ? '对话历史' : '当前页面导航'}
          placement="left"
          width="min(88vw, 320px)"
          open={mobileSidebarOpen}
          onClose={() => setMobileSidebarOpen(false)}
          rootClassName="app-mobile-sidebar-drawer"
        >
          <Sidebar />
        </Drawer>
      )}
    </div>
  );
};

export default MainLayout;
