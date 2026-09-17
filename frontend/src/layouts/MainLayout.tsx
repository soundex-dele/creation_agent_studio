import { ReactNode, useEffect, useState } from 'react';
import { Drawer } from 'antd';
import { useLocation } from 'react-router-dom';
import Header from '../components/Header/Header';
import Sidebar, { hasSidebarContent } from '../components/Sidebar/Sidebar';
import MobileNavigation from '../components/Navigation/MobileNavigation';
import useMediaQuery from '../hooks/useMediaQuery';

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
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const embedded = new URLSearchParams(location.search).get('embedded') === '1';
  const shouldHideSidebar = Boolean(hideSidebar || embedded);
  const shouldHideHeader = Boolean(hideHeader || embedded);
  // Chat page needs full-height content without padding
  const ownsPageSpacing = location.pathname === '/' || location.pathname === ''
    || location.pathname === '/chat';
  const shouldUseFullBleed = Boolean(ownsPageSpacing || fullBleed || embedded);
  const hasContextSidebar = !shouldHideSidebar && hasSidebarContent(location.pathname);

  useEffect(() => setMobileSidebarOpen(false), [location.pathname, location.search]);

  useEffect(() => {
    if (!isMobile) setMobileSidebarOpen(false);
  }, [isMobile]);

  const layoutClass = [
    'app-layout',
    shouldHideSidebar && 'app-layout--nosidebar',
    shouldHideHeader && 'app-layout--noheader',
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <div className={layoutClass}>
      {!shouldHideHeader && (
        <Header
          mobileMenuOpen={mobileSidebarOpen}
          showMobileMenu={hasContextSidebar}
          onMobileMenuClick={() => setMobileSidebarOpen(true)}
        />
      )}
      {!shouldHideSidebar && !isMobile && <Sidebar />}
      <main className={`app-main ${shouldUseFullBleed ? '' : 'app-main--padded'}`}>
        {children}
      </main>
      {!shouldHideHeader && isMobile && <MobileNavigation />}
      {hasContextSidebar && isMobile && (
        <Drawer
          title="当前页面导航"
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
