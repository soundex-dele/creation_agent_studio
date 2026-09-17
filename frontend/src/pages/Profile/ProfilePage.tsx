import { useEffect, useMemo, useState } from 'react';
import {
  Alert, Avatar, Button, Card, Descriptions, Divider, Form, Input, List,
  Modal, Popconfirm, Select, Space, Tabs, Tag, Typography, message,
} from 'antd';
import {
  ApiOutlined, CopyOutlined, DeleteOutlined, LockOutlined, SaveOutlined,
  SafetyCertificateOutlined, UserOutlined,
} from '@ant-design/icons';
import { useSearchParams } from 'react-router-dom';
import { api } from '@/services/api';
import { useAuthStore } from '@/stores/useAuthStore';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import './ProfilePage.css';

type Profile = {
  id: string;
  username: string;
  email: string;
  role: string;
  avatar?: string;
  bio?: string;
  created_at: string;
  updated_at: string;
};

type ApiKey = {
  id: string;
  name: string;
  prefix: string;
  scopes: string[];
  expires_at?: string | null;
  last_used_at?: string | null;
  revoked_at?: string | null;
  created_at: string;
};

const roleNames: Record<string, string> = {
  admin: '管理员', professional: '专业用户', member: '成员', viewer: '查看者',
};

const formatDate = (value?: string | null) => value
  ? new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
  : '—';

const errorText = (error: any, fallback: string) => (
  error?.response?.data?.detail
  || Object.values(error?.response?.data || {})?.flat()?.[0]
  || fallback
);

export default function ProfilePage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { user, updateUser } = useAuthStore();
  const { organizations, currentOrganizationId, loadOrganizations } = useOrganizationStore();
  const [profile, setProfile] = useState<Profile | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [licenseMode, setLicenseMode] = useState(false);
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [keysLoading, setKeysLoading] = useState(false);
  const [keyModalOpen, setKeyModalOpen] = useState(false);
  const [createdKey, setCreatedKey] = useState<string | null>(null);
  const [profileForm] = Form.useForm();
  const [passwordForm] = Form.useForm();
  const [keyForm] = Form.useForm();

  const currentOrganization = useMemo(
    () => organizations.find((item) => item.id === currentOrganizationId),
    [currentOrganizationId, organizations],
  );

  useEffect(() => {
    Promise.all([
      api.get<Profile>('/auth/me/'),
      api.get<{ mode: string }>('/auth/mode/'),
      loadOrganizations(user?.id).catch(() => undefined),
    ]).then(([data, mode]) => {
      setProfile(data);
      profileForm.setFieldsValue(data);
      updateUser(data);
      setLicenseMode(mode.mode === 'license');
    }).catch((error) => message.error(errorText(error, '无法加载个人资料')))
      .finally(() => setLoading(false));
  }, [loadOrganizations, profileForm, updateUser, user?.id]);

  const loadKeys = async () => {
    setKeysLoading(true);
    try { setKeys(await api.get<ApiKey[]>('/auth/me/api-keys/')); }
    catch (error) { message.error(errorText(error, '无法加载 API Key')); }
    finally { setKeysLoading(false); }
  };

  useEffect(() => { void loadKeys(); }, []);

  const saveProfile = async () => {
    try {
      const values = await profileForm.validateFields();
      setSaving(true);
      const updated = await api.patch<Profile>('/auth/me/', values);
      setProfile(updated);
      updateUser(updated);
      profileForm.setFieldsValue(updated);
      message.success('个人资料已保存');
    } catch (error: any) {
      if (!error?.errorFields) message.error(errorText(error, '保存个人资料失败'));
    } finally { setSaving(false); }
  };

  const changePassword = async () => {
    try {
      const values = await passwordForm.validateFields();
      await api.put('/auth/me/change-password/', values);
      passwordForm.resetFields();
      message.success('密码已更新');
    } catch (error: any) {
      if (!error?.errorFields) message.error(errorText(error, '修改密码失败'));
    }
  };

  const createKey = async () => {
    try {
      const values = await keyForm.validateFields();
      const expiresAt = values.expiry_days
        ? new Date(Date.now() + Number(values.expiry_days) * 86_400_000).toISOString()
        : undefined;
      const result = await api.post<ApiKey & { api_key: string }>('/auth/me/generate-api-key/', {
        name: values.name,
        scopes: values.scopes || [],
        expires_at: expiresAt,
      });
      setCreatedKey(result.api_key);
      setKeyModalOpen(false);
      keyForm.resetFields();
      await loadKeys();
    } catch (error: any) {
      if (!error?.errorFields) message.error(errorText(error, '创建 API Key 失败'));
    }
  };

  const copyKey = async () => {
    if (!createdKey) return;
    try {
      await navigator.clipboard.writeText(createdKey);
      message.success('API Key 已复制');
    } catch { message.warning('复制失败，请手动复制'); }
  };

  const revokeKey = async (id: string) => {
    try {
      await api.post(`/auth/me/api-keys/${id}/revoke/`, {});
      message.success('API Key 已撤销');
      await loadKeys();
    } catch (error) { message.error(errorText(error, '撤销 API Key 失败')); }
  };

  const profilePanel = (
    <div className="profile-grid">
      <Card loading={loading} className="profile-summary-card">
        <div className="profile-identity">
          <Avatar size={80} src={profile?.avatar} icon={<UserOutlined />}>
            {profile?.username?.slice(0, 1).toUpperCase()}
          </Avatar>
          <div>
            <Typography.Title level={3}>{profile?.username || '用户'}</Typography.Title>
            <Space wrap>
              <Tag color="gold">{roleNames[profile?.role || ''] || profile?.role}</Tag>
              {currentOrganization && <Tag>{currentOrganization.name}</Tag>}
            </Space>
          </div>
        </div>
        <Divider />
        <Descriptions column={1} size="small" items={[
          { key: 'email', label: '邮箱', children: profile?.email || '未设置' },
          { key: 'created', label: '加入时间', children: formatDate(profile?.created_at) },
          { key: 'updated', label: '最近更新', children: formatDate(profile?.updated_at) },
        ]} />
      </Card>
      <Card title="基本资料" loading={loading}>
        <Form form={profileForm} layout="vertical">
          <Form.Item name="username" label="用户名" rules={[
            { required: true, message: '请输入用户名' },
            { min: 2, max: 150, message: '用户名长度应为 2–150 个字符' },
          ]} extra={licenseMode ? '许可证账号由本机授权自动管理，用户名不可修改。' : undefined}>
            <Input autoComplete="username" disabled={licenseMode} />
          </Form.Item>
          <Form.Item name="email" label="邮箱" rules={[{ type: 'email', message: '请输入有效邮箱' }]}>
            <Input autoComplete="email" />
          </Form.Item>
          <Form.Item name="avatar" label="头像地址" rules={[{ type: 'url', warningOnly: true, message: '建议填写完整 URL' }]}>
            <Input placeholder="https://example.com/avatar.png" />
          </Form.Item>
          <Form.Item name="bio" label="个人简介"><Input.TextArea rows={4} maxLength={500} showCount /></Form.Item>
          <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={saveProfile}>保存资料</Button>
        </Form>
      </Card>
    </div>
  );

  const securityPanel = (
    <Space direction="vertical" size={20} style={{ width: '100%' }}>
      <Card title={<><LockOutlined /> 登录密码</>}>
        {licenseMode ? <Alert type="info" showIcon message="当前使用本机许可证登录" description="许可证模式不使用账号密码，请通过许可证管理登录权限。" /> : (
          <Form form={passwordForm} layout="vertical" className="profile-narrow-form">
            <Form.Item name="old_password" label="当前密码" rules={[{ required: true }]}><Input.Password autoComplete="current-password" /></Form.Item>
            <Form.Item name="new_password" label="新密码" rules={[{ required: true, min: 8, message: '密码至少 8 个字符' }]}><Input.Password autoComplete="new-password" /></Form.Item>
            <Form.Item name="new_password_confirm" label="确认新密码" dependencies={['new_password']} rules={[
              { required: true },
              ({ getFieldValue }) => ({ validator(_, value) { return !value || value === getFieldValue('new_password') ? Promise.resolve() : Promise.reject(new Error('两次输入的密码不一致')); } }),
            ]}><Input.Password autoComplete="new-password" /></Form.Item>
            <Button type="primary" onClick={changePassword}>更新密码</Button>
          </Form>
        )}
      </Card>
      <Card
        title={<><ApiOutlined /> API Key</>}
        extra={<Button type="primary" onClick={() => setKeyModalOpen(true)}>创建 API Key</Button>}
      >
        <Alert type="warning" showIcon message="API Key 仅在创建时显示一次，请保存到安全位置。" className="profile-key-alert" />
        <List loading={keysLoading} dataSource={keys} locale={{ emptyText: '尚未创建 API Key' }} renderItem={(item) => (
          <List.Item actions={item.revoked_at ? [] : [
            <Popconfirm key="revoke" title="确定撤销这个 API Key？" description="撤销后无法恢复。" onConfirm={() => revokeKey(item.id)}>
              <Button danger type="text" icon={<DeleteOutlined />}>撤销</Button>
            </Popconfirm>,
          ]}>
            <List.Item.Meta
              avatar={<SafetyCertificateOutlined className="profile-key-icon" />}
              title={<Space>{item.name}<Typography.Text code>{item.prefix}…</Typography.Text>{item.revoked_at && <Tag color="red">已撤销</Tag>}</Space>}
              description={<Space wrap split={<Divider type="vertical" />}>
                <span>创建于 {formatDate(item.created_at)}</span>
                <span>最后使用 {formatDate(item.last_used_at)}</span>
                <span>到期 {formatDate(item.expires_at)}</span>
                {item.scopes?.length > 0 && <span>范围：{item.scopes.join('、')}</span>}
              </Space>}
            />
          </List.Item>
        )} />
      </Card>
    </Space>
  );

  return (
    <div className="profile-page animate-fade-in">
      <div className="profile-heading"><h1 className="page-title">个人中心</h1><p className="page-subtitle">管理你的公开资料、登录安全和 API 访问凭据。</p></div>
      <Tabs activeKey={searchParams.get('tab') === 'security' ? 'security' : 'profile'} onChange={(tab) => {
        if (tab === 'security') setSearchParams({ tab: 'security' });
        else setSearchParams({});
      }} items={[
        { key: 'profile', label: '个人资料', children: profilePanel },
        { key: 'security', label: '安全与 API Key', children: securityPanel },
      ]} />
      <Modal title="创建 API Key" open={keyModalOpen} onCancel={() => setKeyModalOpen(false)} onOk={createKey} okText="创建" cancelText="取消">
        <Form form={keyForm} layout="vertical" initialValues={{ expiry_days: 90, scopes: [] }}>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}><Input placeholder="例如：本地开发" maxLength={100} /></Form.Item>
          <Form.Item name="expiry_days" label="有效期"><Select options={[
            { value: 30, label: '30 天' }, { value: 90, label: '90 天' }, { value: 365, label: '1 年' }, { value: 0, label: '永不过期' },
          ]} /></Form.Item>
          <Form.Item name="scopes" label="权限范围"><Select mode="tags" tokenSeparators={[',']} placeholder="留空表示使用默认范围；也可输入自定义 scope" /></Form.Item>
        </Form>
      </Modal>
      <Modal title="API Key 已创建" open={Boolean(createdKey)} onCancel={() => setCreatedKey(null)} footer={<Button type="primary" onClick={() => setCreatedKey(null)}>我已保存</Button>}>
        <Alert type="success" showIcon message="请立即复制，关闭后将无法再次查看。" />
        <Input.TextArea className="profile-created-key" value={createdKey || ''} autoSize readOnly />
        <Button block icon={<CopyOutlined />} onClick={copyKey}>复制 API Key</Button>
      </Modal>
    </div>
  );
}
