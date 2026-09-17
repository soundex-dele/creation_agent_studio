import React from 'react';
import { Dropdown, Avatar } from 'antd';
import { UserOutlined, LogoutOutlined, SettingOutlined } from '@ant-design/icons';
import { useNavigate, useLocation } from 'react-router-dom';
import { useAuthStore } from '@/stores/useAuthStore';
import { ThemeToggle } from '@/components/Theme';
import './Header.css';

const navItems = [
  { key: '/', label: '🏠 首页' },
  { key: '/chat', label: '💬 对话' },
  { key: '/agents', label: '🤖 智能体' },
  { key: '/skills', label: '⚡ 技能' },
  { key: '/apps', label: '🧩 应用' },
  { key: '/workflows', label: '🔀 工作流' },
  { key: '/automations', label: '⏱️ 自动化' },
  { key: '/enterprise', label: '🏢 控制台' },
];

const Header: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { user, logout, isAuthenticated } = useAuthStore();

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
      <nav className="header-nav">
        {navItems.map((item) => (
          <div
            key={item.key}
            className={`header-nav-item ${
              activePath === item.key || (item.key !== '/' && activePath.startsWith(item.key))
                ? 'active' : ''}`}
            onClick={() => navigate(item.key)}
          >
            {item.label}
          </div>
        ))}
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
