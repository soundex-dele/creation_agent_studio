import { useCallback, useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import {
  Alert, Button, Card, Empty, Form, Input, Modal, Result, Select, Space, Switch,
  Table, Tag, Typography, Upload, message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  DownloadOutlined, ImportOutlined, InboxOutlined,
  LockOutlined, ReloadOutlined, TeamOutlined, UserAddOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { api } from '@/services/api';
import { useAuthStore } from '@/stores/useAuthStore';
import WorkspaceHeader from '@/components/Workspace/WorkspaceHeader';
import './AccountManagementPage.css';

type AccountRole = 'admin' | 'auditor' | 'member';

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

interface AccountPermissionValues {
  role: AccountRole;
  is_active: boolean;
}

interface AccountImportResult {
  total: number;
  created: number;
  updated: number;
}

interface AccountImportError {
  row: number;
  field: string;
  messages: string[];
}

const roleOptions = [
  { value: 'member', label: '普通用户' },
  { value: 'auditor', label: '平台审计员' },
  { value: 'admin', label: '平台管理员' },
] satisfies Array<{ value: AccountRole; label: string }>;

const rolePresentation: Record<AccountRole, { label: string; color: string }> = {
  admin: { label: '平台管理员', color: 'red' },
  auditor: { label: '平台审计员', color: 'purple' },
  member: { label: '普通用户', color: 'blue' },
};

const fieldNames = new Set<keyof CreateAccountValues>([
  'username', 'email', 'role', 'is_active', 'password', 'password_confirm',
]);

export default function AccountManagementPage() {
  const navigate = useNavigate();
  const user = useAuthStore((state) => state.user);
  const canManageAccounts = user?.role === 'admin';
  const [form] = Form.useForm<CreateAccountValues>();
  const [permissionForm] = Form.useForm<AccountPermissionValues>();
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [permissionAccount, setPermissionAccount] = useState<Account | null>(null);
  const [savingPermissions, setSavingPermissions] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [importing, setImporting] = useState(false);

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
        <div className="account-identity-cell">
          <span className="account-avatar" aria-hidden="true">{Array.from(username)[0]?.toLocaleUpperCase() || 'U'}</span>
          <div className="account-identity">
            <div><strong>{username}</strong>{account.id === user?.id && <Tag bordered={false}>当前账号</Tag>}</div>
            <span>{account.email || '未填写邮箱'}</span>
          </div>
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
    {
      title: '操作',
      key: 'actions',
      width: 156,
      fixed: 'right',
      render: (_, account) => (
        <Button
          icon={<LockOutlined aria-hidden="true" />}
          onClick={() => {
            setPermissionAccount(account);
            permissionForm.setFieldsValue({
              role: account.role,
              is_active: account.is_active,
            });
          }}
        >
          权限设置
        </Button>
      ),
    },
  ], [permissionForm, user?.id]);

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

  const downloadCsv = async (endpoint: string, filename: string) => {
    try {
      const blob = await api.get<Blob>(endpoint, undefined, { responseType: 'blob' });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch {
      message.error('下载失败，请稍后重试');
    }
  };

  const importAccounts = async (file: File) => {
    const data = new FormData();
    data.append('file', file);
    setImporting(true);
    try {
      const result = await api.post<AccountImportResult>(
        '/auth/admin/users/import/',
        data,
        { headers: { 'Content-Type': 'multipart/form-data' }, timeout: 60_000 },
      );
      message.success(`导入完成：新增 ${result.created} 个，更新 ${result.updated} 个`);
      setImportOpen(false);
      await loadAccounts(1);
    } catch (error: unknown) {
      const response = axios.isAxiosError(error)
        ? error.response?.data as { detail?: string; errors?: AccountImportError[] } | undefined
        : undefined;
      const details = (response?.errors ?? []).slice(0, 12).map((item) => (
        `第 ${item.row} 行 · ${item.field}：${item.messages.join('；')}`
      ));
      Modal.error({
        title: response?.detail || '账号导入失败',
        width: 640,
        content: details.length > 0
          ? <pre className="account-import-errors">{details.join('\n')}</pre>
          : '请确认文件为 UTF-8 编码的 CSV，并使用下载的模板填写。',
      });
    } finally {
      setImporting(false);
    }
  };

  const savePermissions = async (values: AccountPermissionValues) => {
    if (!permissionAccount) return;
    setSavingPermissions(true);
    try {
      const updated = await api.patch<Account>(
        `/auth/admin/users/${permissionAccount.id}/`,
        values,
      );
      setAccounts((items) => items.map((item) => (
        item.id === updated.id ? { ...item, ...updated } : item
      )));
      setPermissionAccount(null);
      message.success(`${updated.username} 的账号权限已更新`);
    } catch (error: unknown) {
      const detail = axios.isAxiosError(error) && typeof error.response?.data?.detail === 'string'
        ? error.response.data.detail
        : '更新账号权限失败';
      message.error(detail);
    } finally {
      setSavingPermissions(false);
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
    <div className="account-management-page workspace-page">
      <WorkspaceHeader
        icon={<TeamOutlined />} eyebrow="账号与访问" title="账号管理"
        description="统一维护团队登录账号、平台角色与登录权限。"
        loading={loading}
        action={<Button type="primary" icon={<UserAddOutlined />} onClick={openCreate}>
          添加账号
        </Button>}
        metrics={[
          { label: '全部账号', value: total, hint: '系统中的登录账号' },
          { label: '本页可登录', value: accounts.filter(account => account.is_active).length, hint: `第 ${page} 页的启用账号` },
          { label: '本页已停用', value: accounts.filter(account => !account.is_active).length, hint: `第 ${page} 页的停用账号` },
        ]}
      />

      <Alert
        className="account-management-notice"
        type="info"
        showIcon
        message="新账号不会自动登录"
        description="创建完成后，请将用户名和初始密码通过安全渠道发送给使用者，并建议其首次登录后修改密码。"
      />

      <Card
        className="account-management-card"
        title={<div className="account-management-card-title"><h2>团队账号</h2><span>管理平台身份与登录状态</span></div>}
        extra={(
          <Space wrap className="account-management-tools">
            <Button
              icon={<DownloadOutlined />}
              onClick={() => void downloadCsv('/auth/admin/users/export/', 'accounts.csv')}
            >导出账号</Button>
            <Button icon={<ImportOutlined />} onClick={() => setImportOpen(true)}>导入账号</Button>
            <Button
              icon={<ReloadOutlined />}
              loading={loading}
              onClick={() => void loadAccounts(page)}
            >
              刷新
            </Button>
          </Space>
        )}
      >
        <Table<Account>
          rowKey="id"
          columns={columns}
          dataSource={accounts}
          loading={loading}
          scroll={{ x: 820 }}
          locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有可管理的账号，添加账号后即可为团队分配访问权限" /> }}
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
        className="account-create-modal"
        title="添加登录账号"
        width={680}
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
          className="account-create-form"
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
          <Form.Item name="role" label="账号角色" className="account-form-full" rules={[{ required: true }]}>
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
          <Form.Item name="is_active" label="允许登录" valuePropName="checked" className="account-form-full account-login-field">
            <Switch checkedChildren="启用" unCheckedChildren="停用" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        className="account-permission-modal"
        title={`账号权限 · ${permissionAccount?.username ?? ''}`}
        open={permissionAccount !== null}
        okText="保存权限"
        cancelText="取消"
        confirmLoading={savingPermissions}
        onOk={() => permissionForm.submit()}
        onCancel={() => !savingPermissions && setPermissionAccount(null)}
        destroyOnHidden
        width={680}
      >
        {permissionAccount && <div className="account-permission-identity">
          <span className="account-avatar" aria-hidden="true">{Array.from(permissionAccount.username)[0]?.toLocaleUpperCase() || 'U'}</span>
          <div className="account-identity"><strong>{permissionAccount.username}</strong><span>{permissionAccount.email || '未填写邮箱'}</span></div>
        </div>}
        <Alert
          type="info"
          showIcon
          message="这里只设置平台身份"
          description="组织内的管理能力由组织成员角色决定；单个智能体和应用的访问能力由资源权限设置决定。平台管理员拥有全局覆盖权限，平台审计员仅用于平台级审计。"
        />
        <Form<AccountPermissionValues>
          form={permissionForm}
          layout="vertical"
          className="account-permission-form"
          onFinish={savePermissions}
        >
          <div className="account-permission-basics">
            <Form.Item name="role" label="账号角色" rules={[{ required: true }]}>
              <Select
                options={roleOptions}
                disabled={permissionAccount?.id === user?.id}
              />
            </Form.Item>
            <Form.Item name="is_active" label="允许登录" valuePropName="checked">
              <Switch
                checkedChildren="启用"
                unCheckedChildren="停用"
                disabled={permissionAccount?.id === user?.id}
              />
            </Form.Item>
          </div>
        </Form>
      </Modal>

      <Modal
        className="account-import-modal"
        title="批量导入账号"
        open={importOpen}
        footer={null}
        onCancel={() => !importing && setImportOpen(false)}
        destroyOnHidden
      >
        <Alert
          type="info"
          showIcon
          message="CSV 导入规则"
          description="同名账号会更新，新增账号必须填写初始密码。文件会整批校验，任一行有误时不会写入任何账号。"
        />
        <Upload.Dragger
          className="account-import-dragger"
          accept=".csv,text/csv"
          showUploadList={false}
          disabled={importing}
          beforeUpload={(file) => {
            void importAccounts(file);
            return Upload.LIST_IGNORE;
          }}
        >
          <p className="ant-upload-drag-icon"><InboxOutlined /></p>
          <p className="ant-upload-text">点击或拖入 CSV 文件</p>
          <p className="ant-upload-hint">支持一次新增或更新最多 1000 个账号</p>
        </Upload.Dragger>
        <Button
          type="link"
          icon={<DownloadOutlined />}
          disabled={importing}
          onClick={() => void downloadCsv(
            '/auth/admin/users/import-template/',
            'accounts-import-template.csv',
          )}
        >
          下载导入模板
        </Button>
      </Modal>
    </div>
  );
}
