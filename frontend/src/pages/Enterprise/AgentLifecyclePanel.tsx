import { useCallback, useEffect, useState } from 'react';
import { Alert, Button, Card, Form, Input, Modal, Select, Space, Switch, Table, Tag, message } from 'antd';
import { LockOutlined } from '@ant-design/icons';
import { api } from '@/services/api';
import { useAuthStore } from '@/stores/useAuthStore';
import ResourcePermissionModal from '@/components/Permissions/ResourcePermissionModal';

type Row = Record<string, any>;
const normalize = (value: any): Row[] => Array.isArray(value) ? value : value?.results ?? [];
const asJson = (value: string, fallback: any) => value?.trim() ? JSON.parse(value) : fallback;

export default function AgentLifecyclePanel() {
  const [agents, setAgents] = useState<Row[]>([]); const [agentId, setAgentId] = useState<number>();
  const [versions, setVersions] = useState<Row[]>([]); const [deployment, setDeployment] = useState<Row | null>(null);
  const [versionOpen, setVersionOpen] = useState(false); const [versionForm] = Form.useForm();
  const [permissionOpen, setPermissionOpen] = useState(false);
  const currentUser = useAuthStore((state) => state.user);
  const isPlatformAdmin = currentUser?.role === 'admin';
  const canUpdateAgents = isPlatformAdmin || Boolean(currentUser?.can_update_agents);
  const canDeleteAgents = isPlatformAdmin || Boolean(currentUser?.can_delete_agents);
  const canToggleAgents = isPlatformAdmin || Boolean(currentUser?.can_toggle_agents);
  const canAdministerAgents = canUpdateAgents || canDeleteAgents || canToggleAgents;
  const selectedAgent = agents.find((agent) => agent.id === agentId);
  const loadAgents = useCallback(async () => { const data = normalize(await api.get('/agents/', { mine: 1, manageable: canAdministerAgents ? 1 : undefined })); setAgents(data); setAgentId(current => data.some(a => a.id === current) ? current : data[0]?.id); }, [canAdministerAgents]);
  const loadDetails = useCallback(async () => { if (!agentId || selectedAgent?.is_active === false) { setVersions([]); setDeployment(null); return; } const [v, d] = await Promise.all([api.get(`/agents/${agentId}/versions/`), api.get(`/agents/${agentId}/deployment/`)]); setVersions(v as Row[]); setDeployment(d as Row | null); }, [agentId, selectedAgent?.is_active]);
  useEffect(() => { void loadAgents(); }, [loadAgents]); useEffect(() => { void loadDetails(); }, [loadDetails]);
  const createVersion = async () => { try { const values = await versionForm.validateFields(); for (const key of ['model_config','tool_config','knowledge_config','guardrail_config','workflow_config']) values[key] = asJson(values[key], ['tool_config','knowledge_config'].includes(key) ? [] : {}); await api.post(`/agents/${agentId}/versions/`, values); message.success('版本草稿已创建'); setVersionOpen(false); await loadDetails(); } catch (error: any) { if (!error?.errorFields) message.error(error.message || 'JSON 格式错误'); } };
  const act = async (version: Row, action: string, payload: Row = {}) => { await api.post(`/agents/${agentId}/versions/${version.id}/${action}/`, payload); message.success('操作成功'); await loadDetails(); };
  const deploy = async (version: Row) => { await api.post(`/agents/${agentId}/deploy/`, { version_id: version.id }); message.success('版本已激活'); await loadDetails(); };
  const rollback = async () => { await api.post(`/agents/${agentId}/rollback/`, {}); message.success('已回滚'); await loadDetails(); };
  const toggleStatus = async (isActive: boolean) => { if (!agentId) return; const updated = await api.patch<Row>(`/agents/${agentId}/status/`, { is_active: isActive }); setAgents(items => items.map(item => item.id === agentId ? { ...item, ...updated } : item)); message.success(`智能体已${isActive ? '启用' : '停用'}`); };
  return <div className="enterprise-subpanel">
    <Alert type="info" showIcon message="智能体管理" description="修改权限用于版本内容，启停权限用于智能体可用状态、版本激活和回滚；各项能力独立授权。" />
    <Card title="智能体版本与权限" extra={<Space wrap><Select style={{ width: 260 }} placeholder="选择组织智能体" value={agentId} onChange={setAgentId} options={agents.map(a => ({ value: a.id, label: `${a.name}${a.is_active ? '' : '（已停用）'}` }))} />{canToggleAgents && <Switch checked={Boolean(selectedAgent?.is_active)} checkedChildren="启用" unCheckedChildren="停用" disabled={!agentId} onChange={(checked) => void toggleStatus(checked)} aria-label={`${selectedAgent?.name ?? '智能体'}启用状态`} />}{isPlatformAdmin && <Button icon={<LockOutlined aria-hidden="true" />} disabled={!agentId} onClick={() => setPermissionOpen(true)}>权限设置</Button>}{canUpdateAgents && <Button type="primary" disabled={!agentId || selectedAgent?.is_active === false} onClick={() => { versionForm.resetFields(); setVersionOpen(true); }}>新版本</Button>}</Space>}>
      {!agents.length ? <Alert type="warning" message="当前组织暂无智能体，请先通过智能体 API 创建组织智能体。" /> : <Table rowKey="id" dataSource={versions} scroll={{ x: 1100 }} columns={[
        { title: '版本', dataIndex: 'version' }, { title: '状态', dataIndex: 'status', render: v => <Tag color={v === 'approved' ? 'green' : v === 'rejected' ? 'red' : 'blue'}>{v}</Tag> }, { title: '变更说明', dataIndex: 'changelog' },
        { title: '操作', width: 520, render: (_, v: Row) => (canUpdateAgents || canToggleAgents) ? <Space wrap>{canUpdateAgents && v.status === 'draft' && <Button size="small" onClick={() => act(v, 'submit')}>送审</Button>}{canUpdateAgents && v.status === 'in_review' && <><Button size="small" type="primary" onClick={() => act(v, 'review', { decision: 'approved' })}>批准</Button><Button danger size="small" onClick={() => act(v, 'review', { decision: 'rejected' })}>拒绝</Button></>}{canToggleAgents && <Button size="small" type="primary" onClick={() => deploy(v)}>激活版本</Button>}</Space> : '—' },
      ]} />}
    </Card>
    <Card title="当前激活部署" style={{ marginTop: 16 }}><Table rowKey="id" pagination={false} dataSource={deployment ? [deployment] : []} columns={[{ title: '当前 Revision', dataIndex: 'revision_id' }, { title: '部署版本', dataIndex: 'version' }, { title: '更新时间', dataIndex: 'updated_at' }, { title: '操作', render: (_, d: Row) => canToggleAgents ? <Button size="small" disabled={!d.previous_revision_id} onClick={() => rollback()}>回滚</Button> : '—' }]} /></Card>
    <Modal title="新建智能体版本" open={versionOpen} onCancel={() => setVersionOpen(false)} onOk={createVersion} width={800}><Form layout="vertical" form={versionForm}><Form.Item name="version" label="版本号" rules={[{ required: true }]}><Input placeholder="1.0.0" /></Form.Item><Form.Item name="system_prompt" label="系统提示词" rules={[{ required: true }]}><Input.TextArea rows={5} /></Form.Item><Form.Item name="changelog" label="变更说明"><Input.TextArea /></Form.Item>{[['model_config','{}'],['tool_config','[]'],['knowledge_config','[]'],['guardrail_config','{}'],['workflow_config','{}']].map(([key, value]) => <Form.Item key={key} name={key} label={`${key}（JSON）`} initialValue={value}><Input.TextArea rows={2} /></Form.Item>)}</Form></Modal>
    <ResourcePermissionModal
      resourceType="agent"
      resourceId={agentId ?? null}
      resourceName={agents.find((agent) => agent.id === agentId)?.name ?? ''}
      open={permissionOpen}
      onClose={() => setPermissionOpen(false)}
      onSaved={loadAgents}
    />
  </div>;
}
