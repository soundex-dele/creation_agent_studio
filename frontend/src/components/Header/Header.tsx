import React from 'react';
import { Dropdown, Avatar } from 'antd';
import {
  LogoutOutlined,
  SettingOutlined,
  UserOutlined,
} from '@ant-design/icons';
import { useNavigate, useLocation } from 'react-router-dom';
import { useAuthStore } from '@/stores/useAuthStore';
import { usePreferencesStore } from '@/stores/usePreferencesStore';
import { ThemeToggle } from '@/components/Theme';
import { HEADER_NAV_ITEMS } from './headerNavigation';
import { getNavigationIconComponent } from './navigationIconComponents';
import './Header.css';

const Header: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { user, logout, isAuthenticated } = useAuthStore();
  const navigationIconMode = usePreferencesStore((state) => state.navigationIconMode);
  const navigationIcons = usePreferencesStore((state) => state.navigationIcons);

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
    { type: 'divider' as const },
    {
      key: 'logout',
      icon: <LogoutOutlined />,
      label: '登出',
      onClick: handleLogout,
    },
  ];

  const currentPath = location.pathname;
  const enteredFromHome = new URLSearchParams(location.search).get('entry') === 'home';
  const activePath = enteredFromHome ? '/' : currentPath;

  return (
    <header className="app-header">
      {/* Left: Logo */}
      <div className="header-logo" onClick={() => navigate('/')}>
        Agent <span>Studio</span>
      </div>

      {/* Center: Nav */}
      <nav className="header-nav" aria-label="主导航">
        {HEADER_NAV_ITEMS.map((item) => {
          const active = activePath === item.path
            || (item.path !== '/' && activePath.startsWith(item.path));
          const Icon = getNavigationIconComponent(
            navigationIcons[item.id] ?? item.defaultIcon,
          );

          return (
            <button
              type="button"
              key={item.id}
              className={`header-nav-item${active ? ' active' : ''}`}
              aria-current={active ? 'page' : undefined}
              onClick={() => navigate(item.path)}
            >
              {navigationIconMode === 'outline' && (
                <Icon className="header-nav-icon" aria-hidden="true" />
              )}
              {navigationIconMode === 'emoji' && (
                <span className="header-nav-emoji" aria-hidden="true">{item.emoji}</span>
              )}
              <span>{item.label}</span>
            </button>
          );
        })}
      </nav>

      {/* Right: User */}
      <div className="header-right">
        <ThemeToggle />
        {isAuthenticated && (
          <Dropdown menu={{ items: userMenuItems }} placement="bottomRight">
            <div className="header-user">
              <div className="header-avatar">
                {user?.avatar ? (
                  <Avatar size={32} src={user.avatar} />
                ) : (
                  user?.username?.charAt(0)?.toUpperCase() || 'U'
                )}
              </div>
              <span className="header-username">{user?.username || 'User'}</span>
            </div>
          </Dropdown>
        )}
      </div>
    </header>
  );
};

export default Header;
