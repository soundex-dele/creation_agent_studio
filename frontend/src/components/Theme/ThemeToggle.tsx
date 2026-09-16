import React from 'react';
import { Button, Dropdown, Tooltip } from 'antd';
import { BulbOutlined, MoonOutlined } from '@ant-design/icons';
import {
  getThemePreset,
  SELECTABLE_THEME_PRESETS,
  type ThemeId,
} from '@/components/Theme/themePresets';
import { useThemeStore } from '@/stores/useThemeStore';

const ThemeToggle: React.FC = () => {
  const { theme, setTheme } = useThemeStore();
  const currentTheme = getThemePreset(theme);

  return (
    <Dropdown
      trigger={['click']}
      placement="bottomRight"
      menu={{
        selectedKeys: [theme],
        onClick: ({ key }) => setTheme(key as ThemeId),
        items: SELECTABLE_THEME_PRESETS.map((preset) => ({
          key: preset.id,
          label: preset.name,
          icon: (
            <span
              aria-hidden="true"
              style={{
                display: 'inline-block', width: 10, height: 10, borderRadius: '50%',
                background: preset.colors.primary,
              }}
            />
          ),
        })),
      }}
    >
      <Tooltip title={`当前主题：${currentTheme.name}`}>
        <Button
          type="text"
          aria-label={`当前主题：${currentTheme.name}，点击切换`}
          icon={currentTheme.mode === 'dark' ? <MoonOutlined /> : <BulbOutlined />}
          style={{
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            width: 36, height: 36, borderRadius: 8,
            color: 'var(--color-primary)', fontSize: 18,
          }}
        />
      </Tooltip>
    </Dropdown>
  );
};

export default ThemeToggle;
