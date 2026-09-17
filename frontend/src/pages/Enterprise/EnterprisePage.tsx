import { useCallback, useEffect, useState } from 'react';
import {
  Alert, Button, Card, Descriptions, Drawer, Empty, Form, Input, InputNumber,
  Modal, Popconfirm, Select, Space, Statistic, Switch, Table, Tabs, Tag,
  Typography, message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { api } from '@/services/api';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import AgentLifecyclePanel from './AgentLifecyclePanel';
import ApplicationManagementPanel from './ApplicationManagementPanel';
import OrganizationGovernancePanel from './OrganizationGovernancePanel';
import './EnterprisePage.css';

type Row = Record<string, any>;
type Field = { name: string; label: string; kind?: 'text' | 'textarea' | 'number' | 'select' | 'switch' | 'json'; required?: boolean; options?: Array<{ value: string; label?: string }>; initialValue?: any };

const normalize = (value: any): Row[] => Array.isArray(value) ? value : value?.results ?? [];
const parseJson = (value: any, fallback: any) => {
  if (value === undefined || value === null || value === '') return fallback;
  if (typeof value !== 'string') return value;
  try { return JSON.parse(value); } catch { throw new Error('JSON 配置格式不正确'); }
};

const sections: Record<string, { title: string; endpoint: string; fields?: Field[]; readOnly?: boolean }> = {
  organization: { title: '组织治理', endpoint: '' },
  applications: { title: '应用管理', endpoint: '' },
  lifecycle: { title: '智能体发布', endpoint: '' },
  traces: { title: '运行追踪', endpoint: '/enterprise/traces/', readOnly: true },
  providers: { title: '模型供应商', endpoint: '/enterprise/providers/', fields: [
    { name: 'name', label: '名称', required: true }, { name: 'base_url', label: 'Base URL', required: true },
    { name: 'provider_type', label: '类型', initialValue: 'openai_compatible' }, { name: 'secret_ref', label: '密钥引用' },
    { name: 'available_models', label: '模型列表（JSON）', kind: 'json', initialValue: '[]' }, { name: 'routing_weight', label: '路由权重', kind: 'number', initialValue: 100 },
  ] },
  secrets: { title: '密钥引用', endpoint: '/enterprise/secrets/', fields: [
    { name: 'name', label: '名称', required: true }, { name: 'backend', label: '后端', kind: 'select', initialValue: 'environment', options: [{ value: 'environment', label: '环境变量' }] },
    { name: 'reference', label: '引用名称', required: true }, { name: 'description', label: '说明', kind: 'textarea' },
  ] },
  evaluations: { title: '评测', endpoint: '/enterprise/evaluations/', fields: [
    { name: 'name', label: '名称', required: true }, { name: 'target_type', label: '目标类型', kind: 'select', initialValue: 'agent', options: [{ value: 'agent' }, { value: 'application' }] },
    { name: 'target_id', label: '目标 ID' }, { name: 'evaluators', label: '评测器（JSON）', kind: 'json', initialValue: '[{"type":"exact"}]' },
    { name: 'quality_gate', label: '质量门禁（JSON）', kind: 'json', initialValue: '{"minimum_score":1}' },
  ] },
  connectors: { title: '连接器', endpoint: '/enterprise/connectors/', fields: [
    { name: 'name', label: '名称', required: true }, { name: 'connector_type', label: '类型', initialValue: 'webhook', required: true },
    { name: 'endpoint', label: 'Endpoint', required: true }, { name: 'secret_ref', label: '密钥引用' },
    { name: 'config', label: '配置（JSON）', kind: 'json', initialValue: '{"method":"POST","timeout":10}' },
  ] },
  automations: { title: '自动化', endpoint: '/enterprise/automations/', fields: [
    { name: 'name', label: '名称', required: true }, { name: 'trigger_type', label: '触发类型', kind: 'select', initialValue: 'webhook', options: [{ value: 'webhook' }, { value: 'schedule' }, { value: 'event' }] },
    { name: 'target_type', label: '目标类型', kind: 'select', initialValue: 'agent', options: [{ value: 'agent' }, { value: 'application' }, { value: 'workflow' }] }, { name: 'target_id', label: '目标 ID', required: true },
    { name: 'schedule', label: 'Cron（计划任务）' }, { name: 'event_name', label: '事件名称' }, { name: 'input_mapping', label: '输入映射（JSON）', kind: 'json', initialValue: '{}' },
  ] },
  identity: { title: '身份提供商', endpoint: '/enterprise/identity-providers/', fields: [
    { name: 'name', label: '名称', required: true }, { name: 'protocol', label: '协议', kind: 'select', initialValue: 'oidc', options: [{ value: 'oidc', label: 'OpenID Connect' }, { value: 'saml', label: 'SAML 2.0' }] },
    { name: 'issuer', label: 'Issuer', required: true }, { name: 'client_id', label: 'Client ID' }, { name: 'secret_ref', label: '密钥引用' },
    { name: 'metadata_url', label: 'Metadata URL' }, { name: 'domains', label: '组织域名（JSON）', kind: 'json', initialValue: '[]' }, { name: 'enforce_sso', label: '强制 SSO', kind: 'switch' },
  ] },
  audit: { title: '审计日志', endpoint: '/enterprise/audit-logs/', readOnly: true },
};

function DynamicField({ field }: { field: Field }) {
  const rules = field.required ? [{ required: true, message: `请输入${field.label}` }] : undefined;
  if (field.kind === 'textarea' || field.kind === 'json') return <Form.Item name={field.name} label={field.label} rules={rules} initialValue={field.initialValue}><Input.TextArea rows={field.kind === 'json' ? 4 : 3} /></Form.Item>;
  if (field.kind === 'number') return <Form.Item name={field.name} label={field.label} rules={rules} initialValue={field.initialValue}><InputNumber style={{ width: '100%' }} min={0} /></Form.Item>;
  if (field.kind === 'select') return <Form.Item name={field.name} label={field.label} rules={rules} initialValue={field.initialValue}><Select options={field.options?.map(o => ({ ...o, label: o.label || o.value }))} /></Form.Item>;
  if (field.kind === 'switch') return <Form.Item name={field.name} label={field.label} valuePropName="checked" initialValue={false}><Switch /></Form.Item>;
  return <Form.Item name={field.name} label={field.label} rules={rules} initialValue={field.initialValue}><Input /></Form.Item>;
}

export default function EnterprisePage() {
  const {
    organizations, currentOrganizationId, singleTenantMode,
    loadOrganizations, selectOrganization,
  } = useOrganizationStore();
  const [active, setActive] = useState('traces');
  const [rows, setRows] = useState<Row[]>([]);
  const [usage, setUsage] = useState<Row>({});
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Row | null>(null);
  const [detail, setDetail] = useState<Row | null>(null);
  const [form] = Form.useForm();
  const section = sections[active];

  const reload = useCallback(async () => {
    if (!currentOrganizationId) return;
    if (!section.endpoint) { setRows([]); return; }
    setLoading(true);
    try {
      const [data, summary] = await Promise.all([api.get(section.endpoint), api.get('/enterprise/usage/summary/')]);
      setRows(normalize(data)); setUsage(summary as Row);
    } finally { setLoading(false); }
  }, [currentOrganizationId, section.endpoint]);

  useEffect(() => { void loadOrganizations(); }, [loadOrganizations]);
  useEffect(() => { void reload(); }, [reload]);

  const columns: ColumnsType<Row> = (() => {
    const base: ColumnsType<Row> = active === 'traces' ? [
      { title: '类型', dataIndex: 'kind' }, { title: '资源', dataIndex: 'resource_id' }, { title: '状态', dataIndex: 'status', render: v => <Tag>{v}</Tag> }, { title: '时间', dataIndex: 'created_at' },
    ] : active === 'audit' ? [
      { title: '操作', dataIndex: 'action' }, { title: '操作者', dataIndex: 'actor_username' }, { title: '状态', render: (_, r) => r.metadata?.status_code }, { title: '时间', dataIndex: 'created_at' },
    ] : [
      { title: '名称', dataIndex: 'name', render: v => <strong>{v}</strong> },
      { title: '类型 / 状态', render: (_, r) => r.provider_type || r.connector_type || r.protocol || r.trigger_type || r.target_type || r.status || '—' },
      { title: '启用', dataIndex: 'is_active', render: v => v === undefined ? '—' : <Tag color={v ? 'green' : 'default'}>{v ? '启用' : '停用'}</Tag> },
      { title: '更新时间', dataIndex: 'updated_at' },
    ];
    base.push({ title: '操作', fixed: 'right', width: 210, render: (_, row) => <Space wrap>
      <Button size="small" onClick={() => setDetail(row)}>详情</Button>
      {!section.readOnly && <Button size="small" onClick={() => openEdit(row)}>编辑</Button>}
      {active === 'connectors' && <Button size="small" onClick={() => invoke(row)}>测试</Button>}
      {active === 'automations' && <Button size="small" onClick={() => trigger(row)}>触发</Button>}
      {active === 'evaluations' && <Button size="small" onClick={() => manageEvaluation(row)}>用例</Button>}
      {!section.readOnly && <Popconfirm title="确认删除该资源？" onConfirm={() => remove(row)}><Button danger size="small">删除</Button></Popconfirm>}
    </Space> });
    return base;
  })();

  const openCreate = () => { setEditing(null); form.resetFields(); setModalOpen(true); };
  const openEdit = (row: Row) => {
    setEditing(row); form.resetFields();
    const values = { ...row };
    section.fields?.filter(f => f.kind === 'json').forEach(f => { values[f.name] = JSON.stringify(row[f.name] ?? (f.initialValue || {}), null, 2); });
    form.setFieldsValue(values); setModalOpen(true);
  };
  const submit = async () => {
    try {
      const values = await form.validateFields();
      section.fields?.filter(f => f.kind === 'json').forEach(f => { values[f.name] = parseJson(values[f.name], f.initialValue?.startsWith('[') ? [] : {}); });
      if (editing) await api.patch(`${section.endpoint}${editing.id}/`, values); else await api.post(section.endpoint, values);
      message.success(editing ? '更新成功' : '创建成功'); setModalOpen(false); await reload();
    } catch (error: any) { if (error?.errorFields) return; message.error(error.message || '保存失败'); }
  };
  const remove = async (row: Row) => { await api.delete(`${section.endpoint}${row.id}/`); message.success('已删除'); await reload(); };
  const invoke = async (row: Row) => { const result = await api.post(`${section.endpoint}${row.id}/invoke/`, { ping: new Date().toISOString() }); Modal.info({ title: '连接器响应', width: 720, content: <pre>{JSON.stringify(result, null, 2)}</pre> }); };
  const trigger = async (row: Row) => { const result = await api.post<{ id: string }>(`${section.endpoint}${row.id}/trigger/`, {}); message.success(`已触发，Trace: ${result.id}`); };

  const manageEvaluation = async (row: Row) => {
    const cases = await api.get<Row[]>(`${section.endpoint}${row.id}/cases/`);
    let name = ''; let input = '{}'; let expected = '{"value":""}';
    Modal.confirm({ title: `${row.name} · 评测用例`, width: 860, okText: '新增用例', cancelText: '关闭', content: <div className="enterprise-dialog-stack">
      <Alert type="info" showIcon message={`已有 ${cases.length} 个用例`} description={cases.map(c => c.name).join('、') || '暂无用例'} />
      <Input placeholder="用例名称" onChange={e => { name = e.target.value; }} /><Input.TextArea rows={3} defaultValue={input} onChange={e => { input = e.target.value; }} /><Input.TextArea rows={3} defaultValue={expected} onChange={e => { expected = e.target.value; }} />
      <Button onClick={async () => { const result = await api.post(`${section.endpoint}${row.id}/run/`, { outputs: {} }); Modal.info({ title: '评测结果', content: <pre>{JSON.stringify(result, null, 2)}</pre> }); }}>立即运行</Button>
    </div>, onOk: async () => { if (!name) return; await api.post(`${section.endpoint}${row.id}/cases/`, { name, input: parseJson(input, {}), expected: parseJson(expected, {}) }); message.success('用例已创建'); } });
  };

  const currentOrg = organizations.find(o => o.id === currentOrganizationId);
  return <div className="enterprise-page animate-fade-in">
    <div className="enterprise-hero"><div><h1 className="page-title">控制台</h1><p className="page-subtitle">{singleTenantMode ? '组织治理、运行观测、知识评测与系统集成' : '多组织治理、运行观测、知识评测与系统集成'}</p></div>{singleTenantMode ? <Tag color="blue">{currentOrg?.name || '当前组织'}</Tag> : <Select style={{ width: 280 }} value={currentOrganizationId} onChange={selectOrganization} options={organizations.map(o => ({ value: o.id, label: `${o.name} · ${o.role}` }))} />}</div>
    {!currentOrganizationId && <Alert type="warning" showIcon message="暂无可用组织" description={singleTenantMode ? '默认组织尚未完成初始化。' : '当前账号尚未加入任何组织。'} />}
    <div className="enterprise-grid"><Card><Statistic title="本月 Tokens" value={Number(usage.tokens || 0)} /></Card><Card><Statistic title="Token 配额" value={Number(usage.monthly_token_limit || 0)} /></Card><Card><Statistic title="本月成本" prefix="¥" value={Number(usage.cost || 0)} precision={4} /></Card><Card><Statistic title="成本预算" prefix="¥" value={Number(usage.monthly_cost_limit || 0)} /></Card></div>
    <div className="enterprise-table-card">
      <Tabs activeKey={active} onChange={setActive} items={Object.entries(sections).map(([key, value]) => ({ key, label: value.title }))} />
      {active === 'organization' && currentOrganizationId ? <OrganizationGovernancePanel organizationId={currentOrganizationId} role={currentOrg?.role} /> : active === 'applications' && currentOrganizationId ? <ApplicationManagementPanel organizationId={currentOrganizationId} role={currentOrg?.role} /> : active === 'lifecycle' ? <AgentLifecyclePanel /> : <>
        <div className="enterprise-toolbar"><Typography.Text type="secondary">当前组织：{currentOrg?.name || '—'}</Typography.Text><Space><Button onClick={() => void reload()}>刷新</Button>{section.fields && <Button type="primary" onClick={openCreate}>新建</Button>}</Space></div>
        <Table rowKey="id" loading={loading} columns={columns} dataSource={rows} scroll={{ x: 900 }} locale={{ emptyText: <Empty description="暂无数据" /> }} />
      </>}
    </div>
    <Modal title={editing ? `编辑${section.title}` : `新建${section.title}`} open={modalOpen} onCancel={() => setModalOpen(false)} onOk={submit} width={680}><Form layout="vertical" form={form}>{section.fields?.map(field => <DynamicField key={field.name} field={field} />)}</Form></Modal>
    <Drawer title="资源详情" open={Boolean(detail)} onClose={() => setDetail(null)} width={620}>{detail && <Descriptions column={1} bordered size="small" items={Object.entries(detail).map(([key, value]) => ({ key, label: key, children: typeof value === 'object' ? <pre>{JSON.stringify(value, null, 2)}</pre> : String(value ?? '—') }))} />}</Drawer>
  </div>;
}
