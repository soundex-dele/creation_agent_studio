import { useCallback, useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import {
  Alert, Button, Card, Form, Input, Modal, Result, Select, Switch,
  Table, Tag, Typography, message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  ArrowLeftOutlined, ReloadOutlined, TeamOutlined, UserAddOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { api } from '@/services/api';
import { useAuthStore } from '@/stores/useAuthStore';
import './AccountManagementPage.css';

type AccountRole = 'admin' | 'professional' | 'member' | 'viewer';

interface Account {
  id: string;
  username: string;
  email: string;
  role: AccountRole;
  is_active: boolean;
  created_at: string;
}

interface AccountPage {
  count: number;
  results: Account[];
}

interface CreateAccountValues {
  username: string;
  email: string;
  role: AccountRole;
  is_active: boolean;
  password: string;
  password_confirm: string;
}

const roleOptions = [
  { value: 'member', label: '成员' },
  { value: 'professional', label: '专业用户' },
  { value: 'viewer', label: '查看者' },
  { value: 'admin', label: '管理员' },
] satisfies Array<{ value: AccountRole; label: string }>;

const rolePresentation: Record<AccountRole, { label: string; color: string }> = {
  admin: { label: '管理员', color: 'red' },
  professional: { label: '专业用户', color: 'purple' },
  member: { label: '成员', color: 'blue' },
  viewer: { label: '查看者', color: 'default' },
};

const fieldNames = new Set<keyof CreateAccountValues>([
  'username', 'email', 'role', 'is_active', 'password', 'password_confirm',
]);

export default function AccountManagementPage() {
  const navigate = useNavigate();
  const user = useAuthStore((state) => state.user);
  const canManageAccounts = user?.role === 'admin';
  const [form] = Form.useForm<CreateAccountValues>();
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);

  const loadAccounts = useCallback(async (nextPage = 1) => {
    setLoading(true);
    try {
      const response = await api.get<AccountPage>('/auth/admin/users/', { page: nextPage });
      setAccounts(response.results);
      setTotal(response.count);
      setPage(nextPage);
    } catch {
      message.error('无法加载账号列表，请稍后重试');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (canManageAccounts) void loadAccounts();
  }, [canManageAccounts, loadAccounts]);

  const columns = useMemo<ColumnsType<Account>>(() => [
    {
      title: '账号',
      dataIndex: 'username',
      key: 'username',
      render: (username: string, account) => (
        <div className="account-identity">
          <strong>{username}</strong>
          <span>{account.email || '未填写邮箱'}</span>
        </div>
      ),
    },
    {
      title: '角色',
      dataIndex: 'role',
      key: 'role',
      width: 132,
      render: (role: AccountRole) => {
        const presentation = rolePresentation[role] ?? rolePresentation.member;
        return <Tag color={presentation.color}>{presentation.label}</Tag>;
      },
    },
    {
      title: '状态',
      dataIndex: 'is_active',
      key: 'is_active',
      width: 104,
      render: (active: boolean) => (
        <Tag color={active ? 'success' : 'default'}>{active ? '可登录' : '已停用'}</Tag>
      ),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 190,
      render: (value: string) => new Intl.DateTimeFormat('zh-CN', {
        dateStyle: 'medium',
        timeStyle: 'short',
      }).format(new Date(value)),
    },
  ], []);

  const openCreate = () => {
    form.resetFields();
    form.setFieldsValue({ role: 'member', is_active: true });
    setCreateOpen(true);
  };

  const createAccount = async (values: CreateAccountValues) => {
    setSubmitting(true);
    try {
      await api.post<Account>('/auth/admin/users/', values);
      message.success(`账号 ${values.username} 已创建`);
      setCreateOpen(false);
      form.resetFields();
      await loadAccounts(1);
    } catch (error: unknown) {
      const data = axios.isAxiosError(error)
        ? error.response?.data as Record<string, unknown> | undefined
        : undefined;
      const fieldErrors = data
        ? Object.entries(data).flatMap(([name, value]) => {
          if (!fieldNames.has(name as keyof CreateAccountValues)) return [];
          const errors = Array.isArray(value) ? value.map(String) : [String(value)];
          return [{ name: name as keyof CreateAccountValues, errors }];
        })
        : [];
      if (fieldErrors.length > 0) {
        form.setFields(fieldErrors);
        queueMicrotask(() => form.scrollToField(fieldErrors[0].name, { focus: true }));
      }
      const detail = typeof data?.detail === 'string' ? data.detail : undefined;
      message.error(detail || '添加账号失败，请检查表单内容');
    } finally {
      setSubmitting(false);
    }
  };

  if (!canManageAccounts) {
    return (
      <Result
        status="403"
        title="仅管理员可管理账号"
        subTitle="当前账号没有添加或查看其他账号的权限。"
        extra={<Button type="primary" onClick={() => navigate('/settings')}>返回设置</Button>}
      />
    );
  }

  return (
    <div className="account-management-page animate-fade-in">
      <div className="account-management-heading">
        <div>
          <Button
            type="text"
            className="account-management-back"
            icon={<ArrowLeftOutlined aria-hidden="true" />}
            onClick={() => navigate('/settings')}
          >
            返回设置
          </Button>
          <h1 className="page-title">账号管理</h1>
          <p className="page-subtitle">自主注册关闭后，由管理员在这里为团队添加登录账号。</p>
        </div>
        <Button type="primary" size="large" icon={<UserAddOutlined />} onClick={openCreate}>
          添加账号
        </Button>
      </div>

      <Alert
        className="account-management-notice"
        type="info"
        showIcon
        message="新账号不会自动登录"
        description="创建完成后，请将用户名和初始密码通过安全渠道发送给使用者，并建议其首次登录后修改密码。"
      />

      <Card
        className="account-management-card"
        title={<span className="account-management-card-title"><TeamOutlined /> 团队账号</span>}
        extra={(
          <Button
            icon={<ReloadOutlined />}
            loading={loading}
            onClick={() => void loadAccounts(page)}
          >
            刷新
          </Button>
        )}
      >
        <Table<Account>
          rowKey="id"
          columns={columns}
          dataSource={accounts}
          loading={loading}
          scroll={{ x: 680 }}
          locale={{ emptyText: '还没有可管理的账号' }}
          pagination={{
            current: page,
            pageSize: 20,
            total,
            showSizeChanger: false,
            showTotal: (count) => `共 ${count} 个账号`,
            onChange: (nextPage) => void loadAccounts(nextPage),
          }}
        />
      </Card>

      <Modal
        title="添加登录账号"
        open={createOpen}
        okText="创建账号"
        cancelText="取消"
        confirmLoading={submitting}
        destroyOnHidden
        onOk={() => form.submit()}
        onCancel={() => {
          if (!submitting) setCreateOpen(false);
        }}
      >
        <Typography.Paragraph type="secondary">
          用户名用于登录。密码必须满足系统安全策略，创建后不会再次显示。
        </Typography.Paragraph>
        <Form<CreateAccountValues>
          form={form}
          layout="vertical"
          requiredMark="optional"
          onFinish={createAccount}
          initialValues={{ role: 'member', is_active: true }}
        >
          <Form.Item
            name="username"
            label="用户名"
            rules={[
              { required: true, message: '请输入用户名' },
              { max: 150, message: '用户名不能超过 150 个字符' },
            ]}
          >
            <Input autoFocus autoComplete="off" placeholder="例如：zhangsan" />
          </Form.Item>
          <Form.Item
            name="email"
            label="邮箱"
            rules={[
              { required: true, message: '请输入邮箱' },
              { type: 'email', message: '请输入有效的邮箱地址' },
            ]}
          >
            <Input type="email" autoComplete="email" placeholder="name@example.com" />
          </Form.Item>
          <Form.Item name="role" label="账号角色" rules={[{ required: true }]}>
            <Select options={roleOptions} />
          </Form.Item>
          <Form.Item name="password" label="初始密码" rules={[{ required: true, message: '请输入初始密码' }]}>
            <Input.Password autoComplete="new-password" placeholder="设置初始密码" />
          </Form.Item>
          <Form.Item
            name="password_confirm"
            label="确认初始密码"
            dependencies={['password']}
            rules={[
              { required: true, message: '请再次输入初始密码' },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  if (!value || getFieldValue('password') === value) return Promise.resolve();
                  return Promise.reject(new Error('两次输入的密码不一致'));
                },
              }),
            ]}
          >
            <Input.Password autoComplete="new-password" placeholder="再次输入初始密码" />
          </Form.Item>
          <Form.Item name="is_active" label="允许登录" valuePropName="checked">
            <Switch checkedChildren="启用" unCheckedChildren="停用" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
