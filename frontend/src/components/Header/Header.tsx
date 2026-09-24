import React, { useEffect, useState } from 'react';
import { Dropdown, Avatar } from 'antd';
import {
  BankOutlined,
  LogoutOutlined,
  MenuOutlined,
  RightOutlined,
  SettingOutlined,
  TeamOutlined,
  UserOutlined,
} from '@ant-design/icons';
import { useNavigate, useLocation } from 'react-router-dom';
import { useAuthStore } from '@/stores/useAuthStore';
import { usePreferencesStore } from '@/stores/usePreferencesStore';
import { ThemeToggle } from '@/components/Theme';
import {
  HEADER_NAV_ITEMS, SIDE_NAVIGATION_GROUPS, isHeaderNavigationItemActive,
} from './headerNavigation';
import { getNavigationIconComponent } from './navigationIconComponents';
import './Header.css';

interface HeaderProps {
  sideNavigation?: boolean;
  mobileMenuOpen?: boolean;
  onMobileMenuClick?: () => void;
  showMobileMenu?: boolean;
}

const Header: React.FC<HeaderProps> = ({
  sideNavigation = false,
  mobileMenuOpen = false,
  onMobileMenuClick,
  showMobileMenu = false,
}) => {
  const navigate = useNavigate();
  const location = useLocation();
  const { user, logout, isAuthenticated } = useAuthStore();
  const navigationIconMode = usePreferencesStore((state) => state.navigationIconMode);
  const navigationIcons = usePreferencesStore((state) => state.navigationIcons);
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({});

  // Reveal the current destination on direct entry, route changes, or layout switches.
  // Manual collapse remains available until the next navigation.
  useEffect(() => {
    if (!sideNavigation) return;
    const activeGroup = HEADER_NAV_ITEMS.find((item) => (
      SIDE_NAVIGATION_GROUPS[item.id]
      && isHeaderNavigationItemActive(item, location.pathname, location.search)
    ));
    if (activeGroup) {
      setExpandedGroups((groups) => ({ ...groups, [activeGroup.id]: true }));
    }
  }, [sideNavigation, location.pathname, location.search]);

  const handleLogout = async () => {
    await logout();
    navigate('/auth/login');
  };

  const userMenuItems = [
    {
      key: 'profile',
      icon: <UserOutlined />,
      label: '个人中心',
      onClick: () => navigate('/profile'),
    },
    {
      key: 'settings',
      icon: <SettingOutlined />,
      label: '设置',
      onClick: () => navigate('/settings'),
    },
    ...(user?.role === 'admin' ? [{
      key: 'enterprise',
      icon: <BankOutlined />,
      label: '控制台',
      onClick: () => navigate('/enterprise'),
    }] : []),
    ...(user?.role === 'admin' ? [{
      key: 'account-management',
      icon: <TeamOutlined />,
      label: '账号管理',
      onClick: () => navigate('/settings/accounts'),
    }] : []),
    { type: 'divider' as const },
    {
      key: 'logout',
      icon: <LogoutOutlined />,
      label: '登出',
      onClick: handleLogout,
    },
  ];

  const currentPath = location.pathname;

  return (
    <header className={`app-header${showMobileMenu ? ' app-header--with-mobile-menu' : ''}`}>
      {showMobileMenu && (
        <button
          type="button"
          className="header-mobile-menu"
          aria-label="打开当前页面导航"
          aria-expanded={mobileMenuOpen}
          onClick={onMobileMenuClick}
        >
          <MenuOutlined aria-hidden="true" />
        </button>
      )}

      {/* Left: Logo */}
      <button type="button" className="header-logo" onClick={() => navigate('/')}>
        Agent <span>Studio</span>
      </button>

      {/* Center: Nav */}
      <nav className="header-nav" aria-label="主导航">
        {HEADER_NAV_ITEMS.map((item) => {
          const active = isHeaderNavigationItemActive(item, currentPath, location.search);
          const Icon = getNavigationIconComponent(
            navigationIcons[item.id] ?? item.defaultIcon,
          );
          const children = sideNavigation ? SIDE_NAVIGATION_GROUPS[item.id] : undefined;
          const label = <>
            {navigationIconMode === 'outline' && (
              <Icon className="header-nav-icon" aria-hidden="true" />
            )}
            {navigationIconMode === 'emoji' && (
              <span className="header-nav-emoji" aria-hidden="true">{item.emoji}</span>
            )}
            <span>{item.label}</span>
          </>;

          if (children) {
            const expanded = expandedGroups[item.id] ?? active;
            return (
              <div className="header-nav-group" key={item.id}>
                <button
                  type="button"
                  className={`header-nav-item header-nav-group-toggle${active ? ' active' : ''}`}
                  aria-expanded={expanded}
                  aria-controls={`header-nav-group-${item.id}`}
                  onClick={() => setExpandedGroups((groups) => ({
                    ...groups, [item.id]: !expanded,
                  }))}
                >
                  {label}
                  <RightOutlined className="header-nav-chevron" aria-hidden="true" />
                </button>
                <div id={`header-nav-group-${item.id}`} className="header-nav-children" hidden={!expanded}>
                  {children.map((child) => {
                    const selected = currentPath === child.path || currentPath.startsWith(`${child.path}/`);
                    return (
                      <button
                        type="button"
                        key={child.path}
                        className={`header-nav-item header-nav-subitem${selected ? ' active' : ''}`}
                        aria-current={selected ? 'page' : undefined}
                        onClick={() => navigate(child.path)}
                      >
                        {child.label}
                      </button>
                    );
                  })}
                </div>
              </div>
            );
          }

          return (
            <button
              type="button"
              key={item.id}
              className={`header-nav-item${active ? ' active' : ''}`}
              aria-current={active ? 'page' : undefined}
              onClick={() => navigate(item.path)}
            >
              {label}
            </button>
          );
        })}
      </nav>

      {/* Right: User */}
      <div className="header-right">
        {!sideNavigation && <ThemeToggle />}
        {isAuthenticated && (
          <Dropdown menu={{ items: userMenuItems }} placement={sideNavigation ? 'topLeft' : 'bottomRight'}>
            <button type="button" className="header-user" aria-label="打开用户菜单">
              <div className="header-avatar">
                {user?.avatar ? (
                  <Avatar size={32} src={user.avatar} />
                ) : (
                  user?.username?.charAt(0)?.toUpperCase() || 'U'
                )}
              </div>
              <span className="header-username">{user?.username || 'User'}</span>
            </button>
          </Dropdown>
        )}
      </div>
    </header>
  );
};

export default Header;
