import React, { useEffect, useMemo, useRef, type CSSProperties } from 'react';
import { Button, Empty, Spin } from 'antd';
import { AppstoreOutlined, MessageOutlined } from '@ant-design/icons';
import { useLocation, useNavigate } from 'react-router-dom';
import { applicationPath } from '@/lib/applicationCatalog';
import { applicationWindowPath } from '@/lib/applicationPresentation';
import ApplicationIcon from '@/components/ApplicationIcon';
import { scrollHorizontalWithWheel } from '@/lib/horizontalWheelScroll';
import { useAppStore } from '@/stores/useAppStore';
import { useApplicationPreferences } from '@/hooks/useApplicationPreferences';
import { usePreferencesStore } from '@/stores/usePreferencesStore';
import type { AppItem } from '@/types';
import { CONVERSATION_APP, CONVERSATION_APP_ID, isCoworkApplication } from '@/lib/conversationApplication';

interface HomeApplicationsSidebarProps {
  horizontalWheelScroll?: boolean;
}

const HomeApplicationsSidebar: React.FC<HomeApplicationsSidebarProps> = ({
  horizontalWheelScroll = false,
}) => {
  const navigate = useNavigate();
  const location = useLocation();
  const layoutMode = usePreferencesStore((state) => state.layoutMode);
  const openInNewWindow = layoutMode === 'left-right'
    && (location.pathname === '/' || location.pathname === '');
  const { apps, isLoading, error, loadApps, setSearchQuery } = useAppStore();
  const { preferences, recordUsage } = useApplicationPreferences();
  const applicationListRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setSearchQuery('');
    void loadApps();
  }, [loadApps, setSearchQuery]);

  const recentApps = useMemo(() => (
    [CONVERSATION_APP, ...apps.filter(app => !isCoworkApplication(app))]
      .filter(app => preferences.recent[app.id] > 0)
      .sort((left, right) => preferences.recent[right.id] - preferences.recent[left.id])
  ), [apps, preferences.recent]);

  useEffect(() => {
    const applicationList = applicationListRef.current;
    if (!horizontalWheelScroll || !applicationList) return undefined;
    const handleWheel = (event: WheelEvent) => {
      if (event.ctrlKey) return;
      if (scrollHorizontalWithWheel(applicationList, event)) event.preventDefault();
    };
    applicationList.addEventListener('wheel', handleWheel, { passive: false });
    return () => applicationList.removeEventListener('wheel', handleWheel);
  }, [horizontalWheelScroll, isLoading, error, recentApps.length]);

  const homeApplicationPath = (app: AppItem) => app.id === CONVERSATION_APP_ID
    ? '/chat?entry=home'
    : applicationPath(app, 'home');

  const openApplication = (app: AppItem) => {
    const path = homeApplicationPath(app);
    recordUsage(app.id);
    if (openInNewWindow) {
      window.open(applicationWindowPath(path), '_blank', 'noopener,noreferrer');
      return;
    }
    navigate(path);
  };

  const isActiveApplication = (app: AppItem) => {
    const runtimePath = homeApplicationPath(app).split('?')[0];
    return location.pathname === runtimePath || location.pathname.startsWith(`${runtimePath}/`);
  };

  return (
    <div className="home-app-sidebar">
      <div className="home-app-sidebar-head">
        <div>
          <div className="sidebar-title">最近使用</div>
          <p>{openInNewWindow ? '按最近打开排序 · 在新窗口打开' : '按最近打开排序'}</p>
        </div>
      </div>

      {isLoading && apps.length === 0 ? (
        <div className="home-app-sidebar-state"><Spin size="small" /></div>
      ) : error ? (
        <div className="home-app-sidebar-state" role="alert">
          <p>应用加载失败，请重试</p>
          <Button onClick={() => void loadApps()}>重试</Button>
        </div>
      ) : recentApps.length === 0 ? (
        <div className="home-app-sidebar-state">
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无最近使用的应用，打开应用后会显示在这里" />
        </div>
      ) : (
        <div ref={applicationListRef} className="home-app-list" aria-label="最近使用的应用">
          {recentApps.map((app) => (
            <button
              type="button"
              key={app.id}
              className={`home-app-item ${isActiveApplication(app) ? 'active' : ''}`}
              style={{ '--app-accent': app.color || 'var(--color-primary)' } as CSSProperties}
              aria-current={isActiveApplication(app) ? 'page' : undefined}
              aria-label={openInNewWindow ? `${app.name}（在新窗口打开）` : app.name}
              title={app.name}
              onClick={() => openApplication(app)}
            >
              <span className="home-app-icon" aria-hidden="true">
                {app.id === CONVERSATION_APP_ID ? <MessageOutlined /> : <ApplicationIcon app={app} />}
              </span>
              <span className="home-app-copy"><strong>{app.name}</strong><small>{app.description}</small></span>
            </button>
          ))}
        </div>
      )}

      <button type="button" className="home-all-apps" onClick={() => navigate('/apps')}>
        <AppstoreOutlined aria-hidden="true" /> 查看全部应用
      </button>
    </div>
  );
};

export default HomeApplicationsSidebar;
