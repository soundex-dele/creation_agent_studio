import { useEffect, type CSSProperties } from 'react';
import {
  Alert, Button, Card, Descriptions, Popconfirm, Segmented, Select, Space, Switch,
  Tag, Typography, message,
} from 'antd';
import {
  BgColorsOutlined, CheckOutlined, KeyOutlined, MessageOutlined, MoonOutlined, ReloadOutlined,
  SafetyCertificateOutlined, TeamOutlined, UserOutlined,
  BulbOutlined, UndoOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { useThemeStore } from '@/stores/useThemeStore';
import {
  usePreferencesStore,
  type LayoutMode,
  type NavigationIconMode,
} from '@/stores/usePreferencesStore';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { DEFAULT_THEME_ID, SELECTABLE_THEME_PRESETS } from '@/components/Theme/themePresets';
import {
  DEFAULT_NAVIGATION_ICONS,
  HEADER_NAV_ITEMS,
  NAVIGATION_ICON_OPTIONS,
} from '@/components/Header/headerNavigation';
import { getNavigationIconComponent } from '@/components/Header/navigationIconComponents';
import './SettingsPage.css';

const navigationIconSelectOptions = NAVIGATION_ICON_OPTIONS.map((option) => {
  const Icon = getNavigationIconComponent(option.id);
  return {
    value: option.id,
    label: <span className="settings-icon-select-option"><Icon aria-hidden="true" />{option.label}</span>,
  };
});

export default function SettingsPage() {
  const navigate = useNavigate();
  const userId = useAuthStore((state) => state.user?.id);
  const userRole = useAuthStore((state) => state.user?.role);
  const { theme, setTheme } = useThemeStore();
  const {
    layoutMode, setLayoutMode,
    sendShortcut, defaultPermissionMode, setSendShortcut,
    navigationIconMode, navigationIcons, setDefaultPermissionMode,
    setNavigationIconMode, setNavigationIcon,
    resetNavigationIcons, reset: resetPreferences,
  } = usePreferencesStore();
  const {
    organizations, currentOrganizationId, singleTenantMode,
    loadOrganizations, selectOrganization, isLoading,
  } = useOrganizationStore();

  useEffect(() => {
    void loadOrganizations(userId).catch(() => message.error('无法加载组织工作区'));
  }, [loadOrganizations, userId]);

  const reset = () => {
    resetPreferences();
    setTheme(DEFAULT_THEME_ID);
    message.success('偏好设置已恢复默认值');
  };

  return (
    <div className="settings-page animate-fade-in">
      <div className="settings-heading"><h1 className="page-title">设置</h1><p className="page-subtitle">调整界面、对话行为和当前团队工作区。</p></div>

      <div className="settings-grid">
        <Card className="settings-appearance-card" title={<><BgColorsOutlined /> 外观</>}>
          <div className="settings-row settings-layout-row">
            <div>
              <strong>界面布局</strong>
              <p>上下布局使用顶部导航；左右布局使用左侧导航，工作台应用横向排列。窄屏自动适配。</p>
            </div>
            <Segmented
              value={layoutMode}
              aria-label="界面布局"
              options={[
                { value: 'top-bottom', label: '上下布局' },
                { value: 'left-right', label: '左右布局' },
              ]}
              onChange={(value) => setLayoutMode(value as LayoutMode)}
            />
          </div>
          <div className="settings-theme-intro">
            <strong>界面主题</strong>
            <p>选择适合当前环境的配色，设置会保存在当前浏览器中。</p>
          </div>
          <div className="settings-theme-grid" role="radiogroup" aria-label="界面主题">
            {SELECTABLE_THEME_PRESETS.map((preset) => {
              const selected = preset.id === theme;
              const previewStyle = {
                '--theme-preview-bg': preset.colors.bgVoid,
                '--theme-preview-surface': preset.colors.bgCard,
                '--theme-preview-muted': preset.colors.bgElevated,
                '--theme-preview-border': preset.colors.border,
                '--theme-preview-accent': preset.colors.primary,
              } as CSSProperties;
              return (
                <button
                  type="button"
                  key={preset.id}
                  role="radio"
                  aria-checked={selected}
                  className={`settings-theme-option${selected ? ' selected' : ''}`}
                  style={previewStyle}
                  onClick={() => setTheme(preset.id)}
                >
                  <span className="settings-theme-preview" aria-hidden="true">
                    <span className="settings-theme-preview-sidebar" />
                    <span className="settings-theme-preview-content">
                      <span /><span /><span />
                    </span>
                  </span>
                  <span className="settings-theme-copy">
                    <span className="settings-theme-title">
                      <strong>{preset.name}</strong>
                      {selected && <span className="settings-theme-selected"><CheckOutlined /> 已选择</span>}
                    </span>
                    <small>{preset.description}</small>
                    <span className="settings-theme-mode">
                      {preset.mode === 'dark' ? <MoonOutlined /> : <BulbOutlined />}
                      {preset.mode === 'dark' ? '暗色' : '亮色'}
                    </span>
                  </span>
                </button>
              );
            })}
          </div>

          <div className="settings-icon-config">
            <div className="settings-icon-config-heading">
              <div>
                <strong>主导航图标</strong>
                <p>选择导航图标的显示方式，线稿模式还可逐项自定义。</p>
              </div>
            </div>
            <div className="settings-icon-mode-row">
              <strong>显示模式</strong>
              <Segmented
                value={navigationIconMode}
                aria-label="主导航图标显示模式"
                options={[
                  { value: 'outline', label: '黑白线稿' },
                  { value: 'emoji', label: 'Emoji' },
                  { value: 'hidden', label: '隐藏图标' },
                ]}
                onChange={(value) => setNavigationIconMode(value as NavigationIconMode)}
              />
            </div>

            {navigationIconMode === 'outline' ? (
              <>
                <div className="settings-icon-detail-heading">
                  <strong>线稿图标映射</strong>
                  <Button size="small" icon={<UndoOutlined />} onClick={resetNavigationIcons}>
                    恢复默认图标
                  </Button>
                </div>
                <div className="settings-icon-grid">
                  {HEADER_NAV_ITEMS.map((item) => {
                    const iconId = navigationIcons[item.id] ?? DEFAULT_NAVIGATION_ICONS[item.id];
                    const Icon = getNavigationIconComponent(iconId);
                    return (
                      <div className="settings-icon-row" key={item.id}>
                        <span className="settings-icon-row-label">
                          <Icon aria-hidden="true" />
                          <span>{item.label}</span>
                        </span>
                        <Select
                          value={iconId}
                          aria-label={`设置${item.label}图标`}
                          options={navigationIconSelectOptions}
                          onChange={(value) => setNavigationIcon(item.id, value)}
                        />
                      </div>
                    );
                  })}
                </div>
              </>
            ) : (
              <div className="settings-icon-mode-note">
                {navigationIconMode === 'emoji'
                  ? '导航将使用对应的 Emoji 图标，文字标签保持不变。'
                  : '导航将只显示文字标签，为导航栏腾出更多空间。'}
              </div>
            )}
          </div>
        </Card>

        <Card title={<><MessageOutlined /> 对话</>}>
          <Space direction="vertical" size={22} style={{ width: '100%' }}>
            <div className="settings-row">
              <div><strong>发送快捷键</strong><p>选择更符合你输入习惯的发送方式。</p></div>
              <Select
                value={sendShortcut}
                onChange={setSendShortcut}
                style={{ width: 190 }}
                options={[
                  { value: 'enter', label: 'Enter 发送' },
                  { value: 'mod-enter', label: 'Ctrl/⌘+Enter 发送' },
                ]}
              />
            </div>
            <div className="settings-row settings-row--top">
              <div>
                <strong>默认自动允许工具</strong>
                <p>开启后，新对话默认允许智能体直接调用工具；仍可在输入框中单独切换。</p>
              </div>
              <Switch
                checked={defaultPermissionMode === 'allow_all'}
                onChange={(checked) => setDefaultPermissionMode(checked ? 'allow_all' : 'default')}
              />
            </div>
            {defaultPermissionMode === 'allow_all' && (
              <Alert type="warning" showIcon message="自动允许会减少运行时确认，仅建议在可信任务和工作区中使用。" />
            )}
          </Space>
        </Card>

        <Card title={<><TeamOutlined /> 团队与工作区</>}>
          <div className="settings-row">
            <div><strong>当前组织</strong><p>应用、智能体、工作流和运行记录归属于当前组织。</p></div>
            <Select
              loading={isLoading}
              disabled={singleTenantMode || organizations.length <= 1}
              value={currentOrganizationId || undefined}
              onChange={selectOrganization}
              placeholder="选择组织"
              style={{ width: 240 }}
              options={organizations.map((organization) => ({
                value: organization.id,
                label: organization.name,
              }))}
            />
          </div>
          <Descriptions className="settings-org-details" size="small" column={1} items={[
            {
              key: 'mode', label: '部署模式',
              children: singleTenantMode ? <Tag color="blue">单组织</Tag> : <Tag>多组织</Tag>,
            },
            {
              key: 'role', label: '当前角色',
              children: organizations.find((item) => item.id === currentOrganizationId)?.role || '—',
            },
          ]} />
        </Card>

        <Card title={<><SafetyCertificateOutlined /> 账号与安全</>}>
          <Typography.Paragraph type="secondary">
            个人资料、登录密码与 API Key 集中在个人中心管理。
          </Typography.Paragraph>
          <Space wrap>
            <Button icon={<UserOutlined />} onClick={() => navigate('/profile')}>编辑个人资料</Button>
            <Button icon={<KeyOutlined />} onClick={() => navigate('/profile?tab=security')}>安全与 API Key</Button>
            {userRole === 'admin' && (
              <Button type="primary" icon={<TeamOutlined />} onClick={() => navigate('/settings/accounts')}>
                账号管理
              </Button>
            )}
          </Space>
        </Card>
      </div>

      <Card className="settings-reset-card" title="重置偏好">
        <div className="settings-row">
          <div><strong>恢复默认设置</strong><p>只重置当前浏览器中的主题、布局、导航图标和对话偏好，不会删除账号或业务数据。</p></div>
          <Popconfirm title="恢复默认设置？" description="主题、布局、导航图标和对话偏好将被重置。" onConfirm={reset}>
            <Button icon={<ReloadOutlined />}>恢复默认</Button>
          </Popconfirm>
        </div>
      </Card>
    </div>
  );
}
