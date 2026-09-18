import { useCallback, useEffect, useState } from 'react';
import { Alert, Button, Empty, Switch, Table, Tag, Typography, message } from 'antd';
import { LockOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { api } from '@/services/api';
import { useAuthStore } from '@/stores/useAuthStore';
import ResourcePermissionModal, {
  type AccessScope,
} from '@/components/Permissions/ResourcePermissionModal';

interface ManagedApplication {
  id: number;
  name: string;
  slug: string;
  description: string;
  kind: 'chat' | 'task' | 'custom';
  is_active: boolean;
  access_scope: AccessScope;
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

const accessLabels: Record<AccessScope, string> = {
  admin: '不额外授权',
  restricted: '指定账号',
  organization: '组织全员',
};

export default function ApplicationManagementPanel({
  organizationId,
}: {
  organizationId: string;
}) {
  const [applications, setApplications] = useState<ManagedApplication[]>([]);
  const [loading, setLoading] = useState(false);
  const [updatingId, setUpdatingId] = useState<number | null>(null);
  const [permissionApplication, setPermissionApplication] = useState<ManagedApplication | null>(null);
  const currentUser = useAuthStore((state) => state.user);
  const isPlatformAdmin = currentUser?.role === 'admin';
  const canToggleApplications = isPlatformAdmin || Boolean(currentUser?.can_toggle_applications);

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
          disabled={!canToggleApplications || updatingId !== null}
          loading={updatingId === application.id}
          onChange={(checked) => void updateStatus(application, checked)}
          aria-label={`${application.name}启用状态`}
        />
      ),
    },
    {
      title: '可见权限',
      dataIndex: 'access_scope',
      width: 140,
      render: (scope: AccessScope) => <Tag>{accessLabels[scope] ?? scope}</Tag>,
    },
    { title: '更新时间', dataIndex: 'updated_at', width: 190 },
    {
      title: '操作',
      width: 130,
      render: (_, application) => isPlatformAdmin ? (
        <Button
          icon={<LockOutlined aria-hidden="true" />}
          onClick={() => setPermissionApplication(application)}
        >
          权限设置
        </Button>
      ) : '—',
    },
  ];

  return (
    <div className="enterprise-subpanel">
      {!canToggleApplications && (
        <Alert
          type="info"
          showIcon
          message="只读访问"
          description="当前账号未获授权启用或停用应用。"
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
      <ResourcePermissionModal
        resourceType="application"
        resourceId={permissionApplication?.slug ?? null}
        resourceName={permissionApplication?.name ?? ''}
        open={permissionApplication !== null}
        onClose={() => setPermissionApplication(null)}
        onSaved={loadApplications}
      />
    </div>
  );
}
