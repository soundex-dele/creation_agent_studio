import React, { useEffect, useState } from 'react';
import { Form, Input, Button, message, Spin, Typography } from 'antd';
import { UserOutlined, LockOutlined, MailOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '@/stores/useAuthStore';
import { api } from '@/services/api';

const { Text } = Typography;

interface AuthMode {
  mode: 'account' | 'license';
  registration_enabled: boolean;
}

const RegisterPage: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const [checkingMode, setCheckingMode] = useState(true);
  const navigate = useNavigate();
  const register = useAuthStore((state) => state.register);

  useEffect(() => {
    let active = true;
    api.get<AuthMode>('/auth/mode/')
      .then((result) => {
        if (active && (result.mode === 'license' || !result.registration_enabled)) {
          navigate('/auth/login', { replace: true });
        }
      })
      .catch(() => {
        if (active) {
          message.error('无法读取注册配置');
          navigate('/auth/login', { replace: true });
        }
      })
      .finally(() => { if (active) setCheckingMode(false); });
    return () => { active = false; };
  }, [navigate]);

  const onFinish = async (values: {
    username: string;
    email: string;
    password: string;
    password_confirm: string;
  }) => {
    if (values.password !== values.password_confirm) {
      message.error('两次输入的密码不一致');
      return;
    }
    setLoading(true);
    try {
      await register(values);
      message.success('注册成功');
      navigate('/auth/login');
    } catch (error: any) {
      const errData = error.response?.data;
      if (errData?.detail) {
        message.error(errData.detail);
      } else if (errData && typeof errData === 'object') {
        const firstError = Object.values(errData)[0];
        if (Array.isArray(firstError)) message.error(firstError[0]);
        else message.error('注册失败');
      } else {
        message.error('注册失败');
      }
    } finally {
      setLoading(false);
    }
  };

  if (checkingMode) {
    return <div className="p-12 text-center"><Spin /></div>;
  }

  return (
    <div className="animate-fade-in-scale rounded-xl border border-border bg-card/80 p-8 shadow-lg backdrop-blur-xl">
      <div className="mb-8 text-center">
        <h1 className="animate-logo-reveal font-display text-2xl font-bold text-primary">
          Agent Studio
        </h1>
        <Text className="mt-2 block text-text-sec">创建新账户</Text>
      </div>

      <Form name="register" onFinish={onFinish} autoComplete="off" size="large" layout="vertical">
        <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
          <Input prefix={<UserOutlined className="text-text-dim" />} placeholder="用户名" className="rounded-lg" />
        </Form.Item>

        <Form.Item name="email" rules={[{ required: true, message: '请输入邮箱' }, { type: 'email', message: '请输入有效的邮箱地址' }]}>
          <Input prefix={<MailOutlined className="text-text-dim" />} placeholder="邮箱" className="rounded-lg" />
        </Form.Item>

        <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
          <Input.Password prefix={<LockOutlined className="text-text-dim" />} placeholder="密码" className="rounded-lg" />
        </Form.Item>

        <Form.Item name="password_confirm" rules={[{ required: true, message: '请确认密码' }]}>
          <Input.Password prefix={<LockOutlined className="text-text-dim" />} placeholder="确认密码" className="rounded-lg" />
        </Form.Item>

        <Form.Item>
          <Button type="primary" htmlType="submit" block loading={loading}
            className="h-10 rounded-lg border-none font-medium"
            style={{ background: 'var(--color-primary)' }}>
            注册
          </Button>
        </Form.Item>

        <div className="text-center">
          <Text className="text-text-sec">
            已有账户？{' '}
            <a href="/auth/login" className="text-primary hover:underline">立即登录</a>
          </Text>
        </div>
      </Form>
    </div>
  );
};

export default RegisterPage;
