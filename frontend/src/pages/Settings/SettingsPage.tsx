import { useEffect } from 'react';
import {
  Alert, Button, Card, Descriptions, Popconfirm, Radio, Select, Space, Switch,
  Tag, Typography, message,
} from 'antd';
import {
  BgColorsOutlined, KeyOutlined, MessageOutlined, ReloadOutlined,
  SafetyCertificateOutlined, TeamOutlined, UserOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { useThemeStore } from '@/stores/useThemeStore';
import { usePreferencesStore } from '@/stores/usePreferencesStore';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import { useAuthStore } from '@/stores/useAuthStore';
import './SettingsPage.css';

export default function SettingsPage() {
  const navigate = useNavigate();
  const userId = useAuthStore((state) => state.user?.id);
  const { theme, setTheme } = useThemeStore();
  const {
    sendShortcut, defaultPermissionMode, setSendShortcut,
    setDefaultPermissionMode, reset: resetPreferences,
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
    setTheme('dark');
    message.success('偏好设置已恢复默认值');
  };

  return (
    <div className="settings-page animate-fade-in">
      <div className="settings-heading"><h1>设置</h1><p>调整界面、对话行为和当前团队工作区。</p></div>

      <div className="settings-grid">
        <Card title={<><BgColorsOutlined /> 外观</>}>
          <div className="settings-row">
            <div><strong>界面主题</strong><p>主题设置会保存在当前浏览器中。</p></div>
            <Radio.Group
              optionType="button"
              buttonStyle="solid"
              value={theme}
              onChange={(event) => setTheme(event.target.value)}
              options={[{ value: 'light', label: '亮色' }, { value: 'dark', label: '暗色' }]}
            />
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
          </Space>
        </Card>
      </div>

      <Card className="settings-reset-card" title="重置偏好">
        <div className="settings-row">
          <div><strong>恢复默认设置</strong><p>只重置当前浏览器中的主题和对话偏好，不会删除账号或业务数据。</p></div>
          <Popconfirm title="恢复默认设置？" description="主题和对话偏好将被重置。" onConfirm={reset}>
            <Button icon={<ReloadOutlined />}>恢复默认</Button>
          </Popconfirm>
        </div>
      </Card>
    </div>
  );
}
