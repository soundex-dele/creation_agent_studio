import { useEffect, useState } from 'react';
import { Form, Modal, Radio, Select, Space, Spin, message } from 'antd';
import { api } from '@/services/api';
import './ResourcePermissionModal.css';

export type ResourceVisibility = 'private' | 'restricted' | 'organization';
export type ResourceRole = 'viewer' | 'user' | 'operator' | 'editor';

interface ResourceGrant {
  user_id: number;
  role: ResourceRole;
}

interface PermissionValues {
  visibility: ResourceVisibility;
  grants: ResourceGrant[];
}

interface Account {
  id: number;
  username: string;
  email: string;
}

interface ResourcePermissionResponse extends PermissionValues {
  available_users: Account[];
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
  value: ResourceVisibility;
  title: string;
  description: string;
}> = [
  {
    value: 'private',
    title: '仅创建者',
    description: '只有创建者、组织管理员和平台管理员可以访问。',
  },
  {
    value: 'restricted',
    title: '指定账号',
    description: '为组织成员分别授予查看、使用、运维或编辑权限。',
  },
  {
    value: 'organization',
    title: '组织内全部账号',
    description: '组织内有效成员可查看和使用，组织角色继续决定运维与编辑能力。',
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
  const scope = Form.useWatch('visibility', form);
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
    api.get<ResourcePermissionResponse>(endpoint)
      .then((permission) => {
        if (!active) return;
        setAccounts(permission.available_users ?? []);
        form.setFieldsValue({
          visibility: permission.visibility,
          grants: permission.grants ?? [],
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
        visibility: values.visibility,
        grants: values.visibility === 'restricted'
          ? values.grants ?? []
          : [],
      });
      message.success('权限已更新');
      await onSaved?.();
      onClose();
    } catch (error: any) {
      const fieldErrors = error?.response?.data;
      if (fieldErrors?.grants) {
        form.setFields([{ name: 'grants', errors: fieldErrors.grants }]);
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
          initialValues={{ visibility: 'private', grants: [] }}
          onFinish={save}
        >
          <Form.Item name="visibility" label="可见范围" rules={[{ required: true }]}>
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
            <Form.List name="grants" rules={[{
              validator: async (_, grants) => {
                if (!grants?.length) throw new Error('请至少添加一个授权账号');
              },
            }]}
            >
              {(fields, { add, remove }, { errors }) => (
                <Space direction="vertical" style={{ width: '100%' }}>
                  {fields.map((field) => (
                    <Space key={field.key} align="baseline" wrap>
                      <Form.Item
                        {...field}
                        name={[field.name, 'user_id']}
                        rules={[{ required: true, message: '请选择账号' }]}
                      >
                        <Select
                          showSearch
                          optionFilterProp="label"
                          placeholder="选择组织成员"
                          style={{ width: 300 }}
                          options={accounts.map((account) => ({
                            value: account.id,
                            label: account.email
                              ? `${account.username} (${account.email})`
                              : account.username,
                          }))}
                        />
                      </Form.Item>
                      <Form.Item
                        {...field}
                        name={[field.name, 'role']}
                        initialValue="user"
                        rules={[{ required: true, message: '请选择角色' }]}
                      >
                        <Select style={{ width: 120 }} options={[
                          { value: 'viewer', label: '查看者' },
                          { value: 'user', label: '使用者' },
                          { value: 'operator', label: '运维者' },
                          { value: 'editor', label: '编辑者' },
                        ]} />
                      </Form.Item>
                      <a onClick={() => remove(field.name)}>移除</a>
                    </Space>
                  ))}
                  <a onClick={() => add({ role: 'user' })}>+ 添加授权账号</a>
                  <Form.ErrorList errors={errors} />
                </Space>
              )}
            </Form.List>
          )}
        </Form>
      )}
    </Modal>
  );
}
