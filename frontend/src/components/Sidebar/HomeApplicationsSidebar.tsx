import React, { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import { Button, Checkbox, Empty, Modal, Spin } from 'antd';
import {
  ArrowDownOutlined,
  ArrowUpOutlined,
  AppstoreOutlined,
  MessageOutlined,
  SettingOutlined,
} from '@ant-design/icons';
import { useLocation, useNavigate } from 'react-router-dom';
import { applicationPath } from '@/lib/applicationCatalog';
import { applicationWindowPath } from '@/lib/applicationPresentation';
import ApplicationIcon from '@/components/ApplicationIcon';
import { scrollHorizontalWithWheel } from '@/lib/horizontalWheelScroll';
import { useAppStore } from '@/stores/useAppStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { usePreferencesStore } from '@/stores/usePreferencesStore';
import type { AppItem } from '@/types';

interface HomeApplicationPreferences {
  order: string[];
  hidden: string[];
}

const EMPTY_PREFERENCES: HomeApplicationPreferences = { order: [], hidden: [] };
const CONVERSATION_APP_ID = 'platform-conversation';
const CONVERSATION_APP: AppItem = {
  id: CONVERSATION_APP_ID,
  name: '对话',
  description: '通过持续对话处理日常需求',
  category: 'chat',
  icon: '💬',
  color: '#6d5dfc',
  tags: ['AI 助手', '多轮对话'],
};

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
  const userId = useAuthStore((state) => state.user?.id || 'anonymous');
  const { apps, isLoading, loadApps, setSearchQuery } = useAppStore();
  const [isConfiguring, setIsConfiguring] = useState(false);
  const [preferences, setPreferences] = useState<HomeApplicationPreferences>(EMPTY_PREFERENCES);
  const applicationListRef = useRef<HTMLDivElement>(null);
  const storageKey = `home-applications:${userId}`;

  useEffect(() => {
    setSearchQuery('');
    void loadApps();
  }, [loadApps, setSearchQuery]);

  useEffect(() => {
    try {
      const saved = window.localStorage.getItem(storageKey);
      const parsed = saved ? JSON.parse(saved) as Partial<HomeApplicationPreferences> : null;
      setPreferences({
        order: Array.isArray(parsed?.order) ? parsed.order.filter((id): id is string => typeof id === 'string') : [],
        hidden: Array.isArray(parsed?.hidden) ? parsed.hidden.filter((id): id is string => typeof id === 'string') : [],
      });
    } catch {
      setPreferences(EMPTY_PREFERENCES);
    }
  }, [storageKey]);

  const allApps = useMemo(() => [CONVERSATION_APP, ...apps], [apps]);

  const orderedApps = useMemo(() => {
    const positions = new Map(preferences.order.map((id, index) => [id, index]));
    return [...allApps].sort((left, right) => {
      const leftPosition = positions.get(left.id) ?? Number.MAX_SAFE_INTEGER;
      const rightPosition = positions.get(right.id) ?? Number.MAX_SAFE_INTEGER;
      return leftPosition - rightPosition;
    });
  }, [allApps, preferences.order]);

  const visibleApps = orderedApps.filter((app) => !preferences.hidden.includes(app.id));

  useEffect(() => {
    const applicationList = applicationListRef.current;
    if (!horizontalWheelScroll || !applicationList) return undefined;

    const handleWheel = (event: WheelEvent) => {
      if (event.ctrlKey) return;
      if (scrollHorizontalWithWheel(applicationList, event)) event.preventDefault();
    };

    applicationList.addEventListener('wheel', handleWheel, { passive: false });
    return () => applicationList.removeEventListener('wheel', handleWheel);
  }, [horizontalWheelScroll, isLoading, visibleApps.length]);

  const homeApplicationPath = (app: AppItem) => app.id === CONVERSATION_APP_ID
    ? '/chat?entry=home'
    : applicationPath(app, 'home');

  const openApplication = (app: AppItem) => {
    const path = homeApplicationPath(app);
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

  const save = (next: HomeApplicationPreferences) => {
    setPreferences(next);
    window.localStorage.setItem(storageKey, JSON.stringify(next));
  };

  const toggle = (id: string, visible: boolean) => save({
    ...preferences,
    hidden: visible
      ? preferences.hidden.filter((hiddenId) => hiddenId !== id)
      : [...new Set([...preferences.hidden, id])],
  });

  const move = (id: string, direction: -1 | 1) => {
    const ids = orderedApps.map((app) => app.id);
    const index = ids.indexOf(id);
    const target = index + direction;
    if (target < 0 || target >= ids.length) return;
    [ids[index], ids[target]] = [ids[target], ids[index]];
    save({ ...preferences, order: ids });
  };

  return (
    <div className="home-app-sidebar">
      <div className="home-app-sidebar-head">
        <div>
          <div className="sidebar-title">我的应用</div>
          <p>{openInNewWindow ? '选择应用将在新窗口打开' : '选择应用即可开始'}</p>
        </div>
        <Button
          type="text"
          aria-label="配置首页应用"
          icon={<SettingOutlined />}
          onClick={() => setIsConfiguring(true)}
        />
      </div>

      {isLoading && apps.length === 0 ? (
        <div className="home-app-sidebar-state"><Spin size="small" /></div>
      ) : visibleApps.length === 0 ? (
        <div className="home-app-sidebar-state">
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂未显示应用" />
          <Button type="link" onClick={() => setIsConfiguring(true)}>配置应用</Button>
        </div>
      ) : (
        <div
          ref={applicationListRef}
          className="home-app-list"
        >
          {visibleApps.map((app) => (
            <button
              type="button"
              key={app.id}
              className={`home-app-item ${isActiveApplication(app) ? 'active' : ''}`}
              style={{ '--app-accent': app.color || 'var(--color-primary)' } as CSSProperties}
              aria-current={isActiveApplication(app) ? 'page' : undefined}
              aria-label={openInNewWindow ? `${app.name}（在新窗口打开）` : undefined}
              onClick={() => openApplication(app)}
            >
              <span className="home-app-icon">
                {app.id === CONVERSATION_APP_ID ? <MessageOutlined /> : <ApplicationIcon app={app} />}
              </span>
              <span className="home-app-copy"><strong>{app.name}</strong><small>{app.description}</small></span>
            </button>
          ))}
        </div>
      )}

      <button className="home-all-apps" onClick={() => navigate('/apps')}>
        <AppstoreOutlined /> 查看全部应用
      </button>

      <Modal
        title="配置首页应用"
        open={isConfiguring}
        onCancel={() => setIsConfiguring(false)}
        footer={<Button type="primary" onClick={() => setIsConfiguring(false)}>完成</Button>}
      >
        <p className="home-app-config-help">选择要在工作台显示的应用，并调整顺序。配置仅对当前用户生效。</p>
        <div className="home-app-config-list">
          {orderedApps.map((app, index) => (
            <div className="home-app-config-item" key={app.id}>
              <Checkbox checked={!preferences.hidden.includes(app.id)} onChange={(event) => toggle(app.id, event.target.checked)}>
                <span className="home-app-config-icon"><ApplicationIcon app={app} /></span>{app.name}
              </Checkbox>
              <div>
                <Button type="text" size="small" aria-label={`上移${app.name}`} disabled={index === 0} icon={<ArrowUpOutlined />} onClick={() => move(app.id, -1)} />
                <Button type="text" size="small" aria-label={`下移${app.name}`} disabled={index === orderedApps.length - 1} icon={<ArrowDownOutlined />} onClick={() => move(app.id, 1)} />
              </div>
            </div>
          ))}
        </div>
      </Modal>
    </div>
  );
};

export default HomeApplicationsSidebar;
