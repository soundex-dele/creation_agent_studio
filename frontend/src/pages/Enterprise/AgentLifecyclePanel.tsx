import { useCallback, useEffect, useState } from 'react';
import { Alert, Button, Card, Form, Input, Modal, Select, Space, Table, Tag, message } from 'antd';
import { api } from '@/services/api';

type Row = Record<string, any>;
const normalize = (value: any): Row[] => Array.isArray(value) ? value : value?.results ?? [];
const asJson = (value: string, fallback: any) => value?.trim() ? JSON.parse(value) : fallback;

export default function AgentLifecyclePanel() {
  const [agents, setAgents] = useState<Row[]>([]); const [agentId, setAgentId] = useState<number>();
  const [versions, setVersions] = useState<Row[]>([]); const [deployments, setDeployments] = useState<Row[]>([]);
  const [versionOpen, setVersionOpen] = useState(false); const [versionForm] = Form.useForm();
  const loadAgents = useCallback(async () => { const data = normalize(await api.get('/agents/', { mine: 1 })); setAgents(data); setAgentId(current => data.some(a => a.id === current) ? current : data[0]?.id); }, []);
  const loadDetails = useCallback(async () => { if (!agentId) { setVersions([]); setDeployments([]); return; } const [v, d] = await Promise.all([api.get(`/agents/${agentId}/versions/`), api.get(`/agents/${agentId}/deployments/`)]); setVersions(v as Row[]); setDeployments(d as Row[]); }, [agentId]);
  useEffect(() => { void loadAgents(); }, [loadAgents]); useEffect(() => { void loadDetails(); }, [loadDetails]);
  const createVersion = async () => { try { const values = await versionForm.validateFields(); for (const key of ['model_config','tool_config','skill_bindings','knowledge_config','guardrail_config','workflow_config']) values[key] = asJson(values[key], ['tool_config','skill_bindings','knowledge_config'].includes(key) ? [] : {}); await api.post(`/agents/${agentId}/versions/`, values); message.success('版本草稿已创建'); setVersionOpen(false); await loadDetails(); } catch (error: any) { if (!error?.errorFields) message.error(error.message || 'JSON 格式错误'); } };
  const act = async (version: Row, action: string, payload: Row = {}) => { await api.post(`/agents/${agentId}/versions/${version.id}/${action}/`, payload); message.success('操作成功'); await loadDetails(); };
  const deploy = async (version: Row, environment: string) => { await api.post(`/agents/${agentId}/deploy/`, { version_id: version.id, environment }); message.success(`已发布到 ${environment}`); await loadDetails(); };
  const rollback = async (environment: string) => { await api.post(`/agents/${agentId}/rollback/`, { environment }); message.success(`${environment} 已回滚`); await loadDetails(); };
  return <div className="enterprise-subpanel">
    <Alert type="info" showIcon message="发布流程" description="开发者创建草稿并送审，组织管理员批准后发布到 staging/production；配置评测套件后，生产发布必须通过质量门禁。" />
    <Card title="智能体版本管理" extra={<Space><Select style={{ width: 260 }} placeholder="选择组织智能体" value={agentId} onChange={setAgentId} options={agents.map(a => ({ value: a.id, label: a.name }))} /><Button type="primary" disabled={!agentId} onClick={() => { versionForm.resetFields(); setVersionOpen(true); }}>新建版本</Button></Space>}>
      {!agents.length ? <Alert type="warning" message="当前组织暂无智能体，请先通过智能体 API 创建组织智能体。" /> : <Table rowKey="id" dataSource={versions} scroll={{ x: 1100 }} columns={[
        { title: '版本', dataIndex: 'version' }, { title: '状态', dataIndex: 'status', render: v => <Tag color={v === 'approved' ? 'green' : v === 'rejected' ? 'red' : 'blue'}>{v}</Tag> }, { title: '变更说明', dataIndex: 'changelog' },
        { title: '操作', width: 520, render: (_, v: Row) => <Space wrap>{v.status === 'draft' && <Button size="small" onClick={() => act(v, 'submit')}>送审</Button>}{v.status === 'in_review' && <><Button size="small" type="primary" onClick={() => act(v, 'review', { decision: 'approved' })}>批准</Button><Button danger size="small" onClick={() => act(v, 'review', { decision: 'rejected' })}>拒绝</Button></>}<Button size="small" onClick={() => deploy(v, 'development')}>发布开发</Button>{v.status === 'approved' && <><Button size="small" onClick={() => deploy(v, 'staging')}>发布预发</Button><Button size="small" type="primary" onClick={() => deploy(v, 'production')}>发布生产</Button></>}</Space> },
      ]} />}
    </Card>
    <Card title="环境部署" style={{ marginTop: 16 }}><Table rowKey="id" pagination={false} dataSource={deployments} columns={[{ title: '环境', dataIndex: 'environment' }, { title: '当前版本', dataIndex: 'version_name' }, { title: '发布时间', dataIndex: 'deployed_at' }, { title: '操作', render: (_, d: Row) => <Button size="small" disabled={!d.previous_version} onClick={() => rollback(d.environment)}>回滚</Button> }]} /></Card>
    <Modal title="新建智能体版本" open={versionOpen} onCancel={() => setVersionOpen(false)} onOk={createVersion} width={800}><Form layout="vertical" form={versionForm}><Form.Item name="version" label="版本号" rules={[{ required: true }]}><Input placeholder="1.0.0" /></Form.Item><Form.Item name="system_prompt" label="系统提示词" rules={[{ required: true }]}><Input.TextArea rows={5} /></Form.Item><Form.Item name="changelog" label="变更说明"><Input.TextArea /></Form.Item>{[['model_config','{}'],['tool_config','[]'],['skill_bindings','[]'],['knowledge_config','[]'],['guardrail_config','{}'],['workflow_config','{}']].map(([key, value]) => <Form.Item key={key} name={key} label={`${key}（JSON）`} initialValue={value}><Input.TextArea rows={2} /></Form.Item>)}</Form></Modal>
  </div>;
}
