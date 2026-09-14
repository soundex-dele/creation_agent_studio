import { useEffect, useState } from 'react';
import { Form, Input, Modal, Select, Switch, message } from 'antd';
import { api } from '@/services/api';

interface AgentEditorModalProps {
  agentId: number | null;
  open: boolean;
  onClose: () => void;
  onSaved: () => void | Promise<void>;
}

interface AgentCategoryOption {
  id: number;
  name: string;
}

interface AgentDetail {
  name: string;
  slug: string;
  description: string;
  icon: string;
  category: { id: number };
  system_prompt: string;
  is_public: boolean;
}

interface AgentFormValues {
  category: number;
  name: string;
  slug: string;
  description: string;
  icon?: string;
  system_prompt: string;
  is_public: boolean;
}

const unwrap = <T,>(response: T[] | { results?: T[] }): T[] => (
  Array.isArray(response) ? response : response.results ?? []
);

const fieldError = (error: any): string => {
  const data = error?.response?.data;
  if (!data || typeof data !== 'object') return error?.message || '保存智能体失败';
  const first = Object.values(data).flat()[0];
  return typeof first === 'string' ? first : '保存智能体失败';
};

const AgentEditorModal = ({ agentId, open, onClose, onSaved }: AgentEditorModalProps) => {
  const [form] = Form.useForm<AgentFormValues>();
  const [categories, setCategories] = useState<AgentCategoryOption[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    Promise.all([
      api.get<AgentCategoryOption[] | { results?: AgentCategoryOption[] }>('/agents/categories/'),
      agentId ? api.get<AgentDetail>(`/agents/${agentId}/`) : Promise.resolve(null),
    ])
      .then(([categoryResponse, agent]) => {
        if (cancelled) return;
        setCategories(unwrap(categoryResponse));
        form.resetFields();
        if (agent) {
          form.setFieldsValue({
            category: agent.category.id,
            name: agent.name,
            slug: agent.slug,
            description: agent.description,
            icon: agent.icon,
            system_prompt: agent.system_prompt,
            is_public: agent.is_public,
          });
        } else {
          form.setFieldsValue({ icon: '🤖', is_public: false });
        }
      })
      .catch(() => message.error('加载智能体配置失败'))
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [agentId, form, open]);

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      setSaving(true);
      if (agentId) {
        await api.patch(`/agents/${agentId}/`, values);
        message.success('智能体已更新');
      } else {
        await api.post('/agents/', values);
        message.success('智能体已创建');
      }
      await onSaved();
      onClose();
    } catch (error: any) {
      if (!error?.errorFields) message.error(fieldError(error));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title={agentId ? '编辑智能体' : '新建智能体'}
      open={open}
      onCancel={onClose}
      onOk={handleSave}
      confirmLoading={saving}
      okText={agentId ? '保存' : '创建'}
      cancelText="取消"
      width={760}
      loading={loading}
      destroyOnClose
    >
      <Form form={form} layout="vertical" requiredMark="optional">
        <div className="agent-form-row">
          <Form.Item
            name="name"
            label="名称"
            rules={[{ required: true, whitespace: true, message: '请输入智能体名称' }]}
          >
            <Input placeholder="例如：短视频脚本助手" maxLength={100} />
          </Form.Item>
          <Form.Item
            name="slug"
            label="标识"
            rules={[
              { required: true, message: '请输入唯一标识' },
              { pattern: /^[a-z0-9]+(?:-[a-z0-9]+)*$/, message: '仅支持小写字母、数字和连字符' },
            ]}
          >
            <Input placeholder="video-script-assistant" maxLength={100} disabled={Boolean(agentId)} />
          </Form.Item>
        </div>
        <div className="agent-form-row agent-form-row-compact">
          <Form.Item
            name="category"
            label="分类"
            rules={[{ required: true, message: '请选择分类' }]}
          >
            <Select
              placeholder="选择智能体分类"
              options={categories.map((category) => ({
                value: category.id,
                label: category.name,
              }))}
            />
          </Form.Item>
          <Form.Item name="icon" label="图标">
            <Input placeholder="🤖" maxLength={50} />
          </Form.Item>
        </div>
        <Form.Item
          name="description"
          label="描述"
          rules={[{ required: true, whitespace: true, message: '请输入智能体描述' }]}
        >
          <Input.TextArea rows={3} placeholder="说明这个智能体适合完成什么任务" />
        </Form.Item>
        <Form.Item
          name="system_prompt"
          label="系统提示词"
          extra="定义智能体的身份、能力边界、工作流程和输出要求。"
          rules={[{ required: true, whitespace: true, message: '请输入系统提示词' }]}
        >
          <Input.TextArea
            rows={10}
            placeholder="你是一位专业的……"
            className="agent-system-prompt-input"
          />
        </Form.Item>
        <Form.Item name="is_public" label="公开到智能体市场" valuePropName="checked">
          <Switch checkedChildren="公开" unCheckedChildren="仅组织可见" />
        </Form.Item>
      </Form>
    </Modal>
  );
};

export default AgentEditorModal;
