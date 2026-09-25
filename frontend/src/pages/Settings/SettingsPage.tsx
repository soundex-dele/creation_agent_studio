import { useEffect, useState, type CSSProperties } from 'react';
import {
  Alert, Button, Card, Descriptions, Popconfirm, Segmented, Select, Space, Switch,
  Tag, message,
} from 'antd';
import {
  BgColorsOutlined, CheckOutlined, KeyOutlined, MessageOutlined, MoonOutlined, ReloadOutlined,
  SafetyCertificateOutlined, TeamOutlined, UserOutlined,
  BulbOutlined, UndoOutlined, SettingOutlined, ArrowRightOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { useThemeStore } from '@/stores/useThemeStore';
import {
  usePreferencesStore,
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
import RemoteAccessSettings from './RemoteAccessSettings';

const navigationIconSelectOptions = NAVIGATION_ICON_OPTIONS.map((option) => {
  const Icon = getNavigationIconComponent(option.id);
  return {
    value: option.id,
    label: <span className="settings-icon-select-option"><Icon aria-hidden="true" />{option.label}</span>,
  };
});

const settingsSections = [
  { id: 'appearance', label: '外观与布局', description: '主题、布局与导航', icon: <BgColorsOutlined /> },
  { id: 'conversation', label: '对话偏好', description: '输入习惯与工具权限', icon: <MessageOutlined /> },
  { id: 'workspace', label: '团队与工作区', description: '当前组织与成员角色', icon: <TeamOutlined /> },
  { id: 'security', label: '账号与安全', description: '个人资料与访问凭证', icon: <SafetyCertificateOutlined /> },
  { id: 'reset', label: '重置偏好', description: '恢复浏览器默认设置', icon: <UndoOutlined /> },
];

const sectionTitle = (id: string) => {
  const section = settingsSections.find(item => item.id === id)!;
  return <div className="settings-section-title">
    <span className="settings-section-icon" aria-hidden="true">{section.icon}</span>
    <div><h2>{section.label}</h2><p>{section.description}</p></div>
  </div>;
};

const organizationRoleLabels: Record<string, string> = {
  owner: '所有者', admin: '管理员', developer: '开发者', operator: '操作员', auditor: '审计员', viewer: '查看者',
};

export default function SettingsPage() {
  const [remoteAccessAvailable, setRemoteAccessAvailable] = useState(false);
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

  const currentTheme = SELECTABLE_THEME_PRESETS.find(preset => preset.id === theme);
  const currentOrganization = organizations.find(item => item.id === currentOrganizationId);

  return (
    <div className="settings-page">
      <header className="settings-heading">
        <div>
          <span className="settings-eyebrow"><SettingOutlined aria-hidden="true" />工作区偏好</span>
          <h1 className="page-title">设置</h1>
          <p className="page-subtitle">让界面与协作方式，更贴合你的工作习惯。</p>
        </div>
        <div className="settings-current-preferences" aria-label="当前外观">
          <span><BgColorsOutlined aria-hidden="true" />{currentTheme?.name || '自定义主题'}</span>
          <span>{layoutMode === 'top-bottom' ? '上下布局' : '左右布局'}</span>
        </div>
      </header>

      <div className="settings-layout">
        <aside className="settings-sidebar">
          <nav aria-label="设置分组">
            {remoteAccessAvailable && <a href="#settings-remote-access"><SettingOutlined aria-hidden="true" /><span><strong>远程访问</strong><small>设备配对与连接状态</small></span></a>}
            {settingsSections.map(section => <a href={`#settings-${section.id}`} key={section.id}>
              <span aria-hidden="true">{section.icon}</span>
              <span><strong>{section.label}</strong><small>{section.description}</small></span>
            </a>)}
          </nav>
          <p className="settings-save-note"><CheckOutlined aria-hidden="true" />界面与对话偏好即时生效，自动保存在当前浏览器。</p>
        </aside>
      <div className="settings-grid">
        <RemoteAccessSettings onAvailable={setRemoteAccessAvailable} />
        <Card id="settings-appearance" className="settings-appearance-card" title={sectionTitle('appearance')}>
          <div className="settings-row settings-layout-row">
            <div>
              <strong>界面布局</strong>
              <p>选择导航所在的位置，窄屏下会自动适配。</p>
            </div>
            <div className="settings-layout-options" role="radiogroup" aria-label="界面布局">
              {(['top-bottom', 'left-right'] as const).map(mode => <label className={`settings-layout-option${layoutMode === mode ? ' selected' : ''}`} key={mode}>
                <input type="radio" name="settings-layout" value={mode} checked={layoutMode === mode} onChange={() => setLayoutMode(mode)} />
                <span className={`settings-layout-preview settings-layout-preview--${mode}`} aria-hidden="true"><i /><i /><i /></span>
                <span>{mode === 'top-bottom' ? '上下布局' : '左右布局'}</span>
                <CheckOutlined className="settings-layout-check" aria-hidden="true" />
              </label>)}
            </div>
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
                <label
                  key={preset.id}
                  className={`settings-theme-option${selected ? ' selected' : ''}`}
                  style={previewStyle}
                >
                  <input type="radio" name="settings-theme" value={preset.id} checked={selected} onChange={() => setTheme(preset.id)} aria-label={`${preset.name}，${preset.description}`} />
                  <span className={`settings-theme-preview settings-theme-preview--${layoutMode}`} aria-hidden="true">
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
                </label>
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

        <Card id="settings-conversation" title={sectionTitle('conversation')}>
          <Space direction="vertical" size={22} style={{ width: '100%' }}>
            <div className="settings-row">
              <div><strong>发送快捷键</strong><p>选择更符合你输入习惯的发送方式。</p></div>
              <Select
                aria-label="发送快捷键"
                value={sendShortcut}
                onChange={setSendShortcut}
                className="settings-control"
                options={[
                  { value: 'enter', label: 'Enter 发送' },
                  { value: 'mod-enter', label: 'Ctrl/⌘+Enter 发送' },
                ]}
              />
            </div>
            <div className="settings-row settings-row--top">
              <div>
                <strong>所有会话完全控制</strong>
                <p>修改后应用于所有已有和新建对话（含“我的电脑”）的后续消息；在输入框切换权限也会同步到所有会话。正在执行的任务不受影响。</p>
              </div>
              <Switch
                aria-label="所有会话完全控制"
                checked={defaultPermissionMode === 'allow_all'}
                onChange={(checked) => setDefaultPermissionMode(checked ? 'allow_all' : 'default')}
              />
            </div>
            {defaultPermissionMode === 'allow_all' && (
              <Alert type="warning" showIcon message="完全控制允许 Codex 访问工作区外的文件并执行命令，无需逐次确认；组织强制审批策略仍然有效。" />
            )}
          </Space>
        </Card>

        <Card id="settings-workspace" title={sectionTitle('workspace')}>
          <div className="settings-row">
            <div><strong>当前组织</strong><p>应用、智能体、工作流和运行记录归属于当前组织。</p></div>
            <Select
              aria-label="当前组织"
              loading={isLoading}
              disabled={singleTenantMode || organizations.length <= 1}
              value={currentOrganizationId || undefined}
              onChange={selectOrganization}
              placeholder="选择组织"
              className="settings-control"
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
              children: currentOrganization ? (organizationRoleLabels[currentOrganization.role] || currentOrganization.role) : '—',
            },
          ]} />
        </Card>

        <Card id="settings-security" title={sectionTitle('security')}>
          <div className="settings-account-links">
            <button type="button" onClick={() => navigate('/profile')}>
              <UserOutlined aria-hidden="true" /><span><strong>个人资料</strong><small>编辑头像、昵称与个人信息</small></span><ArrowRightOutlined aria-hidden="true" />
            </button>
            <button type="button" onClick={() => navigate('/profile?tab=security')}>
              <KeyOutlined aria-hidden="true" /><span><strong>安全与 API Key</strong><small>管理登录密码与访问凭证</small></span><ArrowRightOutlined aria-hidden="true" />
            </button>
            {userRole === 'admin' && (
              <button type="button" onClick={() => navigate('/settings/accounts')}>
                <TeamOutlined aria-hidden="true" /><span><strong>账号管理</strong><small>管理系统账号与访问权限</small></span><ArrowRightOutlined aria-hidden="true" />
              </button>
            )}
          </div>
        </Card>

      <Card id="settings-reset" className="settings-reset-card" title={sectionTitle('reset')}>
        <div className="settings-row">
          <div><strong>恢复默认设置</strong><p>只重置当前浏览器中的主题、布局、导航图标和对话偏好，不会删除账号或业务数据。</p></div>
          <Popconfirm title="恢复默认设置？" description="主题、布局、导航图标和对话偏好将被重置。" onConfirm={reset}>
            <Button icon={<ReloadOutlined />}>恢复默认</Button>
          </Popconfirm>
        </div>
      </Card>
      </div>
      </div>
    </div>
  );
}
