import { ReactNode } from 'react';
import { useLocation } from 'react-router-dom';
import Header from '../components/Header/Header';
import Sidebar from '../components/Sidebar/Sidebar';

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
  const embedded = new URLSearchParams(location.search).get('embedded') === '1';
  const shouldHideSidebar = Boolean(hideSidebar || embedded);
  const shouldHideHeader = Boolean(hideHeader || embedded);
  // Chat page needs full-height content without padding
  const ownsPageSpacing = location.pathname === '/' || location.pathname === ''
    || location.pathname === '/chat';
  const shouldUseFullBleed = Boolean(ownsPageSpacing || fullBleed || embedded);

  const layoutClass = [
    'app-layout',
    shouldHideSidebar && 'app-layout--nosidebar',
    shouldHideHeader && 'app-layout--noheader',
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <div className={layoutClass}>
      {!shouldHideHeader && <Header />}
      {!shouldHideSidebar && <Sidebar />}
      <main className={`app-main ${shouldUseFullBleed ? '' : 'app-main--padded'}`}>
        {children}
      </main>
    </div>
  );
};

export default MainLayout;
