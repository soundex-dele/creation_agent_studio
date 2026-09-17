import { useEffect, useState } from 'react';
import { Drawer } from 'antd';
import { EllipsisOutlined } from '@ant-design/icons';
import { useLocation, useNavigate } from 'react-router-dom';
import { usePreferencesStore } from '@/stores/usePreferencesStore';
import { HEADER_NAV_ITEMS } from '@/components/Header/headerNavigation';
import { getNavigationIconComponent } from '@/components/Header/navigationIconComponents';
import './MobileNavigation.css';

const PRIMARY_ITEM_IDS = new Set(['home', 'chat', 'apps', 'workflows']);
const primaryItems = HEADER_NAV_ITEMS.filter((item) => PRIMARY_ITEM_IDS.has(item.id));
const moreItems = HEADER_NAV_ITEMS.filter((item) => !PRIMARY_ITEM_IDS.has(item.id));

const isItemActive = (itemPath: string, currentPath: string) => {
  if (itemPath === '/') return currentPath === '/';
  if (itemPath === '/apps') {
    return currentPath.startsWith('/apps')
      || currentPath.startsWith('/applications')
      || currentPath.startsWith('/workspace');
  }
  return currentPath.startsWith(itemPath);
};

const MobileNavigation = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const navigationIcons = usePreferencesStore((state) => state.navigationIcons);
  const [moreOpen, setMoreOpen] = useState(false);

  useEffect(() => setMoreOpen(false), [location.pathname, location.search]);

  const goTo = (path: string) => {
    setMoreOpen(false);
    navigate(path);
  };

  const moreActive = moreItems.some((item) => isItemActive(item.path, location.pathname));

  return (
    <>
      <nav className="mobile-navigation" aria-label="移动端主导航">
        {primaryItems.map((item) => {
          const active = isItemActive(item.path, location.pathname);
          const Icon = getNavigationIconComponent(
            navigationIcons[item.id] ?? item.defaultIcon,
          );
          return (
            <button
              type="button"
              key={item.id}
              className={`mobile-navigation-item${active ? ' active' : ''}`}
              aria-current={active ? 'page' : undefined}
              onClick={() => goTo(item.path)}
            >
              <Icon aria-hidden="true" />
              <span>{item.label}</span>
            </button>
          );
        })}
        <button
          type="button"
          className={`mobile-navigation-item${moreActive ? ' active' : ''}`}
          aria-expanded={moreOpen}
          aria-controls="mobile-more-navigation"
          onClick={() => setMoreOpen(true)}
        >
          <EllipsisOutlined aria-hidden="true" />
          <span>更多</span>
        </button>
      </nav>

      <Drawer
        id="mobile-more-navigation"
        title="更多功能"
        placement="bottom"
        height="auto"
        open={moreOpen}
        onClose={() => setMoreOpen(false)}
        rootClassName="mobile-more-drawer"
      >
        <div className="mobile-more-grid">
          {moreItems.map((item) => {
            const active = isItemActive(item.path, location.pathname);
            const Icon = getNavigationIconComponent(
              navigationIcons[item.id] ?? item.defaultIcon,
            );
            return (
              <button
                type="button"
                key={item.id}
                className={`mobile-more-item${active ? ' active' : ''}`}
                aria-current={active ? 'page' : undefined}
                onClick={() => goTo(item.path)}
              >
                <Icon aria-hidden="true" />
                <span>{item.label}</span>
              </button>
            );
          })}
        </div>
      </Drawer>
    </>
  );
};

export default MobileNavigation;
