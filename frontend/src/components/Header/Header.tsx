import React from 'react';
import { Dropdown, Avatar } from 'antd';
import {
  LogoutOutlined,
  MenuOutlined,
  SettingOutlined,
  TeamOutlined,
  UserOutlined,
} from '@ant-design/icons';
import { useNavigate, useLocation } from 'react-router-dom';
import { useAuthStore } from '@/stores/useAuthStore';
import { usePreferencesStore } from '@/stores/usePreferencesStore';
import { ThemeToggle } from '@/components/Theme';
import { HEADER_NAV_ITEMS } from './headerNavigation';
import { getNavigationIconComponent } from './navigationIconComponents';
import './Header.css';

interface HeaderProps {
  mobileMenuOpen?: boolean;
  onMobileMenuClick?: () => void;
  showMobileMenu?: boolean;
}

const Header: React.FC<HeaderProps> = ({
  mobileMenuOpen = false,
  onMobileMenuClick,
  showMobileMenu = false,
}) => {
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
  const enteredFromHome = new URLSearchParams(location.search).get('entry') === 'home';
  const activePath = enteredFromHome ? '/' : currentPath;

  return (
    <header className="app-header">
      <button
        type="button"
        className={`header-mobile-menu${showMobileMenu ? '' : ' header-mobile-menu--placeholder'}`}
        aria-label="打开当前页面导航"
        aria-expanded={showMobileMenu ? mobileMenuOpen : undefined}
        aria-hidden={showMobileMenu ? undefined : true}
        tabIndex={showMobileMenu ? 0 : -1}
        onClick={showMobileMenu ? onMobileMenuClick : undefined}
      >
        <MenuOutlined aria-hidden="true" />
      </button>

      {/* Left: Logo */}
      <button type="button" className="header-logo" onClick={() => navigate('/')}>
        Agent <span>Studio</span>
      </button>

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
