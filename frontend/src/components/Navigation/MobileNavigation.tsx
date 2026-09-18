import { useLocation, useNavigate } from 'react-router-dom';
import { usePreferencesStore } from '@/stores/usePreferencesStore';
import {
  HEADER_NAV_ITEMS,
  isHeaderNavigationItemActive,
} from '@/components/Header/headerNavigation';
import { getNavigationIconComponent } from '@/components/Header/navigationIconComponents';
import './MobileNavigation.css';

const MobileNavigation = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const navigationIcons = usePreferencesStore((state) => state.navigationIcons);

  const goTo = (path: string) => {
    navigate(path);
  };

  return (
    <nav className="mobile-navigation" aria-label="移动端主导航">
      {HEADER_NAV_ITEMS.map((item) => {
        const active = isHeaderNavigationItemActive(
          item,
          location.pathname,
          location.search,
        );
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
    </nav>
  );
};

export default MobileNavigation;
