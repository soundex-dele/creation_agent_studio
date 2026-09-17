import { useEffect, useState } from 'react';
import { Button, Card, Form, Input, InputNumber, Select, Space, Spin, Switch, message } from 'antd';
import { useNavigate, useParams } from 'react-router-dom';

import { api } from '@/services/api';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import type { Delegate } from '@/types/delegate';
import './Delegates.css';

type Choice = { id: number; name: string; description?: string };
const unwrap = <T,>(value: T[] | { results?: T[] }): T[] => Array.isArray(value) ? value : value.results ?? [];

const DelegateEditorPage = () => {
  const { id } = useParams<{ id: string }>();
  const organizationId = useOrganizationStore((state) => state.currentOrganizationId);
  const navigate = useNavigate();
  const [form] = Form.useForm();
  const [agents, setAgents] = useState<Choice[]>([]);
  const [applications, setApplications] = useState<Choice[]>([]);
  const [delegate, setDelegate] = useState<Delegate | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!organizationId) return;
    setLoading(true);
    Promise.all([
      api.get<any>('/agents/'),
      api.get<any>('/apps/'),
      id ? api.get<Delegate>(`/organizations/${organizationId}/delegates/${id}`) : Promise.resolve(null),
    ]).then(([agentData, appData, current]) => {
      setAgents(unwrap(agentData));
      setApplications(unwrap(appData));
      setDelegate(current);
      form.setFieldsValue(current ? {
        ...current,
        organization_shared: current.visibility === 'organization',
        principles_text: current.principles.join('\n'),
        model: String(current.model_config.model || ''),
        adapter: String(current.model_config.adapter || ''),
      } : {
        icon: '🧭', organization_shared: false,
        limits: { max_tasks: 12, max_replans: 3, max_parallelism: 3, timeout_seconds: 1800 },
      });
    }).finally(() => setLoading(false));
  }, [form, id, organizationId]);

  const save = async (deploy: boolean) => {
    if (!organizationId) return;
    const values = await form.validateFields();
    const payload = {
      name: values.name, slug: values.slug, description: values.description || '', icon: values.icon || '🧭',
      visibility: values.organization_shared ? 'organization' : 'private',
      role_prompt: values.role_prompt,
      principles: String(values.principles_text || '').split('\n').map((v) => v.trim()).filter(Boolean),
      output_preferences: values.output_preferences || '',
      agent_ids: values.agent_ids || [], application_ids: values.application_ids || [],
      model_config: { model: values.model || '', adapter: values.adapter || '' },
      limits: values.limits,
    };
    setSaving(true);
    try {
      const saved = id
        ? await api.patch<Delegate>(`/organizations/${organizationId}/delegates/${id}`, payload)
        : await api.post<Delegate>(`/organizations/${organizationId}/delegates`, payload);
      if (deploy) {
        const revision = await api.post<{ id: string }>(
          `/organizations/${organizationId}/delegates/${saved.id}/publish`,
          { expected_draft_version: saved.draft_version, release_notes: '发布 AI 分身配置' },
        );
        await api.post(`/organizations/${organizationId}/delegates/${saved.id}/deploy`, {
          revision_id: revision.id,
        });
        message.success('AI 分身已保存并部署');
      } else message.success('草稿已保存');
      navigate('/delegates');
    } catch (error: any) {
      message.error(error?.response?.data?.detail || JSON.stringify(error?.response?.data || '保存失败'));
    } finally { setSaving(false); }
  };

  if (loading) return <Spin size="large" />;
  return (
    <div className="delegate-editor">
      <div className="delegates-heading"><div><h1>{id ? '配置 AI 分身' : '新建 AI 分身'}</h1><p>定义职责、可调度团队和安全执行边界。</p></div></div>
      <Form form={form} layout="vertical">
        <Card title="身份与职责">
          <div className="delegate-form-grid">
            <Form.Item name="name" label="名称" rules={[{ required: true }]}><Input /></Form.Item>
            <Form.Item name="slug" label="唯一标识" rules={[{ required: true }]}><Input disabled={Boolean(delegate)} /></Form.Item>
            <Form.Item name="icon" label="图标"><Input maxLength={50} /></Form.Item>
            <Form.Item name="organization_shared" label="组织共享" valuePropName="checked"><Switch /></Form.Item>
          </div>
          <Form.Item name="description" label="简介"><Input /></Form.Item>
          <Form.Item name="role_prompt" label="角色与职责" rules={[{ required: true }]}><Input.TextArea rows={6} /></Form.Item>
          <Form.Item name="principles_text" label="工作原则（每行一条）"><Input.TextArea rows={4} /></Form.Item>
          <Form.Item name="output_preferences" label="交付偏好"><Input.TextArea rows={3} /></Form.Item>
        </Card>
        <Card title="可调度团队">
          <Form.Item name="agent_ids" label="智能体"><Select mode="multiple" options={agents.map((v) => ({ value: v.id, label: v.name }))} /></Form.Item>
          <Form.Item name="application_ids" label="应用"><Select mode="multiple" options={applications.map((v) => ({ value: v.id, label: v.name }))} /></Form.Item>
        </Card>
        <Card title="模型与执行边界">
          <div className="delegate-form-grid">
            <Form.Item name="model" label="规划模型"><Input placeholder="使用组织默认模型" /></Form.Item>
            <Form.Item name="adapter" label="模型适配器"><Input placeholder="使用组织默认适配器" /></Form.Item>
            <Form.Item name={['limits', 'max_tasks']} label="最多子任务"><InputNumber min={1} max={12} /></Form.Item>
            <Form.Item name={['limits', 'max_replans']} label="最多重规划"><InputNumber min={0} max={3} /></Form.Item>
            <Form.Item name={['limits', 'max_parallelism']} label="最大并行"><InputNumber min={1} max={3} /></Form.Item>
            <Form.Item name={['limits', 'timeout_seconds']} label="超时（秒）"><InputNumber min={60} max={1800} /></Form.Item>
          </div>
        </Card>
        <Space>
          <Button onClick={() => navigate('/delegates')}>取消</Button>
          <Button loading={saving} onClick={() => void save(false)}>保存草稿</Button>
          <Button type="primary" loading={saving} onClick={() => void save(true)}>保存并部署</Button>
        </Space>
      </Form>
    </div>
  );
};

export default DelegateEditorPage;
