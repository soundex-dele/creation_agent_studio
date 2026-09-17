import { useCallback, useEffect, useState } from 'react';
import { Button, Empty, Input, Select, Space, Table, Tag, message } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useNavigate } from 'react-router-dom';
import { automationApi } from '@/services/automations';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import type { Automation } from '@/types/automation';
import './Automations.css';

const statusColors: Record<string, string> = {
  active: 'green', paused: 'default', blocked: 'red', draft: 'blue', archived: 'default',
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
    { title: '状态', dataIndex: 'status', width: 110, render: value => <Tag color={statusColors[value]}>{value}</Tag> },
    { title: '触发', dataIndex: 'trigger_type', width: 120, render: value => value === 'schedule' ? '定时' : 'Webhook' },
    { title: '目标', dataIndex: 'target_name', render: (_, row) => <><Tag>{row.target_type === 'application' ? '应用' : '工作流'}</Tag>{row.target_name}</> },
    { title: '下次执行', dataIndex: 'next_run_at', width: 190, render: value => value ? new Date(value).toLocaleString() : '—' },
    { title: '最近结果', width: 120, render: (_, row) => row.last_invocation ? <Tag>{row.last_invocation.status}</Tag> : '—' },
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
  return <div className="automations-page animate-fade-in">
    <div className="automations-hero">
      <div><h1 className="page-title">自动化</h1><p className="page-subtitle">按计划或 Webhook 自动运行应用与工作流</p></div>
      {canCreate && <Button type="primary" onClick={() => navigate('/automations/new')}>新建自动化</Button>}
    </div>
    <div className="automations-toolbar">
      <Input.Search allowClear placeholder="搜索名称或目标" value={query} onChange={event => setQuery(event.target.value)} />
      <Select allowClear placeholder="全部状态" value={statusFilter} onChange={setStatusFilter} options={['active', 'paused', 'blocked', 'draft'].map(value => ({ value, label: value }))} />
      <Select allowClear placeholder="全部触发方式" value={triggerFilter} onChange={setTriggerFilter} options={[{ value: 'schedule', label: '定时' }, { value: 'webhook', label: 'Webhook' }]} />
      <Button onClick={() => void load()}>刷新</Button>
    </div>
    <div className="automations-card"><Table rowKey="id" loading={loading} columns={columns} dataSource={filtered} scroll={{ x: 980 }} locale={{ emptyText: <Empty description="暂无自动化" /> }} /></div>
  </div>;
}
