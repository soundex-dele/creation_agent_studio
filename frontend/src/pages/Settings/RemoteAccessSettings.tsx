import { useEffect, useRef, useState } from 'react';
import { Alert, Button, Card, Form, Input, Popconfirm, Select, Space, Switch, Tag, Typography } from 'antd';
import { DesktopOutlined } from '@ant-design/icons';
import { api } from '@/services/api';

interface Configuration {
  host_enabled: boolean;
  manageable: boolean;
  server_url: string;
  computer_name: string;
  enabled: boolean;
  local_user_id: number | null;
  organization_id: string | null;
  device_id: string | null;
  bound_account: string;
  pairing_code: string;
  pairing_expires_at: string | null;
  status: string;
  users?: { id: number; username: string }[];
  organizations?: { id: string; name: string }[];
  memberships?: { user_id: number; organization_id: string }[];
}

const statuses: Record<string, string> = {
  online: '已连接', connecting: '连接中', reconnecting: '重连中',
  offline: '连接进程离线', disabled: '已关闭', unpaired: '等待配对',
};

export default function RemoteAccessSettings({ onAvailable }: { onAvailable: (available: boolean) => void }) {
  const [form] = Form.useForm();
  const userId = Form.useWatch('local_user_id', form);
  const initialized = useRef(false);
  const [config, setConfig] = useState<Configuration | null>(null);
  const [pending, setPending] = useState<{ account: string | null; account_id: number | null } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    let loading = false;
    const load = async () => {
      if (loading) return;
      loading = true;
      try {
        const value = await api.get<Configuration>('/remote-access/');
        if (cancelled) return;
        setConfig(value);
        onAvailable(value.host_enabled && value.manageable);
        if (!initialized.current && value.manageable) {
          form.setFieldsValue(value);
          initialized.current = true;
        }
        if (value.device_id && !value.bound_account && value.pairing_code) {
          const account = await api.post<{ account: string | null; account_id: number | null }>('/remote-access/pending/');
          if (!cancelled) setPending(account);
        } else if (!cancelled) setPending(null);
      } catch {
        if (!cancelled) setError('无法读取远程访问配置，请检查本地后端。');
      } finally { loading = false; }
    };
    void load();
    const timer = setInterval(() => void load(), 3000);
    return () => { cancelled = true; clearInterval(timer); };
  }, [form, onAvailable]);

  if (!config?.host_enabled || !config.manageable) return null;

  const perform = async (operation: () => Promise<Configuration>) => {
    setBusy(true);
    setError('');
    try {
      const value = await operation();
      setConfig(current => ({ ...current, ...value }));
      form.setFieldsValue(value);
    } catch (failure) {
      const detail = (failure as { response?: { data?: { detail?: unknown } } }).response?.data?.detail;
      setError(typeof detail === 'string' ? detail : '操作未完成，请检查配置后重试。');
    } finally { setBusy(false); }
  };

  const action = (name: string, data?: unknown) => perform(() => api.post(`/remote-access/${name}/`, data));
  const organizations = config.organizations?.filter(organization => config.memberships?.some(
    membership => membership.user_id === userId && membership.organization_id === organization.id,
  ));

  return <Card id="settings-remote-access" title={<span><DesktopOutlined aria-hidden="true" /> 远程访问</span>}>
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <p>登录服务器的“我的电脑”应用，从手机继续本机对话。关闭浏览器后连接仍会保留。</p>
      {error && <Alert type="error" showIcon message={error} />}
      <Form form={form} layout="vertical" onFinish={values => void perform(() => api.put('/remote-access/', {
        ...values, enabled: config.enabled,
      }))}>
        <Form.Item name="server_url" label="服务器地址" rules={[{ required: true, message: '请输入服务器地址' }, { type: 'url', message: '请输入完整 HTTP/HTTPS 地址' }]}>
          <Input placeholder="https://studio.example.com" disabled={Boolean(config.device_id)} />
        </Form.Item>
        <Form.Item name="computer_name" label="电脑名称" extra="此名称显示在账号的电脑列表中，建议为每台电脑设置便于区分的名称。" rules={[{ required: true, whitespace: true, message: '请输入电脑名称' }]}>
          <Input maxLength={100} />
        </Form.Item>
        <Form.Item name="local_user_id" label="授权访问的本地用户" rules={[{ required: true, message: '请选择本地用户' }]}>
          <Select disabled={Boolean(config.device_id)} options={config.users?.map(user => ({ value: user.id, label: user.username }))}
            onChange={() => form.setFieldValue('organization_id', undefined)} />
        </Form.Item>
        <Form.Item name="organization_id" label="授权访问的本地组织" rules={[{ required: true, message: '请选择本地组织' }]}>
          <Select disabled={Boolean(config.device_id)} options={organizations?.map(org => ({ value: org.id, label: org.name }))} />
        </Form.Item>
        <Button htmlType="submit" loading={busy}>保存连接设置</Button>
      </Form>
      <div className="settings-row">
        <div><strong>启用远程访问</strong><p>沿用授权用户的业务权限。关闭后保留绑定，停止远程连接。</p></div>
        <Switch aria-label="启用远程访问" checked={config.enabled} loading={busy} disabled={!config.server_url}
          onChange={enabled => void perform(() => api.put('/remote-access/', {
            server_url: config.server_url, computer_name: config.computer_name,
            local_user_id: config.local_user_id, organization_id: config.organization_id, enabled,
          }))} />
      </div>
      <div role="status"><Tag color={config.status === 'online' ? 'green' : 'default'}>{statuses[config.status] || config.status}</Tag>
        {config.bound_account ? `绑定账号：${config.bound_account}` : '尚未绑定账号'}
      </div>
      {config.pairing_code && <Alert type="info" showIcon message={<>
        配对码：<Typography.Text copyable strong>{config.pairing_code}</Typography.Text>
      </>} description={`在手机“我的电脑”中输入，${new Date(config.pairing_expires_at!).toLocaleTimeString('zh-CN')} 前有效。输入后请在此确认绑定账号。`} />}
      {pending?.account && !config.bound_account && <Alert type="warning" showIcon
        message={`确认绑定服务器账号：${pending.account}`} description="确认后，该账号可使用上方授权用户的权限访问本机。"
        action={<Button loading={busy} onClick={() => void action('confirm', { account_id: pending.account_id })}>确认绑定</Button>} />}
      <Space wrap>
        {!config.bound_account && <Button disabled={!config.server_url} loading={busy} onClick={() => void action('pair')}>生成配对码</Button>}
        <Button disabled={!config.enabled || !config.bound_account} loading={busy} onClick={() => void action('reconnect')}>重新连接</Button>
        {config.device_id && <Popconfirm title="解绑此电脑？" description="撤销服务器访问凭证并关闭远程访问。" onConfirm={() => action('unbind')}>
          <Button danger loading={busy}>解绑</Button>
        </Popconfirm>}
      </Space>
    </Space>
  </Card>;
}
