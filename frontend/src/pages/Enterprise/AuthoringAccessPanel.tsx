import { useCallback, useEffect, useState } from 'react';
import { Alert, Empty, Switch, Table, Tag, Typography, message } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { api } from '@/services/api';

type Capability =
  | 'can_view_agents'
  | 'can_create_agents'
  | 'can_update_agents'
  | 'can_delete_agents'
  | 'can_toggle_agents'
  | 'can_view_applications'
  | 'can_toggle_applications';

interface Account {
  id: number;
  username: string;
  email: string;
  role: 'admin' | 'professional' | 'member' | 'viewer';
  is_active: boolean;
  can_view_agents: boolean;
  can_create_agents: boolean;
  can_update_agents: boolean;
  can_delete_agents: boolean;
  can_toggle_agents: boolean;
  can_view_applications: boolean;
  can_toggle_applications: boolean;
}

interface AccountPage {
  count?: number;
  results?: Account[];
}

const roleLabels: Record<Account['role'], string> = {
  admin: '管理员',
  professional: '专业用户',
  member: '成员',
  viewer: '查看者',
};

export default function AuthoringAccessPanel() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [loading, setLoading] = useState(false);
  const [updating, setUpdating] = useState<string | null>(null);

  const loadAccounts = useCallback(async () => {
    setLoading(true);
    try {
      const first = await api.get<AccountPage | Account[]>('/auth/admin/users/', { page: 1 });
      if (Array.isArray(first)) {
        setAccounts(first);
        return;
      }
      const firstItems = first.results ?? [];
      const pageCount = Math.ceil((first.count ?? firstItems.length) / 20);
      const remaining = await Promise.all(Array.from(
        { length: Math.max(0, pageCount - 1) },
        (_, index) => api.get<AccountPage>('/auth/admin/users/', { page: index + 2 }),
      ));
      setAccounts([
        ...firstItems,
        ...remaining.flatMap((page) => page.results ?? []),
      ]);
    } catch {
      message.error('加载账号授权失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadAccounts();
  }, [loadAccounts]);

  const updateCapability = async (
    account: Account,
    capability: Capability,
    checked: boolean,
  ) => {
    const key = `${account.id}:${capability}`;
    setUpdating(key);
    try {
      const updated = await api.patch<Account>(`/auth/admin/users/${account.id}/`, {
        [capability]: checked,
      });
      setAccounts((items) => items.map((item) => (
        item.id === updated.id ? { ...item, ...updated } : item
      )));
      message.success(`${account.username} 的账号权限已更新`);
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '更新授权失败');
    } finally {
      setUpdating(null);
    }
  };

  const capabilityColumn = (title: string, capability: Capability) => ({
    title,
    dataIndex: capability,
    width: 130,
    align: 'center' as const,
    render: (checked: boolean, account: Account) => (
      <Switch
        checked={account.role === 'admin' || checked}
        disabled={account.role === 'admin' || !account.is_active || updating !== null}
        loading={updating === `${account.id}:${capability}`}
        onChange={(value) => void updateCapability(account, capability, value)}
        aria-label={`${account.username} ${title}`}
      />
    ),
  });

  const columns: ColumnsType<Account> = [
    {
      title: '账号',
      dataIndex: 'username',
      width: 220,
      render: (username: string, account) => (
        <div className="enterprise-application-name">
          <strong>{username}</strong>
          <Typography.Text type="secondary">{account.email || '未填写邮箱'}</Typography.Text>
        </div>
      ),
    },
    {
      title: '角色',
      dataIndex: 'role',
      width: 110,
      render: (role: Account['role']) => <Tag>{roleLabels[role]}</Tag>,
    },
    {
      title: '应用权限',
      children: [
        capabilityColumn('查看', 'can_view_applications'),
        capabilityColumn('启停', 'can_toggle_applications'),
      ],
    },
    {
      title: '智能体权限',
      children: [
        capabilityColumn('查看', 'can_view_agents'),
        capabilityColumn('创建', 'can_create_agents'),
        capabilityColumn('修改', 'can_update_agents'),
        capabilityColumn('删除', 'can_delete_agents'),
        capabilityColumn('启停', 'can_toggle_agents'),
      ],
    },
  ];

  return (
    <div className="enterprise-subpanel">
      <Alert
        type="info"
        showIcon
        message="默认仅管理员拥有管理能力"
        description="查看能力与资源指定账号采用“或”关系：开通查看能力，或被某个资源单独选中，均可查看。应用创建与修改、资源账号配置仍仅限管理员。"
      />
      <Table<Account>
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={accounts}
        scroll={{ x: 1160 }}
        pagination={false}
        locale={{ emptyText: <Empty description="暂无账号" /> }}
      />
    </div>
  );
}
