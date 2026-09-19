import { useEffect, useMemo, useState } from 'react';
import { Alert, Form, Modal, Spin, message } from 'antd';
import { api } from '@/services/api';
import {
  getResourcePermissionEndpoint,
  ResourcePermissionFields,
  type Account,
  type PermissionValues,
  type ResourcePermissionResponse,
} from './ResourcePermissionModal';
import './ResourcePermissionModal.css';

export interface BulkPermissionResource {
  id: number;
  permissionId: number | string;
  name: string;
  ownerId?: number;
}

interface BulkResourcePermissionModalProps {
  resourceType: 'agent' | 'application';
  resources: BulkPermissionResource[];
  open: boolean;
  onClose: () => void;
  onSaved?: () => void | Promise<void>;
}

const resourceLabels = {
  agent: '智能体',
  application: '应用',
};

export default function BulkResourcePermissionModal({
  resourceType,
  resources,
  open,
  onClose,
  onSaved,
}: BulkResourcePermissionModalProps) {
  const [form] = Form.useForm<PermissionValues>();
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const resourceLabel = resourceLabels[resourceType];
  const selectedNames = useMemo(() => resources.map((resource) => resource.name), [resources]);

  useEffect(() => {
    if (!open || resources.length === 0) return;
    let active = true;
    const first = resources[0];
    const ownerIds = new Set(resources.map((resource) => resource.ownerId).filter(Boolean));
    form.resetFields();
    setAccounts([]);
    setLoading(true);
    api.get<ResourcePermissionResponse>(
      getResourcePermissionEndpoint(resourceType, first.permissionId),
    )
      .then((permission) => {
        if (!active) return;
        setAccounts((permission.available_users ?? []).filter(
          (account) => !ownerIds.has(account.id),
        ));
      })
      .catch(() => {
        if (active) message.error('加载组织成员失败，请重试');
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [form, open, resourceType, resources]);

  const save = async (values: PermissionValues) => {
    setSaving(true);
    try {
      const response = await api.put<{ updated: number }>(
        resourceType === 'agent'
          ? '/agents/bulk-permissions/'
          : '/apps/bulk-permissions/',
        {
          resource_ids: resources.map((resource) => resource.id),
          visibility: values.visibility,
          grants: values.visibility === 'restricted' ? values.grants ?? [] : [],
        },
      );
      message.success(`已更新 ${response.updated} 个${resourceLabel}的权限`);
      await onSaved?.();
      onClose();
    } catch (error: any) {
      const fieldErrors = error?.response?.data;
      if (fieldErrors?.grants) {
        form.setFields([{ name: 'grants', errors: [String(fieldErrors.grants)] }]);
      } else {
        message.error(fieldErrors?.detail || fieldErrors?.resource_ids || '批量保存权限失败');
      }
    } finally {
      setSaving(false);
    }
  };

  const visibleNames = selectedNames.slice(0, 3).join('、');
  const remainingCount = Math.max(0, selectedNames.length - 3);

  return (
    <Modal
      title={`批量设置${resourceLabel}权限`}
      open={open}
      onCancel={onClose}
      okText={`应用到 ${resources.length} 项`}
      cancelText="取消"
      confirmLoading={saving}
      okButtonProps={{
        htmlType: 'submit',
        form: 'bulk-resource-permission-form',
        disabled: loading || resources.length === 0,
      }}
      destroyOnHidden
    >
      <Alert
        type="warning"
        showIcon
        message={`将覆盖所选 ${resources.length} 个${resourceLabel}的现有权限`}
        description="所有所选项目会使用同一套可见范围和账号授权；保存过程为原子操作，任一项目校验失败都不会修改。"
        className="resource-permission-bulk-alert"
      />
      <div className="resource-permission-selection" aria-live="polite">
        已选择：{visibleNames}{remainingCount > 0 ? ` 等 ${selectedNames.length} 项` : ''}
      </div>
      {loading ? (
        <div className="resource-permission-loading"><Spin /></div>
      ) : (
        <Form<PermissionValues>
          id="bulk-resource-permission-form"
          form={form}
          layout="vertical"
          initialValues={{ grants: [] }}
          onFinish={save}
        >
          <ResourcePermissionFields form={form} accounts={accounts} />
        </Form>
      )}
    </Modal>
  );
}
