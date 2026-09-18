import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Button, Card, Descriptions, Drawer, Empty, Input, Select, Space, Statistic, Table,
  Tabs, Tag, Typography, message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  CheckCircleOutlined, ClockCircleOutlined, ExportOutlined, ReloadOutlined,
  SearchOutlined, WarningOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';

import { api } from '@/services/api';
import type { RunResource } from '@/services/applicationRuntime';
import { tenantApiRoot } from '@/services/tenantContext';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import {
  buildTaskRelation,
  primaryTaskTypes,
  taskApplicationId,
  taskConversationId,
  taskDestination,
  taskType,
  taskWorkflowId,
  type PrimaryTaskType,
} from './taskCenterModel';
import './TaskCenterPage.css';

type TaskTypeFilter = 'all' | PrimaryTaskType | 'other';
type TaskStatusFilter = 'all' | 'active' | 'completed';

const ACTIVE_STATUSES = new Set([
  'queued', 'running', 'waiting_input', 'waiting_children', 'cancelling',
]);
const COMPLETED_STATUSES = new Set(['succeeded', 'failed', 'cancelled']);

const statusMeta: Record<string, { label: string; color: string }> = {
  queued: { label: '排队中', color: 'default' },
  running: { label: '执行中', color: 'processing' },
  waiting_input: { label: '等待处理', color: 'gold' },
  waiting_children: { label: '执行中', color: 'processing' },
  cancelling: { label: '取消中', color: 'orange' },
  succeeded: { label: '已完成', color: 'success' },
  failed: { label: '失败', color: 'error' },
  cancelled: { label: '已取消', color: 'default' },
};

const typeMeta: Record<string, { label: string; icon: string }> = {
  automation: { label: '自动化', icon: '⏱️' },
  workflow: { label: '工作流', icon: '🔀' },
  application: { label: '应用', icon: '🧩' },
  conversation: { label: '对话', icon: '💬' },
  execution: { label: '执行任务', icon: '▶️' },
  delegate: { label: 'AI 分身', icon: '🧭' },
  agent: { label: '智能体', icon: '🤖' },
  evaluation: { label: '评测', icon: '🧪' },
};

const formatTime = (value?: string | null) => value
  ? new Intl.DateTimeFormat('zh-CN', {
      month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
    }).format(new Date(value))
  : '—';

const taskTitle = (run: RunResource) => run.task_title
  || `${typeMeta[taskType(run)]?.label || '任务'} #${run.source_id || run.id.slice(0, 8)}`;

const triggerLabel = (trigger?: string) => {
  if (trigger === 'schedule') return '定时触发';
  if (trigger === 'webhook') return 'Webhook';
  if (trigger === 'event') return '事件触发';
  if (trigger === 'parent') return '由上级任务创建';
  return '手动发起';
};

export default function TaskCenterPage() {
  const navigate = useNavigate();
  const organizationId = useOrganizationStore((state) => state.currentOrganizationId);
  const loadOrganizations = useOrganizationStore((state) => state.loadOrganizations);
  const [runs, setRuns] = useState<RunResource[]>([]);
  const [children, setChildren] = useState<RunResource[]>([]);
  const [selected, setSelected] = useState<RunResource | null>(null);
  const [typeFilter, setTypeFilter] = useState<TaskTypeFilter>('all');
  const [statusFilter, setStatusFilter] = useState<TaskStatusFilter>('all');
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => { void loadOrganizations(); }, [loadOrganizations]);

  const load = useCallback(async () => {
    if (!organizationId) return;
    setLoading(true);
    try {
      const response = await api.get<RunResource[]>(`${tenantApiRoot(organizationId)}/runs`);
      setRuns(response);
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '加载任务失败');
    } finally {
      setLoading(false);
    }
  }, [organizationId]);

  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    if (!organizationId || !selected) { setChildren([]); return; }
    void api.get<RunResource[]>(
      `${tenantApiRoot(organizationId)}/runs/${selected.id}/children`,
    ).then(setChildren).catch(() => setChildren([]));
  }, [organizationId, selected]);

  const totals = useMemo(() => ({
    active: runs.filter((run) => ACTIVE_STATUSES.has(run.status)).length,
    completed: runs.filter((run) => run.status === 'succeeded').length,
    waiting: runs.filter((run) => run.status === 'waiting_input').length,
    failed: runs.filter((run) => run.status === 'failed').length,
  }), [runs]);

  const typeCounts = useMemo(() => Object.fromEntries(
    [...primaryTaskTypes, 'other'].map((type) => [type, runs.filter((run) => (
      type === 'other'
        ? !primaryTaskTypes.includes(taskType(run) as PrimaryTaskType)
        : taskType(run) === type
    )).length]),
  ) as Record<PrimaryTaskType | 'other', number>, [runs]);

  const visibleRuns = useMemo(() => runs.filter((run) => {
    const type = taskType(run);
    if (typeFilter === 'other' && primaryTaskTypes.includes(type as PrimaryTaskType)) return false;
    if (typeFilter !== 'all' && typeFilter !== 'other' && type !== typeFilter) return false;
    if (statusFilter === 'active' && !ACTIVE_STATUSES.has(run.status)) return false;
    if (statusFilter === 'completed' && !COMPLETED_STATUSES.has(run.status)) return false;
    const keyword = query.trim().toLowerCase();
    if (!keyword) return true;
    const relationship = buildTaskRelation(run, runs)
      .map((node) => typeMeta[node.type]?.label || node.type).join(' ');
    return `${taskTitle(run)} ${typeMeta[type]?.label || ''} ${relationship} ${run.status}`
      .toLowerCase().includes(keyword);
  }), [query, runs, statusFilter, typeFilter]);

  const openDestination = (run: RunResource, requestedType = taskType(run)) => {
    const destination = taskDestination(run, requestedType);
    if (destination) navigate(destination.path);
  };

  const renderRelationship = (run: RunResource, source = runs) => {
    const nodes = buildTaskRelation(run, source);
    return <div className="task-relation-chain" aria-label="任务关联关系">
      {nodes.map((node, index) => {
        const meta = typeMeta[node.type] || { label: node.type, icon: '•' };
        const destination = taskDestination(node.run, node.type);
        return <span className="task-relation-part" key={`${node.type}-${index}`}>
          {index > 0 && <span className="task-relation-arrow">→</span>}
          <button
            type="button"
            className={node.type === taskType(run) ? 'current' : ''}
            disabled={!destination}
            title={destination?.label || meta.label}
            onClick={(event) => {
              event.stopPropagation();
              if (destination) navigate(destination.path);
            }}
          >
            <span aria-hidden="true">{meta.icon}</span>{meta.label}
          </button>
        </span>;
      })}
    </div>;
  };

  const columns: ColumnsType<RunResource> = [
    {
      title: '任务', dataIndex: 'task_title', render: (_, run) => {
        const meta = typeMeta[taskType(run)] || { label: '任务', icon: '•' };
        return <button type="button" className="task-title-button" onClick={() => setSelected(run)}>
          <span className="task-type-icon" aria-hidden="true">{meta.icon}</span>
          <span><strong>{taskTitle(run)}</strong><small>{meta.label} · {triggerLabel(run.trigger_type)}</small></span>
        </button>;
      },
    },
    {
      title: '关联关系', key: 'relationship', width: 330,
      render: (_, run) => renderRelationship(run),
    },
    {
      title: '状态', dataIndex: 'status', width: 110, render: (status: string) => {
        const meta = statusMeta[status] || { label: status, color: 'default' };
        return <Tag color={meta.color}>{meta.label}</Tag>;
      },
    },
    { title: '开始时间', dataIndex: 'created_at', width: 155, render: formatTime },
    {
      title: '操作', width: 150, fixed: 'right', render: (_, run) => {
        const destination = taskDestination(run);
        return <Space size={4}>
          <Button size="small" onClick={() => setSelected(run)}>详情</Button>
          {destination && <Button type="link" size="small" icon={<ExportOutlined />} onClick={() => openDestination(run)}>
            {taskType(run) === 'conversation' ? '打开对话' : '打开'}
          </Button>}
        </Space>;
      },
    },
  ];

  const relationSource = useMemo(() => {
    const merged = new Map(runs.map((run) => [run.id, run]));
    children.forEach((run) => merged.set(run.id, run));
    return [...merged.values()];
  }, [children, runs]);
  const selectedDestination = selected ? taskDestination(selected) : null;
  const selectedParent = selected?.parent_id
    ? relationSource.find((run) => run.id === selected.parent_id)
    : null;

  return <div className="task-center-page animate-fade-in">
    <div className="task-center-heading">
      <div><h1 className="page-title">任务中心</h1><p className="page-subtitle">按自动化、工作流和对话查看任务，并追踪任务与来源应用之间的调用关系</p></div>
      <Button icon={<ReloadOutlined />} loading={loading} onClick={() => void load()}>刷新</Button>
    </div>

    <div className="task-stat-grid">
      <Card><Statistic title="执行中" value={totals.active} prefix={<ClockCircleOutlined />} /></Card>
      <Card><Statistic title="待我处理" value={totals.waiting} prefix={<WarningOutlined />} /></Card>
      <Card><Statistic title="已完成" value={totals.completed} prefix={<CheckCircleOutlined />} /></Card>
      <Card><Statistic title="失败" value={totals.failed} prefix={<WarningOutlined />} /></Card>
    </div>

    <Card className="task-list-card">
      <Tabs
        className="task-type-tabs"
        activeKey={typeFilter}
        onChange={(key) => setTypeFilter(key as TaskTypeFilter)}
        items={[
          { key: 'all', label: `全部 ${runs.length}` },
          ...primaryTaskTypes.map((type) => ({
            key: type,
            label: `${typeMeta[type].icon} ${typeMeta[type].label} ${typeCounts[type]}`,
          })),
          ...(typeCounts.other ? [{ key: 'other', label: `其他 ${typeCounts.other}` }] : []),
        ]}
      />
      <div className="task-list-toolbar">
        <Select<TaskStatusFilter>
          value={statusFilter}
          onChange={setStatusFilter}
          aria-label="任务状态筛选"
          options={[
            { value: 'all', label: '全部状态' },
            { value: 'active', label: '执行中' },
            { value: 'completed', label: '已结束' },
          ]}
        />
        <Input
          allowClear prefix={<SearchOutlined />} placeholder="搜索任务或关联类型"
          value={query} onChange={(event) => setQuery(event.target.value)}
        />
      </div>
      <Table
        rowKey="id" loading={loading} columns={columns} dataSource={visibleRuns}
        scroll={{ x: 1050 }} pagination={{ pageSize: 20 }}
        locale={{ emptyText: <Empty description="暂无任务" /> }}
      />
    </Card>

    <Drawer
      title={selected ? taskTitle(selected) : '任务详情'}
      width={720}
      open={Boolean(selected)}
      onClose={() => setSelected(null)}
      extra={selectedDestination && <Button type="primary" icon={<ExportOutlined />} onClick={() => selected && openDestination(selected)}>
        {selectedDestination.label}
      </Button>}
    >
      {selected && <Space direction="vertical" size="large" style={{ width: '100%' }}>
        <section className="task-detail-relation">
          <Typography.Title level={5}>任务关系</Typography.Title>
          {renderRelationship(selected, relationSource)}
          <Typography.Paragraph type="secondary">
            应用是任务来源而不是任务类型；自动化可触发工作流或应用，应用产生的对话会作为任务展示。
          </Typography.Paragraph>
        </section>
        <Descriptions bordered size="small" column={1} items={[
          { key: 'type', label: '任务类型', children: typeMeta[taskType(selected)]?.label || taskType(selected) },
          { key: 'status', label: '状态', children: statusMeta[selected.status]?.label || selected.status },
          { key: 'trigger', label: '触发方式', children: triggerLabel(selected.trigger_type) },
          ...(selectedParent ? [{
            key: 'parent', label: '上级任务', children: <Button type="link" onClick={() => setSelected(selectedParent)}>{taskTitle(selectedParent)}</Button>,
          }] : []),
          ...(selected.automation_id ? [{ key: 'automation', label: '自动化 ID', children: String(selected.automation_id) }] : []),
          ...(taskWorkflowId(selected) ? [{ key: 'workflow', label: '工作流 ID', children: taskWorkflowId(selected) }] : []),
          ...(taskApplicationId(selected) ? [{ key: 'application', label: '应用 ID', children: taskApplicationId(selected) }] : []),
          ...(taskConversationId(selected) ? [{
            key: 'conversation', label: '对话 ID', children: <Button type="link" onClick={() => openDestination(selected, 'conversation')}>{taskConversationId(selected)}</Button>,
          }] : []),
          { key: 'created', label: '开始时间', children: formatTime(selected.created_at) },
          { key: 'finished', label: '完成时间', children: formatTime(selected.finished_at) },
          { key: 'id', label: '任务 ID', children: <Typography.Text copyable code>{selected.id}</Typography.Text> },
          ...(selected.error_message ? [{ key: 'error', label: '错误', children: selected.error_message }] : []),
        ]} />
        {children.length > 0 && <section><Typography.Title level={5}>下级任务</Typography.Title><div className="task-child-list">
          {children.map((child) => <button type="button" key={child.id} onClick={() => setSelected(child)}>
            <span>{typeMeta[taskType(child)]?.icon || '•'}</span>
            <span><strong>{taskTitle(child)}</strong><small>{typeMeta[taskType(child)]?.label || taskType(child)}</small></span>
            <Tag color={statusMeta[child.status]?.color}>{statusMeta[child.status]?.label || child.status}</Tag>
          </button>)}
        </div></section>}
        <section><Typography.Title level={5}>输入</Typography.Title><pre className="task-json">{JSON.stringify(selected.input || {}, null, 2)}</pre></section>
        <section><Typography.Title level={5}>输出</Typography.Title><pre className="task-json">{JSON.stringify(selected.output_summary || {}, null, 2)}</pre></section>
      </Space>}
    </Drawer>
  </div>;
}
