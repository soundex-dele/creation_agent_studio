import { useCallback, useEffect, useState } from 'react';
import { Button, Empty, Input, Select, Space, Table, Tag, message } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { ClockCircleOutlined, LinkOutlined, PlusOutlined, ReloadOutlined, ThunderboltOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { automationApi } from '@/services/automations';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import type { Automation } from '@/types/automation';
import WorkspaceHeader from '@/components/Workspace/WorkspaceHeader';
import './Automations.css';

const statusColors: Record<string, string> = {
  active: 'green', paused: 'default', blocked: 'red', draft: 'blue', archived: 'default',
};
const statusLabels: Record<string, string> = {
  active: '已启用', paused: '已暂停', blocked: '需处理', draft: '草稿', archived: '已归档',
};
const resultLabels: Record<string, string> = {
  pending: '等待执行', queued: '排队中', running: '执行中', succeeded: '已完成',
  failed: '失败', cancelled: '已取消', skipped: '已跳过', blocked: '需处理',
};

export default function AutomationsPage() {
  const navigate = useNavigate();
  const { currentOrganizationId, organizations, loadOrganizations } = useOrganizationStore();
  const [rows, setRows] = useState<Automation[]>([]);
  const [loading, setLoading] = useState(false);
  const [query, setQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>();
  const [triggerFilter, setTriggerFilter] = useState<string>();
  const currentRole = organizations.find(item => item.id === currentOrganizationId)?.role || 'viewer';
  const canOperate = ['operator', 'developer', 'admin', 'owner'].includes(currentRole);
  const canCreate = ['developer', 'admin', 'owner'].includes(currentRole);

  const load = useCallback(async () => {
    if (!currentOrganizationId) return;
    setLoading(true);
    try {
      setRows(await automationApi.list(currentOrganizationId, {
        ...(statusFilter ? { status: statusFilter } : {}),
        ...(triggerFilter ? { trigger_type: triggerFilter } : {}),
      }));
    } finally {
      setLoading(false);
    }
  }, [currentOrganizationId, statusFilter, triggerFilter]);

  useEffect(() => { void loadOrganizations(); }, [loadOrganizations]);
  useEffect(() => { void load(); }, [load]);

  const toggle = async (row: Automation) => {
    if (!currentOrganizationId) return;
    const action = row.status === 'active' ? 'disable' : 'enable';
    await automationApi.action(currentOrganizationId, row.id, action);
    message.success(action === 'enable' ? '自动化已启用' : '自动化已暂停');
    await load();
  };

  const columns: ColumnsType<Automation> = [
    {
      title: '自动化', dataIndex: 'name', render: (_, row) => (
        <button className="automation-name-button" onClick={() => navigate(`/automations/${row.id}`)}>
          <strong>{row.name}</strong><span>{row.description || '暂无描述'}</span>
        </button>
      ),
    },
    { title: '状态', dataIndex: 'status', width: 110, render: value => <Tag color={statusColors[value]}>{statusLabels[value] || value}</Tag> },
    { title: '触发', dataIndex: 'trigger_type', width: 120, render: value => <span className="automation-trigger">{value === 'schedule' ? <ClockCircleOutlined aria-hidden="true" /> : <LinkOutlined aria-hidden="true" />}{value === 'schedule' ? '定时' : 'Webhook'}</span> },
    { title: '目标', dataIndex: 'target_name', render: (_, row) => <><Tag>{row.target_type === 'application' ? '应用' : '工作流'}</Tag>{row.target_name}</> },
    { title: '下次执行', dataIndex: 'next_run_at', width: 190, render: value => value ? new Date(value).toLocaleString() : '—' },
    { title: '最近结果', width: 120, render: (_, row) => row.last_invocation ? <Tag>{resultLabels[row.last_invocation.status] || row.last_invocation.status}</Tag> : <span className="automation-no-runs">尚未执行</span> },
    {
      title: '操作', width: 180, render: (_, row) => <Space>
        <Button size="small" onClick={() => navigate(`/automations/${row.id}`)}>详情</Button>
        {canOperate && <Button size="small" onClick={() => void toggle(row)} disabled={row.status === 'blocked'}>
          {row.status === 'active' ? '暂停' : '启用'}
        </Button>}
      </Space>,
    },
  ];

  const filtered = rows.filter(row => `${row.name} ${row.target_name}`.toLowerCase().includes(query.toLowerCase()));
  return <div className="automations-page workspace-page">
    <WorkspaceHeader
      icon={<ThunderboltOutlined />} eyebrow="自动运行" title="自动化"
      description="设定执行计划，或通过 Webhook 触发，让应用与工作流按约定自动运转。"
      loading={loading}
      action={canCreate && <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/automations/new')}>新建自动化</Button>}
      metrics={[
        { label: '当前筛选', value: filtered.length, hint: '符合筛选条件的自动化' },
        { label: '已启用', value: filtered.filter(row => row.status === 'active').length, hint: '当前筛选中的启用项' },
        { label: '需处理', value: filtered.filter(row => row.status === 'blocked').length, hint: '当前筛选中的受阻项' },
      ]}
    />
    <div className="workspace-section-heading"><h2>自动化任务</h2><span>查看触发方式、执行计划与最近结果</span></div>
    <div className="automations-card">
      <div className="automations-toolbar">
        <Input.Search allowClear aria-label="搜索自动化名称或目标" placeholder="搜索名称或目标" value={query} onChange={event => setQuery(event.target.value)} />
        <Select allowClear aria-label="筛选自动化状态" placeholder="全部状态" value={statusFilter} onChange={setStatusFilter} options={['active', 'paused', 'blocked', 'draft'].map(value => ({ value, label: statusLabels[value] }))} />
        <Select allowClear aria-label="筛选触发方式" placeholder="全部触发方式" value={triggerFilter} onChange={setTriggerFilter} options={[{ value: 'schedule', label: '定时' }, { value: 'webhook', label: 'Webhook' }]} />
        <Button icon={<ReloadOutlined />} loading={loading} onClick={() => void load()}>刷新</Button>
      </div>
      <Table rowKey="id" loading={loading} columns={columns} dataSource={filtered} scroll={{ x: 980 }} locale={{ emptyText: <Empty description={query || statusFilter || triggerFilter ? '没有匹配的自动化，试试调整筛选条件' : '还没有自动化，创建计划让工作自动运行'} /> }} />
    </div>
  </div>;
}
