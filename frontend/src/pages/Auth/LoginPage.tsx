import React, { useEffect, useState } from 'react';
import { Divider, Form, Input, Button, message, Modal, Select, Spin, Typography } from 'antd';
import { api } from '@/services/api';
import { UserOutlined, LockOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '@/stores/useAuthStore';

const { Text } = Typography;

interface AuthMode {
  mode: 'account' | 'license';
  registration_enabled: boolean;
  machine_code: string | null;
  license_installed: boolean;
  product: string | null;
}

const LoginPage: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const [modeLoading, setModeLoading] = useState(true);
  const [authMode, setAuthMode] = useState<AuthMode | null>(null);
  const [ssoOpen, setSsoOpen] = useState(false);
  const [ssoProviders, setSsoProviders] = useState<Array<{ id: number; name: string; organization: string; login_url: string }>>([]);
  const [ssoProvider, setSsoProvider] = useState<number>();
  const navigate = useNavigate();
  const login = useAuthStore((state) => state.login);
  const licenseLogin = useAuthStore((state) => state.licenseLogin);

  useEffect(() => {
    let active = true;
    api.get<AuthMode>('/auth/mode/')
      .then((result) => { if (active) setAuthMode(result); })
      .catch(() => message.error('无法读取登录配置'))
      .finally(() => { if (active) setModeLoading(false); });
    return () => { active = false; };
  }, []);

  const onFinish = async (values: { username: string; password: string }) => {
    setLoading(true);
    try {
      await login(values.username, values.password);
      message.success('登录成功');
      navigate('/');
    } catch (error: any) {
      const errData = error.response?.data;
      if (errData?.detail) {
        message.error(errData.detail);
      } else if (errData && typeof errData === 'object') {
        const firstError = Object.values(errData)[0];
        if (Array.isArray(firstError)) message.error(firstError[0]);
        else message.error('登录失败');
      } else {
        message.error('登录失败');
      }
    } finally {
      setLoading(false);
    }
  };

  const activateLicense = async (values: { license?: string }) => {
    setLoading(true);
    try {
      await licenseLogin(values.license);
      message.success('许可证验证成功');
      navigate('/');
    } catch (error: any) {
      message.error(error.response?.data?.detail || '许可证验证失败');
    } finally {
      setLoading(false);
    }
  };

  const copyMachineCode = async () => {
    if (!authMode?.machine_code) return;
    await navigator.clipboard.writeText(authMode.machine_code);
    message.success('机器码已复制');
  };

  const discoverSso = async (values: { email: string }) => {
    const domain = values.email.split('@')[1];
    const providers = await api.get<typeof ssoProviders>('/enterprise/sso/discovery', { domain });
    setSsoProviders(providers); setSsoProvider(providers[0]?.id);
    if (!providers.length) message.warning('该邮箱域名未配置企业身份提供商');
  };

  return (
    <div className="animate-fade-in-scale rounded-xl border border-border bg-card/80 p-8 shadow-lg backdrop-blur-xl">
      <div className="mb-8 text-center">
        <h1 className="animate-logo-reveal font-display text-2xl font-bold text-primary">
          Agent Studio
        </h1>
        <Text className="mt-2 block text-text-sec">
          {authMode?.mode === 'license' ? '使用离线许可证激活' : '登录到您的账户'}
        </Text>
      </div>

      {modeLoading && <div className="py-12 text-center"><Spin /></div>}

      {!modeLoading && !authMode && (
        <div className="text-center">
          <Text type="danger" className="mb-4 block">无法读取登录配置</Text>
          <Button onClick={() => window.location.reload()}>重试</Button>
        </div>
      )}

      {!modeLoading && authMode?.mode === 'license' && (
        <Form name="license-login" onFinish={activateLicense} autoComplete="off" size="large" layout="vertical">
          <Form.Item label="本机机器码">
            <Input value={authMode.machine_code || ''} readOnly addonAfter={(
              <Button type="link" size="small" onClick={copyMachineCode}>复制</Button>
            )} />
          </Form.Item>
          <Text className="mb-4 block text-text-sec">
            将机器码发给授权方，再把收到的许可证粘贴到下方。
          </Text>
          <Form.Item
            name="license"
            label="许可证"
            rules={authMode.license_installed ? [] : [{ required: true, message: '请输入许可证' }]}
          >
            <Input.TextArea rows={5} placeholder={authMode.license_installed ? '已安装有效许可证，可直接进入' : 'ASL1.…'} />
          </Form.Item>
          <Button type="primary" htmlType="submit" block loading={loading}>
            {authMode.license_installed ? '使用已激活许可证进入' : '激活并进入'}
          </Button>
        </Form>
      )}

      {!modeLoading && authMode?.mode === 'account' && <Form name="login" onFinish={onFinish} autoComplete="off" size="large" layout="vertical">
        <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
          <Input
            prefix={<UserOutlined className="text-text-dim" />}
            placeholder="用户名"
            className="rounded-lg"
          />
        </Form.Item>

        <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
          <Input.Password
            prefix={<LockOutlined className="text-text-dim" />}
            placeholder="密码"
            className="rounded-lg"
          />
        </Form.Item>

        <Form.Item>
          <Button
            type="primary"
            htmlType="submit"
            block
            loading={loading}
            className="animate-glow-pulse h-10 rounded-lg border-none font-medium"
            style={{
              background: 'var(--color-primary)',
              color: 'var(--color-on-primary)',
              boxShadow: '0 0 20px color-mix(in srgb, var(--color-primary) 30%, transparent)',
            }}
          >
            登录
          </Button>
        </Form.Item>

        <Divider plain>或</Divider>
        <Button block onClick={() => setSsoOpen(true)}>企业 SSO 登录</Button>

        {authMode.registration_enabled && (
          <div className="text-center">
            <Text className="text-text-sec">
              还没有账户？{' '}
              <a href="/auth/register" className="text-primary hover:underline">立即注册</a>
            </Text>
          </div>
        )}
      </Form>}
      <Modal title="企业 SSO 登录" open={ssoOpen} onCancel={() => setSsoOpen(false)} okText="前往企业登录" okButtonProps={{ disabled: !ssoProvider }} onOk={() => { const provider = ssoProviders.find(item => item.id === ssoProvider); if (provider) window.location.assign(provider.login_url); }}>
        <Form layout="vertical" onFinish={discoverSso}><Form.Item name="email" label="企业邮箱" rules={[{ required: true, type: 'email' }]}><Input /></Form.Item><Button htmlType="submit">查找身份提供商</Button></Form>
        {ssoProviders.length > 0 && <Select style={{ width: '100%', marginTop: 16 }} value={ssoProvider} onChange={setSsoProvider} options={ssoProviders.map(item => ({ value: item.id, label: `${item.organization} · ${item.name}` }))} />}
      </Modal>
    </div>
  );
};

export default LoginPage;
