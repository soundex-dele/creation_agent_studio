import { useCallback, useEffect, useState, type Key } from 'react';
import { Alert, Button, Empty, Space, Switch, Table, Tag, Typography, message } from 'antd';
import { LockOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { api } from '@/services/api';
import ResourcePermissionModal, {
  type ResourceVisibility,
} from '@/components/Permissions/ResourcePermissionModal';
import BulkResourcePermissionModal from '@/components/Permissions/BulkResourcePermissionModal';

interface ManagedApplication {
  id: number;
  owner_id: number;
  name: string;
  slug: string;
  description: string;
  kind: 'chat' | 'task' | 'custom';
  is_active: boolean;
  visibility: ResourceVisibility;
  can_toggle: boolean;
  can_manage_permissions: boolean;
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

const accessLabels: Record<ResourceVisibility, string> = {
  private: '仅创建者',
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
  const [selectedRowKeys, setSelectedRowKeys] = useState<Key[]>([]);
  const [bulkPermissionOpen, setBulkPermissionOpen] = useState(false);

  const loadApplications = useCallback(async () => {
    setLoading(true);
    try {
      const response = await api.get<ApplicationListResponse | ManagedApplication[]>(
        `/organizations/${organizationId}/applications`,
        { limit: 200 },
      );
      const items = Array.isArray(response) ? response : response.results ?? [];
      setApplications(items);
      setSelectedRowKeys((current) => current.filter((key) => (
        items.some((item) => item.id === key && item.can_manage_permissions)
      )));
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
          disabled={!application.can_toggle || updatingId !== null}
          loading={updatingId === application.id}
          onChange={(checked) => void updateStatus(application, checked)}
          aria-label={`${application.name}启用状态`}
        />
      ),
    },
    {
      title: '可见权限',
      dataIndex: 'visibility',
      width: 140,
      render: (scope: ResourceVisibility) => <Tag>{accessLabels[scope] ?? scope}</Tag>,
    },
    { title: '更新时间', dataIndex: 'updated_at', width: 190 },
    {
      title: '操作',
      width: 130,
      render: (_, application) => application.can_manage_permissions ? (
        <Button
          icon={<LockOutlined aria-hidden="true" />}
          onClick={() => setPermissionApplication(application)}
        >
          权限设置
        </Button>
      ) : '—',
    },
  ];

  const selectedApplications = applications.filter((application) => (
    selectedRowKeys.includes(application.id)
  ));

  return (
    <div className="enterprise-subpanel">
      <Alert
        type="info"
        showIcon
        message="应用可用性"
        description="停用后，应用将从应用中心隐藏，并且无法发起新的运行；按钮是否可用由组织角色和资源授权决定。"
      />
      <div className="enterprise-bulk-toolbar">
        <Typography.Text type="secondary">
          勾选应用后可统一覆盖可见范围和账号授权，支持表头全选。
        </Typography.Text>
        <Space wrap size={12}>
          <Button
            disabled={selectedRowKeys.length === 0}
            onClick={() => setSelectedRowKeys([])}
          >
            取消选择
          </Button>
          <Button
            type="primary"
            icon={<LockOutlined aria-hidden="true" />}
            disabled={selectedRowKeys.length === 0}
            onClick={() => setBulkPermissionOpen(true)}
          >
            批量设置权限{selectedRowKeys.length > 0 ? `（${selectedRowKeys.length}）` : ''}
          </Button>
        </Space>
      </div>
      <Table
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={applications}
        rowSelection={{
          selectedRowKeys,
          onChange: setSelectedRowKeys,
          getCheckboxProps: (application) => ({
            disabled: !application.can_manage_permissions,
            'aria-label': `选择${application.name}`,
          }),
        }}
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
      <BulkResourcePermissionModal
        resourceType="application"
        resources={selectedApplications.map((application) => ({
          id: application.id,
          permissionId: application.slug,
          name: application.name,
          ownerId: application.owner_id,
        }))}
        open={bulkPermissionOpen}
        onClose={() => setBulkPermissionOpen(false)}
        onSaved={async () => {
          await loadApplications();
          setSelectedRowKeys([]);
        }}
      />
    </div>
  );
}
