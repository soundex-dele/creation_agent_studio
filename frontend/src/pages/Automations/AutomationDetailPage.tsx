import { useCallback, useEffect, useState } from 'react';
import { Alert, Button, Card, Descriptions, Modal, Popconfirm, Space, Table, Tag, Typography, message } from 'antd';
import { useNavigate, useParams } from 'react-router-dom';
import { automationApi } from '@/services/automations';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import type { Automation, AutomationInvocation } from '@/types/automation';
import './Automations.css';

const roleLevel: Record<string, number> = { viewer: 10, auditor: 20, operator: 30, developer: 40, admin: 50, owner: 60 };

export default function AutomationDetailPage() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const automationId = Number(id);
  const { currentOrganizationId, organizations, loadOrganizations } = useOrganizationStore();
  const [automation, setAutomation] = useState<Automation>();
  const [invocations, setInvocations] = useState<AutomationInvocation[]>([]);
  const currentRole = organizations.find(item => item.id === currentOrganizationId)?.role || 'viewer';
  const canOperate = roleLevel[currentRole] >= 30;
  const canEdit = roleLevel[currentRole] >= 40;
  const canAdmin = roleLevel[currentRole] >= 50;

  const load = useCallback(async () => {
    if (!currentOrganizationId || !automationId) return;
    const [detail, history] = await Promise.all([
      automationApi.get(currentOrganizationId, automationId),
      automationApi.invocations(currentOrganizationId, automationId),
    ]);
    setAutomation(detail); setInvocations(history);
  }, [currentOrganizationId, automationId]);
  useEffect(() => { void loadOrganizations(); }, [loadOrganizations]);
  useEffect(() => { void load(); }, [load]);

  const action = async (name: string) => {
    if (!currentOrganizationId) return;
    const result = await automationApi.action(currentOrganizationId, automationId, name);
    if (name === 'rotate-secret' && 'webhook_secret' in result && result.webhook_secret) {
      Modal.info({ title: '新密钥只显示这一次', content: <Typography.Text copyable code>{result.webhook_secret}</Typography.Text> });
    } else message.success('操作成功');
    await load();
  };
  const archive = async () => {
    if (!currentOrganizationId) return;
    await automationApi.archive(currentOrganizationId, automationId);
    message.success('自动化已归档'); navigate('/automations');
  };

  if (!automation) return <div className="automation-detail">正在加载…</div>;
  return <div className="automation-detail animate-fade-in">
    <div className="automations-hero"><div><Space><Typography.Title level={2}>{automation.name}</Typography.Title><Tag>{automation.status}</Tag></Space><Typography.Text type="secondary">{automation.description || '暂无描述'}</Typography.Text></div><Space><Button onClick={() => navigate('/automations')}>返回</Button>{canEdit && <Button onClick={() => navigate(`/automations/${automation.id}/edit`)}>编辑</Button>}</Space></div>
    {automation.blocked_reason && <Alert type="error" showIcon message="自动化已阻塞" description={automation.blocked_reason} />}
    <div className="automation-actions"><Space wrap>{canOperate && <Button type="primary" onClick={() => void action('run')}>立即运行</Button>}{canOperate && <Button onClick={() => void action(automation.status === 'active' ? 'disable' : 'enable')}>{automation.status === 'active' ? '暂停' : '启用'}</Button>}{canAdmin && automation.trigger_type === 'webhook' && <Button onClick={() => void action('rotate-secret')}>轮换密钥</Button>}{canAdmin && <Button onClick={() => void action('take-over')}>接管</Button>}{canAdmin && <Popconfirm title="确认归档这个自动化？" onConfirm={() => void archive()}><Button danger>归档</Button></Popconfirm>}</Space></div>
    <Card title="配置"><Descriptions bordered column={2} items={[
      { key: 'trigger', label: '触发方式', children: automation.trigger_type === 'schedule' ? '定时' : 'Webhook' },
      { key: 'target', label: '执行目标', children: `${automation.target_type === 'application' ? '应用' : '工作流'} · ${automation.target_name}` },
      { key: 'owner', label: '运行身份', children: automation.created_by_username },
      { key: 'next', label: '下次执行', children: automation.next_run_at ? new Date(automation.next_run_at).toLocaleString() : '—' },
      { key: 'schedule', label: '计划', children: automation.trigger_type === 'schedule' ? (automation.schedule_kind === 'once' ? automation.run_at : `${automation.schedule} · ${automation.timezone}`) : '—' },
      { key: 'webhook', label: 'Webhook URL', children: automation.webhook_url ? <Typography.Text copyable code>{window.location.origin}{automation.webhook_url}</Typography.Text> : '—' },
      { key: 'input', label: '默认参数', span: 2, children: <pre>{JSON.stringify(automation.default_input, null, 2)}</pre> },
    ]} /></Card>
    <Card title="运行记录"><Table rowKey="id" dataSource={invocations} columns={[
      { title: '触发时间', dataIndex: 'created_at', render: value => new Date(value).toLocaleString() },
      { title: '来源', dataIndex: 'source' },
      { title: '状态', dataIndex: 'status', render: value => <Tag>{value}</Tag> },
      { title: '错误', dataIndex: 'error', render: value => value || '—' },
      { title: 'Run', dataIndex: 'run_id', render: value => value ? <Button type="link" onClick={() => navigate(`/runs/${value}`)}>查看运行</Button> : '—' },
    ]} /></Card>
  </div>;
}
