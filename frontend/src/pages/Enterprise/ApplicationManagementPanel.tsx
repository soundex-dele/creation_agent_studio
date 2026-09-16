import { useCallback, useEffect, useState } from 'react';
import { Alert, Empty, Switch, Table, Tag, Typography, message } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { api } from '@/services/api';

interface ManagedApplication {
  id: number;
  name: string;
  slug: string;
  description: string;
  kind: 'chat' | 'task' | 'custom';
  is_active: boolean;
  updated_at: string;
}

interface ApplicationListResponse {
  results?: ManagedApplication[];
}

const kindLabels: Record<ManagedApplication['kind'], string> = {
  chat: '聊天应用',
  task: '任务应用',
  custom: '自定义应用',
};

export default function ApplicationManagementPanel({
  organizationId,
  role,
}: {
  organizationId: string;
  role?: string;
}) {
  const [applications, setApplications] = useState<ManagedApplication[]>([]);
  const [loading, setLoading] = useState(false);
  const [updatingId, setUpdatingId] = useState<number | null>(null);
  const canAdmin = role === 'owner' || role === 'admin';

  const loadApplications = useCallback(async () => {
    setLoading(true);
    try {
      const response = await api.get<ApplicationListResponse | ManagedApplication[]>(
        `/organizations/${organizationId}/applications`,
        { limit: 200 },
      );
      setApplications(Array.isArray(response) ? response : response.results ?? []);
    } finally {
      setLoading(false);
    }
  }, [organizationId]);

  useEffect(() => {
    void loadApplications();
  }, [loadApplications]);

  const updateStatus = async (application: ManagedApplication, isActive: boolean) => {
    setUpdatingId(application.id);
    try {
      const updated = await api.patch<ManagedApplication>(
        `/organizations/${organizationId}/applications/${application.id}`,
        { is_active: isActive },
      );
      setApplications((items) => items.map((item) => (
        item.id === updated.id ? { ...item, ...updated } : item
      )));
      message.success(`${application.name}已${isActive ? '启用' : '停用'}`);
    } finally {
      setUpdatingId(null);
    }
  };

  const columns: ColumnsType<ManagedApplication> = [
    {
      title: '应用',
      dataIndex: 'name',
      render: (_, application) => (
        <div className="enterprise-application-name">
          <strong>{application.name}</strong>
          <Typography.Text type="secondary">{application.description || '暂无描述'}</Typography.Text>
        </div>
      ),
    },
    { title: '标识', dataIndex: 'slug', width: 200 },
    {
      title: '类型',
      dataIndex: 'kind',
      width: 120,
      render: (kind: ManagedApplication['kind']) => <Tag>{kindLabels[kind] ?? kind}</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'is_active',
      width: 150,
      render: (isActive: boolean, application) => (
        <Switch
          checked={isActive}
          checkedChildren="启用"
          unCheckedChildren="停用"
          disabled={!canAdmin || updatingId !== null}
          loading={updatingId === application.id}
          onChange={(checked) => void updateStatus(application, checked)}
          aria-label={`${application.name}启用状态`}
        />
      ),
    },
    { title: '更新时间', dataIndex: 'updated_at', width: 190 },
  ];

  return (
    <div className="enterprise-subpanel">
      {!canAdmin && (
        <Alert
          type="info"
          showIcon
          message="只读访问"
          description="只有组织 owner/admin 可启用或停用应用。"
        />
      )}
      <Alert
        type="info"
        showIcon
        message="应用可用性"
        description="停用后，应用将从应用中心隐藏，并且无法发起新的运行；已有历史数据不会被删除。"
      />
      <Table
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={applications}
        scroll={{ x: 860 }}
        pagination={false}
        locale={{ emptyText: <Empty description="暂无应用" /> }}
      />
    </div>
  );
}
