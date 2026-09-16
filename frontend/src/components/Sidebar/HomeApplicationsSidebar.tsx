import React, { useEffect, useMemo, useState, type CSSProperties } from 'react';
import { Button, Checkbox, Empty, Modal, Spin } from 'antd';
import {
  ArrowDownOutlined,
  ArrowUpOutlined,
  AppstoreOutlined,
  SettingOutlined,
} from '@ant-design/icons';
import { useLocation, useNavigate } from 'react-router-dom';
import { applicationPath } from '@/lib/applicationCatalog';
import { useAppStore } from '@/stores/useAppStore';
import { useAuthStore } from '@/stores/useAuthStore';

interface HomeApplicationPreferences {
  order: string[];
  hidden: string[];
}

const EMPTY_PREFERENCES: HomeApplicationPreferences = { order: [], hidden: [] };

const HomeApplicationsSidebar: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const userId = useAuthStore((state) => state.user?.id || 'anonymous');
  const { apps, isLoading, loadApps, setSearchQuery } = useAppStore();
  const [isConfiguring, setIsConfiguring] = useState(false);
  const [preferences, setPreferences] = useState<HomeApplicationPreferences>(EMPTY_PREFERENCES);
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

  const orderedApps = useMemo(() => {
    const positions = new Map(preferences.order.map((id, index) => [id, index]));
    return [...apps].sort((left, right) => {
      const leftPosition = positions.get(left.id) ?? Number.MAX_SAFE_INTEGER;
      const rightPosition = positions.get(right.id) ?? Number.MAX_SAFE_INTEGER;
      return leftPosition - rightPosition;
    });
  }, [apps, preferences.order]);

  const visibleApps = orderedApps.filter((app) => !preferences.hidden.includes(app.id));

  const isActiveApplication = (app: (typeof apps)[number]) => {
    const runtimePath = applicationPath(app, 'home').split('?')[0];
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
          <p>选择应用即可开始</p>
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
        <div className="home-app-list">
          {visibleApps.map((app) => (
            <button
              key={app.id}
              className={`home-app-item ${isActiveApplication(app) ? 'active' : ''}`}
              style={{ '--app-accent': app.color || 'var(--color-primary)' } as CSSProperties}
              aria-current={isActiveApplication(app) ? 'page' : undefined}
              onClick={() => navigate(applicationPath(app, 'home'))}
            >
              <span className="home-app-icon">{app.icon || <AppstoreOutlined />}</span>
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
        <p className="home-app-config-help">选择要在首页侧边栏显示的应用，并调整顺序。配置仅对当前用户生效。</p>
        <div className="home-app-config-list">
          {orderedApps.map((app, index) => (
            <div className="home-app-config-item" key={app.id}>
              <Checkbox checked={!preferences.hidden.includes(app.id)} onChange={(event) => toggle(app.id, event.target.checked)}>
                <span className="home-app-config-icon">{app.icon}</span>{app.name}
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
