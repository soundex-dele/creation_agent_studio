import { useEffect, useState } from 'react';
import { Form, Modal, Radio, Select, Spin, message } from 'antd';
import { api } from '@/services/api';
import './ResourcePermissionModal.css';

export type AccessScope = 'admin' | 'restricted' | 'organization';

interface PermissionValues {
  access_scope: AccessScope;
  allowed_user_ids: number[];
}

interface Account {
  id: number;
  username: string;
  email: string;
  role: string;
  is_active: boolean;
  can_view_agents: boolean;
  can_view_applications: boolean;
}

interface AccountPage {
  count?: number;
  results?: Account[];
}

async function loadAllAccounts() {
  const first = await api.get<AccountPage | Account[]>('/auth/admin/users/', { page: 1 });
  if (Array.isArray(first)) return first;
  const firstItems = first.results ?? [];
  const pageCount = Math.ceil((first.count ?? firstItems.length) / 20);
  const remaining = await Promise.all(Array.from(
    { length: Math.max(0, pageCount - 1) },
    (_, index) => api.get<AccountPage>('/auth/admin/users/', { page: index + 2 }),
  ));
  return [...firstItems, ...remaining.flatMap((page) => page.results ?? [])];
}

interface ResourcePermissionModalProps {
  resourceType: 'agent' | 'application';
  resourceId: number | string | null;
  resourceName: string;
  open: boolean;
  onClose: () => void;
  onSaved?: () => void | Promise<void>;
}

const scopeOptions: Array<{
  value: AccessScope;
  title: string;
  description: string;
}> = [
  {
    value: 'admin',
    title: '不额外授权',
    description: '未单独指定账号；已开通对应查看能力的账号仍可查看。',
  },
  {
    value: 'restricted',
    title: '指定账号',
    description: '下方选中的账号即使没有全局查看能力，也可以查看和使用。',
  },
  {
    value: 'organization',
    title: '组织内全部账号',
    description: '组织内所有有效成员均可查看，无需单独开通查看能力。',
  },
];

export default function ResourcePermissionModal({
  resourceType,
  resourceId,
  resourceName,
  open,
  onClose,
  onSaved,
}: ResourcePermissionModalProps) {
  const [form] = Form.useForm<PermissionValues>();
  const scope = Form.useWatch('access_scope', form);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  const endpoint = resourceId == null
    ? ''
    : resourceType === 'agent'
      ? `/agents/${resourceId}/permissions/`
      : `/apps/${resourceId}/permissions/`;

  useEffect(() => {
    if (!open || !endpoint) return;
    let active = true;
    setLoading(true);
    Promise.all([
      api.get<PermissionValues>(endpoint),
      loadAllAccounts(),
    ])
      .then(([permission, accountResponse]) => {
        if (!active) return;
        setAccounts(accountResponse.filter((item) => item.is_active));
        form.setFieldsValue({
          access_scope: permission.access_scope,
          allowed_user_ids: permission.allowed_user_ids ?? [],
        });
      })
      .catch(() => {
        if (active) message.error('加载权限设置失败');
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [endpoint, form, open]);

  const save = async (values: PermissionValues) => {
    setSaving(true);
    try {
      await api.put(endpoint, {
        access_scope: values.access_scope,
        allowed_user_ids: values.access_scope === 'restricted'
          ? values.allowed_user_ids ?? []
          : [],
      });
      message.success('权限已更新');
      await onSaved?.();
      onClose();
    } catch (error: any) {
      const fieldErrors = error?.response?.data;
      if (fieldErrors?.allowed_user_ids) {
        form.setFields([{ name: 'allowed_user_ids', errors: fieldErrors.allowed_user_ids }]);
      } else {
        message.error(fieldErrors?.detail || '保存权限失败');
      }
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title={`设置权限 · ${resourceName}`}
      open={open}
      onCancel={onClose}
      okText="保存"
      cancelText="取消"
      confirmLoading={saving}
      okButtonProps={{ htmlType: 'submit', form: 'resource-permission-form' }}
      destroyOnHidden
    >
      {loading ? (
        <div className="resource-permission-loading"><Spin /></div>
      ) : (
        <Form<PermissionValues>
          id="resource-permission-form"
          form={form}
          layout="vertical"
          initialValues={{ access_scope: 'admin', allowed_user_ids: [] }}
          onFinish={save}
        >
          <Form.Item name="access_scope" label="可见范围" rules={[{ required: true }]}>
            <Radio.Group className="resource-permission-options">
              {scopeOptions.map((option) => (
                <Radio key={option.value} value={option.value} className="resource-permission-option">
                  <span className="resource-permission-title">{option.title}</span>
                  <span className="resource-permission-description">{option.description}</span>
                </Radio>
              ))}
            </Radio.Group>
          </Form.Item>
          {scope === 'restricted' && (
            <Form.Item
              name="allowed_user_ids"
              label="可访问账号"
              rules={[{ required: true, type: 'array', min: 1, message: '请至少选择一个账号' }]}
            >
              <Select
                mode="multiple"
                showSearch
                optionFilterProp="label"
                placeholder="搜索并选择账号"
                options={accounts.map((account) => ({
                  value: account.id,
                  label: (account.email
                    ? `${account.username} (${account.email})`
                    : account.username) + (
                    account.role === 'admin'
                    || (resourceType === 'agent'
                      ? account.can_view_agents
                      : account.can_view_applications)
                      ? ' · 已开通查看能力'
                      : ' · 单独授权'
                  ),
                }))}
              />
            </Form.Item>
          )}
        </Form>
      )}
    </Modal>
  );
}
