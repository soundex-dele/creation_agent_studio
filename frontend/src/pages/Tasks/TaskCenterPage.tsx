import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import {
  Button, Descriptions, Drawer, Empty, Input, Select, Space, Spin, Table,
  Tabs, Tag, Typography, message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  ApartmentOutlined, AppstoreOutlined, CheckCircleOutlined, ClockCircleOutlined,
  CaretDownOutlined, CaretRightOutlined, CloseCircleOutlined, CommentOutlined,
  CompassOutlined, ExperimentOutlined,
  ExportOutlined, FieldTimeOutlined, PlayCircleOutlined, ReloadOutlined,
  RobotOutlined, SearchOutlined, UnorderedListOutlined, WarningOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';

import { api } from '@/services/api';
import type { RunResource } from '@/services/applicationRuntime';
import { tenantApiRoot } from '@/services/tenantContext';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import {
  buildTaskRelation,
  buildTaskTree,
  collapseConversationRuns,
  flattenTaskTree,
  primaryTaskTypes,
  taskApplicationId,
  taskConversationId,
  taskDestination,
  taskType,
  taskWorkflowId,
  type PrimaryTaskType,
  type TaskTreeNode,
} from './taskCenterModel';
import './TaskCenterPage.css';

type TaskTypeFilter = 'all' | PrimaryTaskType | 'other';
type TaskStatusFilter = 'all' | 'active' | 'completed';

const ACTIVE_STATUSES = new Set([
  'queued', 'running', 'waiting_input', 'waiting_children', 'cancelling',
]);
const COMPLETED_STATUSES = new Set(['succeeded', 'failed', 'cancelled']);

const statusMeta: Record<string, { label: string; color: string; tone: string }> = {
  queued: { label: '排队中', color: 'default', tone: 'neutral' },
  running: { label: '执行中', color: 'processing', tone: 'active' },
  waiting_input: { label: '等待处理', color: 'gold', tone: 'waiting' },
  waiting_children: { label: '执行中', color: 'processing', tone: 'active' },
  cancelling: { label: '取消中', color: 'orange', tone: 'waiting' },
  succeeded: { label: '已完成', color: 'success', tone: 'success' },
  failed: { label: '失败', color: 'error', tone: 'danger' },
  cancelled: { label: '已取消', color: 'default', tone: 'neutral' },
};

const typeMeta: Record<string, { label: string; icon: ReactNode; tone: string }> = {
  automation: { label: '自动化', icon: <FieldTimeOutlined />, tone: 'amber' },
  workflow: { label: '工作流', icon: <ApartmentOutlined />, tone: 'blue' },
  application: { label: '应用', icon: <AppstoreOutlined />, tone: 'violet' },
  conversation: { label: '对话', icon: <CommentOutlined />, tone: 'green' },
  execution: { label: '执行任务', icon: <PlayCircleOutlined />, tone: 'blue' },
  delegate: { label: 'AI 分身', icon: <CompassOutlined />, tone: 'violet' },
  agent: { label: '智能体', icon: <RobotOutlined />, tone: 'amber' },
  evaluation: { label: '评测', icon: <ExperimentOutlined />, tone: 'green' },
};

const fallbackTypeMeta = {
  label: '任务', icon: <UnorderedListOutlined />, tone: 'neutral',
};

function TaskStatusBadge({ status }: { status: string }) {
  const meta = statusMeta[status] || { label: status, color: 'default', tone: 'neutral' };
  return <span className={`task-status task-status--${meta.tone}`}>
    <span className="task-status-dot" aria-hidden="true" />
    {meta.label}
  </span>;
}

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
  const [treeRoot, setTreeRoot] = useState<RunResource | null>(null);
  const [treeRuns, setTreeRuns] = useState<RunResource[]>([]);
  const [treeLoading, setTreeLoading] = useState(false);
  const [typeFilter, setTypeFilter] = useState<TaskTypeFilter>('all');
  const [statusFilter, setStatusFilter] = useState<TaskStatusFilter>('all');
  const [query, setQuery] = useState('');
  const [collapsedTreeNodes, setCollapsedTreeNodes] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);

  useEffect(() => { void loadOrganizations(); }, [loadOrganizations]);

  const load = useCallback(async () => {
    if (!organizationId) return;
    setLoading(true);
    try {
      const response = await api.get<RunResource[]>(
        `${tenantApiRoot(organizationId)}/runs`,
        { collapse_conversations: true },
      );
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

  const taskRuns = useMemo(() => collapseConversationRuns(runs), [runs]);
  const runsWithChildren = useMemo(() => new Set(
    taskRuns.flatMap((run) => run.parent_id ? [run.parent_id] : []),
  ), [taskRuns]);

  const totals = useMemo(() => ({
    active: taskRuns.filter((run) => ACTIVE_STATUSES.has(run.status)).length,
    completed: taskRuns.filter((run) => run.status === 'succeeded').length,
    waiting: taskRuns.filter((run) => run.status === 'waiting_input').length,
    failed: taskRuns.filter((run) => run.status === 'failed').length,
  }), [taskRuns]);

  const typeCounts = useMemo(() => Object.fromEntries(
    [...primaryTaskTypes, 'other'].map((type) => [type, taskRuns.filter((run) => (
      type === 'other'
        ? !primaryTaskTypes.includes(taskType(run) as PrimaryTaskType)
        : taskType(run) === type
    )).length]),
  ) as Record<PrimaryTaskType | 'other', number>, [taskRuns]);

  const visibleRuns = useMemo(() => taskRuns.filter((run) => {
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
  }), [query, runs, statusFilter, taskRuns, typeFilter]);

  const openDestination = (run: RunResource, requestedType = taskType(run)) => {
    const destination = taskDestination(run, requestedType);
    if (destination) navigate(destination.path);
  };

  const openTreeBoard = async (run: RunResource) => {
    setTreeRoot(run);
    setTreeRuns([]);
    setCollapsedTreeNodes(new Set());
    if (!organizationId) return;
    setTreeLoading(true);
    try {
      const descendants = await api.get<RunResource[]>(
        `${tenantApiRoot(organizationId)}/runs/${run.id}/children`,
      );
      setTreeRuns(descendants);
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '加载任务树失败');
    } finally {
      setTreeLoading(false);
    }
  };

  const renderRelationship = (run: RunResource, source = runs) => {
    const nodes = buildTaskRelation(run, source);
    return <div className="task-relation-chain" aria-label="任务关联关系">
      {nodes.map((node, index) => {
        const meta = typeMeta[node.type] || { ...fallbackTypeMeta, label: node.type };
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
        const meta = typeMeta[taskType(run)] || fallbackTypeMeta;
        return <button type="button" className="task-title-button" onClick={() => setSelected(run)}>
          <span className={`task-type-icon task-type-icon--${meta.tone}`} aria-hidden="true">{meta.icon}</span>
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
        return <TaskStatusBadge status={status} />;
      },
    },
    { title: '开始时间', dataIndex: 'created_at', width: 155, render: formatTime },
    {
      title: '操作', width: 260, fixed: 'right', render: (_, run) => {
        const destination = taskDestination(run);
        return <Space size={4}>
          <Button size="small" onClick={() => setSelected(run)}>详情</Button>
          {runsWithChildren.has(run.id) && <Button size="small" onClick={() => void openTreeBoard(run)}>树状看板</Button>}
          {destination && taskType(run) !== 'conversation' && <Button type="link" size="small" icon={<ExportOutlined />} onClick={() => openDestination(run)}>
            打开
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
  const treeNodes = useMemo(() => {
    if (!treeRoot) return [];
    const merged = new Map<string, RunResource>([[treeRoot.id, treeRoot]]);
    treeRuns.forEach((run) => merged.set(run.id, run));
    return buildTaskTree([...merged.values()]);
  }, [treeRoot, treeRuns]);
  const treeBranchIds = useMemo(() => {
    const ids = new Set<string>();
    const collect = (nodes: TaskTreeNode[]) => nodes.forEach((node) => {
      if (node.children.length) ids.add(node.run.id);
      collect(node.children);
    });
    collect(treeNodes);
    return ids;
  }, [treeNodes]);
  const allTreeBranchesCollapsed = treeBranchIds.size > 0
    && [...treeBranchIds].every((id) => collapsedTreeNodes.has(id));
  const selectedDestination = selected ? taskDestination(selected) : null;
  const selectedParent = selected?.parent_id
    ? relationSource.find((run) => run.id === selected.parent_id)
    : null;

  const stats = [
    {
      key: 'active', label: '执行中', value: totals.active,
      note: '正在排队或运行', icon: <ClockCircleOutlined />, tone: 'active',
    },
    {
      key: 'waiting', label: '待我处理', value: totals.waiting,
      note: '等待输入或确认', icon: <WarningOutlined />, tone: 'waiting',
    },
    {
      key: 'completed', label: '已完成', value: totals.completed,
      note: '已顺利完成', icon: <CheckCircleOutlined />, tone: 'success',
    },
    {
      key: 'failed', label: '失败', value: totals.failed,
      note: '需要检查处理', icon: <CloseCircleOutlined />, tone: 'danger',
    },
  ];

  const hasFilters = statusFilter !== 'all' || Boolean(query.trim());
  const clearFilters = () => {
    setStatusFilter('all');
    setQuery('');
  };

  const toggleTreeNode = (runId: string) => {
    setCollapsedTreeNodes((current) => {
      const next = new Set(current);
      if (next.has(runId)) next.delete(runId);
      else next.add(runId);
      return next;
    });
  };

  const renderTreeNode = (node: TaskTreeNode, depth = 0): ReactNode => {
    const { run } = node;
    const meta = typeMeta[taskType(run)] || fallbackTypeMeta;
    const destination = taskDestination(run);
    const hasChildren = node.children.length > 0;
    const expanded = hasChildren && !collapsedTreeNodes.has(run.id);
    const descendants = hasChildren ? flattenTaskTree(node.children) : [];
    const completedChildren = descendants.filter((item) => item.status === 'succeeded').length;
    const activeChildren = descendants.filter((item) => ACTIVE_STATUSES.has(item.status)).length;
    const failedChildren = descendants.filter((item) => item.status === 'failed').length;
    const completion = descendants.length
      ? Math.round((completedChildren / descendants.length) * 100)
      : 0;

    return <div
      className={`task-tree-node ${depth === 0 ? 'task-tree-node--root' : 'task-tree-node--child'}`}
      key={run.id}
      data-depth={depth}
    >
      <div className="task-tree-node-row">
        {hasChildren ? <button
          type="button"
          className="task-tree-toggle"
          aria-expanded={expanded}
          aria-label={`${expanded ? '收起' : '展开'}${taskTitle(run)}的子任务`}
          onClick={() => toggleTreeNode(run.id)}
        >
          {expanded ? <CaretDownOutlined /> : <CaretRightOutlined />}
        </button> : <span className="task-tree-toggle-placeholder" aria-hidden="true" />}
        <span className={`task-type-icon task-type-icon--${meta.tone}`} aria-hidden="true">{meta.icon}</span>
        <button type="button" className="task-tree-title" onClick={() => {
          setTreeRoot(null);
          setSelected(run);
        }}>
          <strong>{taskTitle(run)}</strong>
          <small>
            {meta.label} · {triggerLabel(run.trigger_type)}
            {hasChildren ? ` · ${descendants.length} 个下级任务` : ''}
          </small>
        </button>
        <TaskStatusBadge status={run.status} />
        <span className="task-tree-time"><ClockCircleOutlined aria-hidden="true" />{formatTime(run.created_at)}</span>
        <div className="task-tree-actions">
          <Button type="text" size="small" onClick={() => {
            setTreeRoot(null);
            setSelected(run);
          }}>详情</Button>
          {destination && taskType(run) !== 'conversation' && <Button
            type="link" size="small" icon={<ExportOutlined />}
            onClick={() => openDestination(run)}
          >打开</Button>}
        </div>
      </div>
      {depth === 0 && hasChildren && <div className="task-tree-progress" aria-label={`子任务进度 ${completedChildren}/${descendants.length}`}>
        <span><strong>{completedChildren}/{descendants.length}</strong> 子任务已完成</span>
        <span className="task-tree-progress-track" aria-hidden="true"><i style={{ width: `${completion}%` }} /></span>
        <span className="task-tree-progress-states">
          {activeChildren > 0 && <em className="active">{activeChildren} 执行中</em>}
          {failedChildren > 0 && <em className="failed">{failedChildren} 失败</em>}
          {activeChildren === 0 && failedChildren === 0 && <em>{completion === 100 ? '全部完成' : '等待执行'}</em>}
        </span>
      </div>}
      {expanded && <div className="task-tree-children" role="group" aria-label={`${taskTitle(run)}的子任务`}>
        {node.children.map((child) => renderTreeNode(child, depth + 1))}
      </div>}
    </div>;
  };

  return <div className="task-center-page animate-fade-in">
    <header className="task-center-hero">
      <div className="task-center-heading">
        <div>
          <span className="task-center-eyebrow">TASK OVERVIEW</span>
          <h1 className="page-title">任务中心</h1>
          <p className="page-subtitle">统一查看自动化、工作流与对话任务，快速追踪每一次调用关系。</p>
        </div>
        <div className="task-hero-actions">
          <span className="task-total"><strong>{taskRuns.length}</strong> 个任务</span>
          <Button icon={<ReloadOutlined />} loading={loading} onClick={() => void load()}>刷新数据</Button>
        </div>
      </div>
    </header>

    <div className="task-stat-grid" aria-label="任务状态概览">
      {stats.map((stat) => <article className={`task-stat-card task-stat-card--${stat.tone}`} key={stat.key}>
        <span className="task-stat-icon" aria-hidden="true">{stat.icon}</span>
        <span className="task-stat-copy"><span>{stat.label}</span><small>{stat.note}</small></span>
        <strong>{stat.value}</strong>
      </article>)}
    </div>

    <section className="task-list-card" aria-labelledby="task-list-title">
      <div className="task-list-heading">
        <div>
          <span>任务记录</span>
          <h2 id="task-list-title">全部任务</h2>
        </div>
        <p>当前显示 <strong>{visibleRuns.length}</strong> 条</p>
      </div>
      <Tabs
        className="task-type-tabs"
        activeKey={typeFilter}
        onChange={(key) => setTypeFilter(key as TaskTypeFilter)}
        items={[
          { key: 'all', label: <span className="task-tab-label">全部 <b>{taskRuns.length}</b></span> },
          ...primaryTaskTypes.map((type) => ({
            key: type,
            label: <span className="task-tab-label"><span aria-hidden="true">{typeMeta[type].icon}</span>{typeMeta[type].label} <b>{typeCounts[type]}</b></span>,
          })),
          ...(typeCounts.other ? [{
            key: 'other',
            label: <span className="task-tab-label"><UnorderedListOutlined aria-hidden="true" />其他 <b>{typeCounts.other}</b></span>,
          }] : []),
        ]}
      />
      <div className="task-list-toolbar">
        <div className="task-filter-group">
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
            allowClear prefix={<SearchOutlined />} placeholder="搜索任务名称或关联类型"
            aria-label="搜索任务名称或关联类型"
            value={query} onChange={(event) => setQuery(event.target.value)}
          />
        </div>
        {hasFilters && <Button type="text" onClick={clearFilters}>清除筛选</Button>}
      </div>
      <Table
        className="task-desktop-table"
        rowKey="id" loading={loading} columns={columns} dataSource={visibleRuns}
        pagination={{
          pageSize: 20,
          showSizeChanger: false,
          hideOnSinglePage: true,
          showTotal: (total) => `共 ${total} 条`,
        }}
        locale={{ emptyText: <Empty description={hasFilters ? '没有匹配的任务' : '暂无任务'} /> }}
      />
      <div className="task-mobile-list">
        {visibleRuns.map((run) => {
          const meta = typeMeta[taskType(run)] || fallbackTypeMeta;
          const destination = taskDestination(run);
          return <article className="task-mobile-card" key={run.id}>
            <div className="task-mobile-card-main">
              <span className={`task-type-icon task-type-icon--${meta.tone}`} aria-hidden="true">{meta.icon}</span>
              <button type="button" className="task-mobile-title" onClick={() => setSelected(run)}>
                <strong>{taskTitle(run)}</strong>
                <small>{meta.label} · {triggerLabel(run.trigger_type)}</small>
              </button>
              <TaskStatusBadge status={run.status} />
            </div>
            {renderRelationship(run)}
            <footer>
              <span><ClockCircleOutlined aria-hidden="true" />{formatTime(run.created_at)}</span>
              <div>
                <Button type="text" size="small" onClick={() => setSelected(run)}>查看详情</Button>
                {runsWithChildren.has(run.id) && <Button type="text" size="small" onClick={() => void openTreeBoard(run)}>树状看板</Button>}
                {destination && taskType(run) !== 'conversation' && <Button type="link" size="small" icon={<ExportOutlined />} onClick={() => openDestination(run)}>打开</Button>}
              </div>
            </footer>
          </article>;
        })}
        {!loading && visibleRuns.length === 0 && <Empty description={hasFilters ? '没有匹配的任务' : '暂无任务'} />}
      </div>
    </section>

    <Drawer
      rootClassName="task-tree-drawer"
      title={treeRoot ? <div className="task-tree-drawer-title">
        <span><ApartmentOutlined aria-hidden="true" /></span>
        <span><strong>树状看板</strong><small>{taskTitle(treeRoot)}</small></span>
      </div> : '树状看板'}
      width={920}
      open={Boolean(treeRoot)}
      onClose={() => setTreeRoot(null)}
      extra={treeBranchIds.size > 0 && <Button type="text" onClick={() => {
        setCollapsedTreeNodes(allTreeBranchesCollapsed ? new Set() : new Set(treeBranchIds));
      }}>
        {allTreeBranchesCollapsed ? '全部展开' : '全部收起'}
      </Button>}
    >
      {treeLoading ? <div className="task-tree-loading"><Spin tip="正在加载任务树" /></div> : <div className="task-tree-board">
        {treeNodes.map((node) => renderTreeNode(node))}
        {treeNodes.length === 0 && <Empty description="暂无任务数据" />}
      </div>}
    </Drawer>

    <Drawer
      rootClassName="task-detail-drawer"
      title={selected ? <div className="task-drawer-title">
        <span className={`task-type-icon task-type-icon--${typeMeta[taskType(selected)]?.tone || 'neutral'}`} aria-hidden="true">
          {typeMeta[taskType(selected)]?.icon || fallbackTypeMeta.icon}
        </span>
        <span><strong>{taskTitle(selected)}</strong><small>{typeMeta[taskType(selected)]?.label || '任务'} · {triggerLabel(selected.trigger_type)}</small></span>
      </div> : '任务详情'}
      width={760}
      open={Boolean(selected)}
      onClose={() => setSelected(null)}
      extra={selectedDestination && <Button type="primary" icon={<ExportOutlined />} onClick={() => selected && openDestination(selected)}>
        {selectedDestination.label}
      </Button>}
    >
      {selected && <div className="task-detail-stack">
        <div className="task-detail-summary">
          <TaskStatusBadge status={selected.status} />
          <span>开始于 {formatTime(selected.created_at)}</span>
        </div>
        <section className="task-detail-relation">
          <div className="task-section-heading"><h3>任务关系</h3><span>从来源到当前任务的完整链路</span></div>
          {renderRelationship(selected, relationSource)}
          <Typography.Paragraph type="secondary">
            应用是任务来源而不是任务类型；自动化可触发工作流或应用，应用产生的对话会作为任务展示。
          </Typography.Paragraph>
        </section>
        <section className="task-detail-card">
          <div className="task-section-heading"><h3>基本信息</h3><span>任务标识、类型与执行时间</span></div>
          <Descriptions size="small" column={1} items={[
            { key: 'type', label: '任务类型', children: typeMeta[taskType(selected)]?.label || taskType(selected) },
            { key: 'status', label: '状态', children: <TaskStatusBadge status={selected.status} /> },
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
        </section>
        {children.length > 0 && <section className="task-detail-card"><div className="task-section-heading"><h3>下级任务</h3><span>{children.length} 个关联任务</span></div><div className="task-child-list">
          {children.map((child) => <button type="button" key={child.id} onClick={() => setSelected(child)}>
            <span className="task-child-icon" aria-hidden="true">{typeMeta[taskType(child)]?.icon || fallbackTypeMeta.icon}</span>
            <span><strong>{taskTitle(child)}</strong><small>{typeMeta[taskType(child)]?.label || taskType(child)}</small></span>
            <Tag color={statusMeta[child.status]?.color}>{statusMeta[child.status]?.label || child.status}</Tag>
          </button>)}
        </div></section>}
        <div className="task-payload-grid">
          <section className="task-detail-card"><div className="task-section-heading"><h3>输入</h3><span>任务接收的数据</span></div><pre className="task-json">{JSON.stringify(selected.input || {}, null, 2)}</pre></section>
          <section className="task-detail-card"><div className="task-section-heading"><h3>输出</h3><span>任务返回的摘要</span></div><pre className="task-json">{JSON.stringify(selected.output_summary || {}, null, 2)}</pre></section>
        </div>
      </div>}
    </Drawer>
  </div>;
}
