import { useCallback, useEffect, useState } from 'react';
import { Alert, Button, Card, Form, Input, InputNumber, Modal, Popconfirm, Select, Space, Switch, Table, Tabs, Tag, message } from 'antd';
import { api } from '@/services/api';

type Row = Record<string, any>;
const roles = [
  { value: 'admin', label: '管理员' }, { value: 'developer', label: '开发者' },
  { value: 'operator', label: '操作员' }, { value: 'auditor', label: '审计员' }, { value: 'viewer', label: '查看者' },
];
const settingLabels: Record<string, string> = {
  monthly_token_limit: '每月 Token 配额', monthly_cost_limit: '每月成本预算',
  max_concurrent_runs: '最大并发运行数', requests_per_minute: '每分钟请求上限',
  storage_bytes_limit: '存储上限（字节）', hard_limit: '强制配额限制',
  retention_days: '数据保留天数', redact_pii: '个人信息脱敏',
  require_tool_approval: '工具调用审批', export_enabled: '允许导出',
  allowed_models: '允许的模型', blocked_terms: '屏蔽词',
  allowed_tool_patterns: '允许的工具规则', blocked_tool_patterns: '禁止的工具规则',
  network_allowlist: '网络访问白名单', organization: '所属组织',
};
const displaySetting = (value: unknown) => typeof value === 'boolean'
  ? value ? '已开启' : '已关闭'
  : typeof value === 'object' ? JSON.stringify(value) : String(value);
const json = (value: string, fallback: any) => value?.trim() ? JSON.parse(value) : fallback;

export default function OrganizationGovernancePanel({ organizationId, role }: { organizationId: string; role?: string }) {
  const [members, setMembers] = useState<Row[]>([]);
  const [quota, setQuota] = useState<Row>({});
  const [policy, setPolicy] = useState<Row>({});
  const [memberOpen, setMemberOpen] = useState(false);
  const [quotaMember, setQuotaMember] = useState<Row | null>(null);
  const [savingMemberQuota, setSavingMemberQuota] = useState(false);
  const [memberQuotaForm] = Form.useForm();
  const [quotaOpen, setQuotaOpen] = useState(false);
  const [policyOpen, setPolicyOpen] = useState(false);
  const [memberForm] = Form.useForm(); const [quotaForm] = Form.useForm(); const [policyForm] = Form.useForm();
  const canAdmin = role === 'owner' || role === 'admin';

  const load = useCallback(async () => {
    if (!organizationId) return;
    const [memberData, quotaData, policyData] = await Promise.all([
      api.get(`/enterprise/organizations/${organizationId}/members/`), api.get('/enterprise/quota/'), api.get('/enterprise/governance/'),
    ]);
    setMembers(memberData as Row[]); setQuota(quotaData as Row); setPolicy(policyData as Row);
  }, [organizationId]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => { setQuotaMember(null); }, [organizationId]);

  const openMemberQuota = (member: Row) => {
    memberQuotaForm.setFieldsValue({ monthly_token_limit: member.monthly_token_limit });
    setQuotaMember(member);
  };
  const saveMemberQuota = async () => {
    if (!quotaMember || savingMemberQuota) return;
    try {
      const values = await memberQuotaForm.validateFields();
      setSavingMemberQuota(true);
      await api.patch(`/enterprise/organizations/${organizationId}/members/${quotaMember.id}/`, {
        monthly_token_limit: values.monthly_token_limit ?? null,
      });
      message.success('成员 Token 配额已更新');
      setQuotaMember(null);
      await load();
    } catch (error: any) {
      if (!error?.errorFields) message.error('成员配额保存失败，请重试');
    } finally { setSavingMemberQuota(false); }
  };

  const saveMember = async () => { const values = await memberForm.validateFields(); await api.post(`/enterprise/organizations/${organizationId}/members/`, values); message.success('成员已添加'); setMemberOpen(false); await load(); };
  const updateRole = async (member: Row, nextRole: string) => { await api.patch(`/enterprise/organizations/${organizationId}/members/${member.id}/`, { role: nextRole }); message.success('角色已更新'); await load(); };
  const removeMember = async (member: Row) => { await api.delete(`/enterprise/organizations/${organizationId}/members/${member.id}/`); message.success('成员已停用'); await load(); };
  const openQuota = () => { quotaForm.setFieldsValue(quota); setQuotaOpen(true); };
  const saveQuota = async () => { const values = await quotaForm.validateFields(); await api.patch('/enterprise/quota/current/', values); message.success('配额已更新'); setQuotaOpen(false); await load(); };
  const openPolicy = () => { policyForm.setFieldsValue({ ...policy, allowed_models: JSON.stringify(policy.allowed_models || []), blocked_terms: JSON.stringify(policy.blocked_terms || []), allowed_tool_patterns: JSON.stringify(policy.allowed_tool_patterns || []), blocked_tool_patterns: JSON.stringify(policy.blocked_tool_patterns || []), network_allowlist: JSON.stringify(policy.network_allowlist || []) }); setPolicyOpen(true); };
  const savePolicy = async () => { try { const values = await policyForm.validateFields(); ['allowed_models', 'blocked_terms', 'allowed_tool_patterns', 'blocked_tool_patterns', 'network_allowlist'].forEach(key => { values[key] = json(values[key], []); }); await api.patch('/enterprise/governance/current/', values); message.success('治理策略已更新'); setPolicyOpen(false); await load(); } catch (error: any) { if (!error?.errorFields) message.error(error.message || 'JSON 格式不正确'); } };

  return <div className="enterprise-subpanel">
    {!canAdmin && <Alert type="info" showIcon message="只读访问" description="只有组织所有者或管理员可修改成员、配额和治理策略。" />}
    <Tabs items={[
      { key: 'members', label: '成员与角色', children: <Card extra={canAdmin && <Button type="primary" onClick={() => { memberForm.resetFields(); setMemberOpen(true); }}>添加成员</Button>}><Table rowKey="id" pagination={false} scroll={{ x: 920 }} dataSource={members} columns={[
        { title: '用户', render: (_, r: Row) => <div className="enterprise-member-identity"><strong>{r.username}</strong><span>{r.email || '未填写邮箱'}</span></div> },
        { title: '角色', width: 150, render: (_, r: Row) => r.role === 'owner' ? <Tag>所有者</Tag> : <Select aria-label={`${r.username}的组织角色`} style={{ width: 120 }} disabled={!canAdmin} value={r.role} options={roles} onChange={value => void updateRole(r, value)} /> },
        { title: '状态', width: 100, render: (_, r: Row) => <Tag color={r.is_active ? 'success' : 'default'}>{r.is_active ? '已启用' : '已停用'}</Tag> },
        { title: '本月已用 / Token 配额', width: 240, render: (_, r: Row) => <Space direction="vertical" size={4}>
          <span>{(r.monthly_tokens_used ?? 0).toLocaleString()} / {r.monthly_token_limit == null ? '不单独限制' : r.monthly_token_limit.toLocaleString()}</span>
          {r.monthly_token_limit != null && <Tag color={r.monthly_tokens_used >= r.monthly_token_limit ? 'error' : 'default'}>{r.monthly_tokens_used >= r.monthly_token_limit ? '配额已用尽' : `剩余 ${Math.max(0, r.monthly_token_limit - (r.monthly_tokens_used ?? 0)).toLocaleString()}`}</Tag>}
        </Space> },
        { title: '操作', render: (_, r: Row) => canAdmin ? <Space wrap>
          <Button size="small" onClick={() => openMemberQuota(r)}>设置配额</Button>
          {r.role !== 'owner' && <Popconfirm title="确认停用该成员？" onConfirm={() => removeMember(r)}><Button danger size="small">停用</Button></Popconfirm>}
        </Space> : '—' },
      ]} /></Card> },
      { key: 'quota', label: '配额与预算', children: <Card extra={canAdmin && <Button onClick={openQuota}>编辑配额</Button>}><div className="enterprise-policy-grid">{Object.entries(quota).filter(([key]) => !['id','created_at','updated_at'].includes(key)).map(([key, value]) => <div key={key}><span>{settingLabels[key] || key}</span><strong>{displaySetting(value)}</strong></div>)}</div></Card> },
      { key: 'policy', label: '治理策略', children: <Card extra={canAdmin && <Button onClick={openPolicy}>编辑策略</Button>}><div className="enterprise-policy-grid">{Object.entries(policy).filter(([key]) => !['id','created_at','updated_at'].includes(key)).map(([key, value]) => <div key={key}><span>{settingLabels[key] || key}</span><strong>{displaySetting(value)}</strong></div>)}</div></Card> },
    ]} />
    <Modal title="添加组织成员" open={memberOpen} onCancel={() => setMemberOpen(false)} onOk={saveMember}><Form layout="vertical" form={memberForm}><Form.Item name="user_id" label="用户 ID" rules={[{ required: true }]}><InputNumber style={{ width: '100%' }} /></Form.Item><Form.Item name="role" label="角色" initialValue="viewer"><Select options={roles} /></Form.Item><Form.Item name="monthly_token_limit" label="每月 Token 配额" extra="留空表示不单独限制，0 表示禁止新增执行。"><InputNumber min={0} max={Number.MAX_SAFE_INTEGER} precision={0} style={{ width: '100%' }} /></Form.Item></Form></Modal>
    <Modal title={`${quotaMember?.username ?? ''} · Token 配额`} open={!!quotaMember} confirmLoading={savingMemberQuota} onCancel={() => { if (!savingMemberQuota) setQuotaMember(null); }} onOk={saveMemberQuota} okText="保存" cancelText="取消">
      <Form layout="vertical" form={memberQuotaForm}>
        <Form.Item name="monthly_token_limit" label="每月 Token 配额" extra="留空表示不单独限制；0 表示禁止新增执行。" rules={[{ type: 'integer', min: 0, max: Number.MAX_SAFE_INTEGER, message: '请输入非负整数' }]}>
          <InputNumber min={0} max={Number.MAX_SAFE_INTEGER} precision={0} placeholder="不单独限制" style={{ width: '100%' }} />
        </Form.Item>
        <Alert type="info" showIcon message={`本月已用 ${(quotaMember?.monthly_tokens_used ?? 0).toLocaleString()} tokens`} description="按服务器时区的自然月统计，每月自动重新计算。成员配额独立生效，同时受组织总配额约束。达到配额后阻止新增执行，已开始的请求可能使最终用量超过配额。" />
      </Form>
    </Modal>
    <Modal title="编辑配额" open={quotaOpen} onCancel={() => setQuotaOpen(false)} onOk={saveQuota}><Form layout="vertical" form={quotaForm}><Form.Item name="monthly_token_limit" label="每月 Token"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item><Form.Item name="monthly_cost_limit" label="每月成本预算"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item><Form.Item name="max_concurrent_runs" label="最大并发运行"><InputNumber min={1} style={{ width: '100%' }} /></Form.Item><Form.Item name="requests_per_minute" label="每分钟请求"><InputNumber min={1} style={{ width: '100%' }} /></Form.Item><Form.Item name="storage_bytes_limit" label="存储字节"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item><Form.Item name="hard_limit" label="硬限制" valuePropName="checked"><Switch /></Form.Item></Form></Modal>
    <Modal title="编辑治理策略" open={policyOpen} onCancel={() => setPolicyOpen(false)} onOk={savePolicy} width={760}><Form layout="vertical" form={policyForm}><Space align="start"><Form.Item name="retention_days" label="数据保留天数"><InputNumber min={1} /></Form.Item><Form.Item name="redact_pii" label="PII 脱敏" valuePropName="checked"><Switch /></Form.Item><Form.Item name="require_tool_approval" label="工具审批" valuePropName="checked"><Switch /></Form.Item><Form.Item name="export_enabled" label="允许导出" valuePropName="checked"><Switch /></Form.Item></Space>{['allowed_models','blocked_terms','allowed_tool_patterns','blocked_tool_patterns','network_allowlist'].map(key => <Form.Item key={key} name={key} label={`${key}（JSON 数组）`}><Input.TextArea rows={2} /></Form.Item>)}</Form></Modal>
  </div>;
}
