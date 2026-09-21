import { useCallback, useEffect, useState, type ReactNode } from 'react';
import {
  Alert, Button, Card, Descriptions, Drawer, Empty, Form, Input, InputNumber,
  Modal, Popconfirm, Select, Space, Statistic, Switch, Table, Tag,
  Typography, message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  ApartmentOutlined, AppstoreOutlined, AuditOutlined, BankOutlined, CloudServerOutlined,
  DashboardOutlined, ExperimentOutlined, KeyOutlined, LinkOutlined, PlusOutlined,
  ReloadOutlined, RobotOutlined, SafetyCertificateOutlined, ThunderboltOutlined,
  WalletOutlined, PieChartOutlined, BarChartOutlined,
} from '@ant-design/icons';
import { api } from '@/services/api';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import AgentLifecyclePanel from './AgentLifecyclePanel';
import ApplicationManagementPanel from './ApplicationManagementPanel';
import OrganizationGovernancePanel from './OrganizationGovernancePanel';
import { useAuthStore } from '@/stores/useAuthStore';
import './EnterprisePage.css';

type Row = Record<string, any>;
type Field = { name: string; label: string; kind?: 'text' | 'textarea' | 'number' | 'select' | 'switch' | 'json'; required?: boolean; options?: Array<{ value: string; label?: string }>; initialValue?: any };

const normalize = (value: any): Row[] => Array.isArray(value) ? value : value?.results ?? [];
const organizationRoleLevel: Record<string, number> = {
  viewer: 10, auditor: 20, operator: 30, developer: 40, admin: 50, owner: 60,
};
const parseJson = (value: any, fallback: any) => {
  if (value === undefined || value === null || value === '') return fallback;
  if (typeof value !== 'string') return value;
  try { return JSON.parse(value); } catch { throw new Error('JSON 配置格式不正确'); }
};

const sections: Record<string, { title: string; endpoint: string; fields?: Field[]; readOnly?: boolean }> = {
  organization: { title: '组织治理', endpoint: '' },
  applications: { title: '应用管理', endpoint: '' },
  lifecycle: { title: '智能体管理', endpoint: '' },
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

const sectionPresentation: Record<string, { icon: ReactNode; description: string }> = {
  organization: { icon: <ApartmentOutlined />, description: '管理组织成员、资源配额与治理策略。' },
  applications: { icon: <AppstoreOutlined />, description: '维护应用可用性、可见范围与成员访问权限。' },
  lifecycle: { icon: <RobotOutlined />, description: '管理智能体权限、版本发布与部署状态。' },
  traces: { icon: <DashboardOutlined />, description: '查看资源运行状态，追踪执行过程与异常。' },
  evaluations: { icon: <ExperimentOutlined />, description: '维护评测用例与质量门禁，检查输出表现。' },
  audit: { icon: <AuditOutlined />, description: '回溯组织内的操作记录与执行结果。' },
  providers: { icon: <CloudServerOutlined />, description: '配置模型服务、可用模型与路由权重。' },
  secrets: { icon: <KeyOutlined />, description: '统一管理外部服务所需的密钥引用。' },
  connectors: { icon: <LinkOutlined />, description: '连接外部系统，管理接口配置与调用测试。' },
  automations: { icon: <ThunderboltOutlined />, description: '维护触发规则，让业务按计划或事件运行。' },
  identity: { icon: <SafetyCertificateOutlined />, description: '配置组织身份提供商与单点登录。' },
};
const navigationGroups = [
  { title: '组织与资源', keys: ['organization', 'applications', 'lifecycle'] },
  { title: '运行与质量', keys: ['traces', 'evaluations', 'audit'] },
  { title: '模型与集成', keys: ['providers', 'secrets', 'connectors', 'automations', 'identity'] },
];
const roleLabels: Record<string, string> = {
  owner: '所有者', admin: '管理员', developer: '开发者', operator: '操作员', auditor: '审计员', viewer: '查看者',
};
const runStatusLabels: Record<string, string> = {
  pending: '等待执行', queued: '排队中', running: '运行中', succeeded: '已完成',
  failed: '失败', cancelled: '已取消', blocked: '受阻', waiting: '等待中',
};
const displayTime = (value?: string) => {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false });
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
  const isPlatformAuditor = useAuthStore((state) => state.user?.role === 'auditor');
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
  const currentOrg = organizations.find(o => o.id === currentOrganizationId);
  const currentRoleLevel = organizationRoleLevel[currentOrg?.role ?? ''] ?? 0;
  const minimumWriteLevel = ['secrets', 'identity'].includes(active) ? 50 : 40;
  const canWriteSection = currentRoleLevel >= minimumWriteLevel;

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
      { title: '类型', dataIndex: 'kind' }, { title: '资源', dataIndex: 'resource_id' }, { title: '状态', dataIndex: 'status', render: v => <Tag color={v === 'succeeded' ? 'success' : v === 'failed' ? 'error' : v === 'running' ? 'processing' : 'default'}>{runStatusLabels[v] || v}</Tag> }, { title: '时间', dataIndex: 'created_at', render: displayTime },
    ] : active === 'audit' ? [
      { title: '操作', dataIndex: 'action' }, { title: '操作者', dataIndex: 'actor_username' }, { title: '状态', render: (_, r) => r.metadata?.status_code }, { title: '时间', dataIndex: 'created_at', render: displayTime },
    ] : [
      { title: '名称', dataIndex: 'name', render: v => <strong>{v}</strong> },
      { title: '类型 / 状态', render: (_, r) => r.provider_type || r.connector_type || r.protocol || r.trigger_type || r.target_type || r.status || '—' },
      { title: '启用', dataIndex: 'is_active', render: v => v === undefined ? '—' : <Tag color={v ? 'green' : 'default'}>{v ? '启用' : '停用'}</Tag> },
      { title: '更新时间', dataIndex: 'updated_at', render: displayTime },
    ];
    base.push({ title: '操作', fixed: 'right', width: 210, render: (_, row) => <Space wrap>
      <Button size="small" onClick={() => setDetail(row)}>详情</Button>
      {!section.readOnly && canWriteSection && <Button size="small" onClick={() => openEdit(row)}>编辑</Button>}
      {active === 'connectors' && canWriteSection && <Button size="small" onClick={() => invoke(row)}>测试</Button>}
      {active === 'automations' && canWriteSection && <Button size="small" onClick={() => trigger(row)}>触发</Button>}
      {active === 'evaluations' && canWriteSection && <Button size="small" onClick={() => manageEvaluation(row)}>用例</Button>}
      {!section.readOnly && canWriteSection && <Popconfirm title="确认删除该资源？" onConfirm={() => remove(row)}><Button danger size="small">删除</Button></Popconfirm>}
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

  return <div className="enterprise-page">
    <header className="enterprise-hero">
      <div>
        <span className="enterprise-eyebrow"><BankOutlined aria-hidden="true" />管理控制台</span>
        <h1 className="page-title">系统管理</h1>
        <p className="page-subtitle">集中管理组织资源，掌握运行情况与服务配置。</p>
      </div>
      <div className="enterprise-organization">
        <span>当前组织</span>
        {singleTenantMode ? <strong><ApartmentOutlined aria-hidden="true" />{currentOrg?.name || '暂无组织'}</strong> : <Select aria-label="切换管理组织" value={currentOrganizationId} onChange={selectOrganization} options={organizations.map(o => ({ value: o.id, label: `${o.name} · ${roleLabels[o.role] || o.role}` }))} />}
        <small>{singleTenantMode ? '单组织工作区' : '多组织工作区'}{currentOrg?.role ? ` · ${roleLabels[currentOrg.role] || currentOrg.role}` : ''}</small>
      </div>
    </header>
    {!currentOrganizationId && <Alert type="warning" showIcon message="暂无可用组织" description={singleTenantMode ? '默认组织尚未完成初始化。' : '当前账号尚未加入任何组织。'} />}
    <div className="enterprise-grid" aria-label="组织用量概览" aria-busy={loading}>
      {[
        { key: 'tokens', label: '本月 Tokens', hint: '当前组织累计使用量', icon: <BarChartOutlined /> },
        { key: 'monthly_token_limit', label: 'Token 配额', hint: '每月可用 Token 上限', icon: <PieChartOutlined /> },
        { key: 'cost', label: '本月成本', hint: '当前组织累计模型成本', icon: <WalletOutlined />, currency: true },
        { key: 'monthly_cost_limit', label: '成本预算', hint: '组织每月成本预算', icon: <SafetyCertificateOutlined />, currency: true },
      ].map(metric => <Card key={metric.key} className="enterprise-stat-card">
        <div className="enterprise-stat-label"><span>{metric.label}</span><span aria-hidden="true">{metric.icon}</span></div>
        <Statistic value={loading || !currentOrganizationId || usage[metric.key] === undefined ? '—' : Number(usage[metric.key] || 0)} prefix={metric.currency ? '¥' : undefined} precision={metric.key === 'cost' ? 4 : undefined} />
        <p>{metric.hint}</p>
      </Card>)}
    </div>
    <div className="enterprise-workspace">
      <nav className="enterprise-navigation" aria-label="系统管理分组">
        {navigationGroups.map(group => <div className="enterprise-navigation-group" key={group.title}>
          <h2>{group.title}</h2>
          {group.keys.filter(key => (key !== 'audit' || currentRoleLevel >= 20) && (!isPlatformAuditor || !['applications', 'lifecycle'].includes(key))).map(key => <button
            key={key} type="button" className={active === key ? 'active' : ''}
            aria-pressed={active === key} aria-controls="enterprise-section" onClick={() => setActive(key)}
          ><span aria-hidden="true">{sectionPresentation[key].icon}</span>{sections[key].title}</button>)}
        </div>)}
      </nav>
      <section className="enterprise-table-card" id="enterprise-section" aria-labelledby="enterprise-section-title">
        <div className="enterprise-section-heading">
          <span className="enterprise-section-icon" aria-hidden="true">{sectionPresentation[active].icon}</span>
          <div><h2 id="enterprise-section-title">{section.title}</h2><p>{sectionPresentation[active].description}</p></div>
          {section.readOnly && <Tag bordered={false}>只读记录</Tag>}
        </div>
      {active === 'organization' && currentOrganizationId ? <OrganizationGovernancePanel organizationId={currentOrganizationId} role={currentOrg?.role} /> : active === 'applications' && currentOrganizationId ? <ApplicationManagementPanel organizationId={currentOrganizationId} /> : active === 'lifecycle' ? <AgentLifecyclePanel /> : <>
        <div className="enterprise-toolbar"><Typography.Text type="secondary">{loading ? '正在加载记录…' : `当前列表 ${rows.length} 条记录`}</Typography.Text><Space wrap><Button icon={<ReloadOutlined />} loading={loading} onClick={() => void reload()}>刷新</Button>{section.fields && canWriteSection && <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建{section.title}</Button>}</Space></div>
        <Table rowKey="id" loading={loading} columns={columns} dataSource={rows} scroll={{ x: 900 }} locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={`暂无${section.title}记录`} /> }} />
      </>}
      </section>
    </div>
    <Modal className="enterprise-resource-modal" title={editing ? `编辑${section.title}` : `新建${section.title}`} open={modalOpen} onCancel={() => setModalOpen(false)} onOk={submit} width={680}><Form layout="vertical" form={form}>{section.fields?.map(field => <DynamicField key={field.name} field={field} />)}</Form></Modal>
    <Drawer className="enterprise-resource-drawer" title="资源详情" open={Boolean(detail)} onClose={() => setDetail(null)} width={620}>{detail && <Descriptions column={1} bordered size="small" items={Object.entries(detail).map(([key, value]) => ({ key, label: key, children: typeof value === 'object' ? <pre>{JSON.stringify(value, null, 2)}</pre> : String(value ?? '—') }))} />}</Drawer>
  </div>;
}
