import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ApartmentOutlined, AppstoreOutlined, ArrowRightOutlined, ClockCircleOutlined,
  CloseCircleOutlined, DatabaseOutlined, ReloadOutlined, WarningOutlined,
} from '@ant-design/icons';
import { Button, Empty, Spin, Tag } from 'antd';
import { useLocation, useNavigate } from 'react-router-dom';

import { api } from '@/services/api';
import type { RunResource } from '@/services/applicationRuntime';
import { tenantApiRoot } from '@/services/tenantContext';
import { useAuthStore } from '@/stores/useAuthStore';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import { usePreferencesStore } from '@/stores/usePreferencesStore';
import useMediaQuery from '@/hooks/useMediaQuery';
import HomeApplicationsSidebar from '@/components/Sidebar/HomeApplicationsSidebar';
import { collapseConversationRuns, taskType } from '@/pages/Tasks/taskCenterModel';
import './HomePage.css';

const ACTIVE_STATUSES = new Set([
  'queued', 'running', 'waiting_input', 'waiting_children', 'cancelling',
]);

const statusMeta: Record<string, { label: string; color: string }> = {
  queued: { label: '排队中', color: 'default' },
  running: { label: '执行中', color: 'processing' },
  waiting_input: { label: '待处理', color: 'gold' },
  waiting_children: { label: '执行中', color: 'processing' },
  cancelling: { label: '取消中', color: 'orange' },
  succeeded: { label: '已完成', color: 'success' },
  failed: { label: '失败', color: 'error' },
  cancelled: { label: '已取消', color: 'default' },
};

const taskTypeLabel: Record<string, string> = {
  automation: '自动化', workflow: '工作流', application: '应用',
  execution: '执行任务',
  conversation: '对话', delegate: 'AI 分身', agent: '智能体', evaluation: '评测',
};

const formatTime = (value?: string | null) => value
  ? new Intl.DateTimeFormat('zh-CN', {
      month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
    }).format(new Date(value))
  : '—';

const taskTitle = (run: RunResource) => run.task_title
  || `${taskTypeLabel[taskType(run)] || '任务'} #${run.source_id || run.id.slice(0, 8)}`;

export default function HomePage() {
  const navigate = useNavigate();
  const location = useLocation();
  const layoutMode = usePreferencesStore((state) => state.layoutMode);
  const isMobile = useMediaQuery('(max-width: 767px)');
  const showInlineApps = layoutMode === 'left-right' && !isMobile
    && new URLSearchParams(location.search).get('embedded') !== '1';
  const username = useAuthStore((state) => state.user?.username);
  const organizationId = useOrganizationStore((state) => state.currentOrganizationId);
  const loadOrganizations = useOrganizationStore((state) => state.loadOrganizations);
  const [runs, setRuns] = useState<RunResource[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => { void loadOrganizations(); }, [loadOrganizations]);

  const loadRuns = useCallback(async () => {
    if (!organizationId) return;
    setLoading(true);
    try {
      const response = await api.get<RunResource[]>(
        `${tenantApiRoot(organizationId)}/runs`,
        { collapse_conversations: true },
      );
      setRuns(collapseConversationRuns(response));
    } catch {
      setRuns([]);
    } finally {
      setLoading(false);
    }
  }, [organizationId]);

  useEffect(() => { void loadRuns(); }, [loadRuns]);

  const summary = useMemo(() => ({
    active: runs.filter((run) => ACTIVE_STATUSES.has(run.status)).length,
    waiting: runs.filter((run) => run.status === 'waiting_input').length,
    completed: runs.filter((run) => run.status === 'succeeded').length,
    failed: runs.filter((run) => run.status === 'failed').length,
  }), [runs]);
  const recentRuns = runs.slice(0, 5);

  return <div className="home-page animate-fade-in">
    <header className="home-heading">
      <div>
        <span className="home-eyebrow">WORKBENCH</span>
        <h1>{username ? `${username}，欢迎回来` : '欢迎回来'}</h1>
        <p>在这里继续最近的工作，处理等待你的任务。</p>
      </div>
      <Button icon={<ReloadOutlined />} loading={loading} onClick={() => void loadRuns()}>刷新</Button>
    </header>

    {showInlineApps && (
      <section className="home-applications" aria-label="我的应用">
        <HomeApplicationsSidebar horizontalWheelScroll />
      </section>
    )}

    <section className="home-overview" aria-label="任务概览">
      <button type="button" onClick={() => navigate('/tasks')}><ClockCircleOutlined /><span><small>执行中</small><strong>{summary.active}</strong></span></button>
      <button type="button" onClick={() => navigate('/tasks')}><WarningOutlined /><span><small>待我处理</small><strong>{summary.waiting}</strong></span></button>
      <button type="button" onClick={() => navigate('/tasks')}><span className="home-status-symbol">✓</span><span><small>已完成</small><strong>{summary.completed}</strong></span></button>
      <button type="button" onClick={() => navigate('/tasks')}><CloseCircleOutlined /><span><small>失败</small><strong>{summary.failed}</strong></span></button>
    </section>

    <div className="home-dashboard-grid">
      <section className="home-panel home-recent-panel">
        <div className="home-panel-heading"><div><span>任务</span><h2>最近活动</h2></div><Button type="link" onClick={() => navigate('/tasks')}>查看全部 <ArrowRightOutlined /></Button></div>
        <Spin spinning={loading}>
          {recentRuns.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无任务" /> : <div className="home-recent-list">
            {recentRuns.map((run) => {
              const type = taskType(run);
              const status = statusMeta[run.status] || { label: run.status, color: 'default' };
              return <button type="button" key={run.id} onClick={() => navigate(`/tasks?run=${encodeURIComponent(run.id)}`)}>
                <span className="home-task-mark" aria-hidden="true" />
                <span className="home-task-copy"><strong>{taskTitle(run)}</strong><small>{taskTypeLabel[type] || '任务'} · {formatTime(run.created_at)}</small></span>
                <Tag color={status.color}>{status.label}</Tag>
              </button>;
            })}
          </div>}
        </Spin>
      </section>

      <section className="home-panel home-quick-panel">
        <div className="home-panel-heading"><div><span>快捷入口</span><h2>开始工作</h2></div></div>
        <div className="home-quick-list">
          <button type="button" onClick={() => navigate('/apps')}><AppstoreOutlined /><span><strong>打开应用</strong><small>选择已发布的业务应用</small></span><ArrowRightOutlined /></button>
          <button type="button" onClick={() => navigate('/build')}><ApartmentOutlined /><span><strong>进入构建</strong><small>创建分身、工作流和自动化</small></span><ArrowRightOutlined /></button>
          <button type="button" onClick={() => navigate('/resources')}><DatabaseOutlined /><span><strong>管理资源</strong><small>维护智能体、技能和知识库</small></span><ArrowRightOutlined /></button>
        </div>
      </section>
    </div>
  </div>;
}
