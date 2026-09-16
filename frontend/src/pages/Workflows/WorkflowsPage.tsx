import { useCallback, useEffect, useState } from 'react';
import { Button, Card, Empty, Popconfirm, Spin, Tag, message } from 'antd';
import {
  AppstoreOutlined, DeleteOutlined, EditOutlined, HistoryOutlined, PlayCircleOutlined,
  PlusOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { api } from '@/services/api';
import type { Workflow } from '@/types';
import type { RunResource } from '@/services/applicationRuntime';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import { tenantApiRoot } from '@/services/tenantContext';
import './Workflows.css';

const unwrap = <T,>(value: T[] | { results?: T[] }): T[] =>
  Array.isArray(value) ? value : value.results ?? [];

const wait = (milliseconds: number) => new Promise((resolve) => {
  window.setTimeout(resolve, milliseconds);
});

const WorkflowsPage = () => {
  const navigate = useNavigate();
  const organizationId = useOrganizationStore((state) => state.currentOrganizationId);
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [runs, setRuns] = useState<RunResource[]>([]);
  const [loading, setLoading] = useState(true);
  const [deletingWorkflowId, setDeletingWorkflowId] = useState<string | null>(null);
  const [deletingRunId, setDeletingRunId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [workflowResponse, runResponse] = await Promise.all([
        api.get<Workflow[] | { results?: Workflow[] }>('/workflows/'),
        organizationId
          ? api.get<RunResource[]>(`${tenantApiRoot(organizationId)}/runs`, {
              source_type: 'workflow',
            })
          : Promise.resolve([]),
      ]);
      setWorkflows(unwrap(workflowResponse));
      setRuns(unwrap(runResponse));
    } finally {
      setLoading(false);
    }
  }, [organizationId]);

  useEffect(() => { void load(); }, [load]);

  const start = async (workflow: Workflow) => {
    if (workflow.execution_mode === 'manual') {
      navigate(`/workflows/${workflow.id}/manual`);
      return;
    }
    try {
      const run = await api.post<{ id: string }>(
        `/workflows/${workflow.id}/start/`,
        undefined,
        { headers: { 'Idempotency-Key': crypto.randomUUID() } },
      );
      navigate(`/runs/${run.id}`);
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '工作流启动失败');
    }
  };

  const remove = async (workflow: Workflow) => {
    setDeletingWorkflowId(workflow.id);
    try {
      await api.delete(`/workflows/${workflow.id}/`);
      setWorkflows((current) => current.filter((item) => item.id !== workflow.id));
      message.success('工作流已删除');
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '删除工作流失败');
    } finally {
      setDeletingWorkflowId(null);
    }
  };

  const removeRun = async (run: RunResource) => {
    if (!organizationId) return;
    setDeletingRunId(run.id);
    try {
      const endpoint = `${tenantApiRoot(organizationId)}/runs/${run.id}`;
      let deleted = false;
      for (let attempt = 0; attempt < 120; attempt += 1) {
        const result = await api.delete<{
          deletion_pending?: boolean;
          detail?: string;
        } | undefined>(endpoint);
        if (!result?.deletion_pending) {
          deleted = true;
          break;
        }
        await wait(500);
      }
      if (!deleted) {
        throw new Error('取消工作流超时，请稍后重试');
      }
      setRuns((current) => current.filter((item) => item.id !== run.id));
      message.success('执行历史已删除');
    } catch (error: any) {
      message.error(error?.response?.data?.detail || error?.message || '删除执行历史失败');
    } finally {
      setDeletingRunId(null);
    }
  };

  return (
    <div className="workflows-page">
      <div className="workflows-heading">
        <div><h1>工作流</h1><p>把多个应用组合成可手动操作或自动运行的业务流程</p></div>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/workflows/new')}>
          新建工作流
        </Button>
      </div>
      {loading ? <div className="workflows-loading"><Spin size="large" /></div> : (
        <>
          {workflows.length === 0 ? <Empty description="还没有工作流" />
            : <div className="workflow-grid">{workflows.map((workflow) => (
              <Card key={workflow.id} className="workflow-card">
                <div className="workflow-card-icon">{workflow.icon || '🔀'}</div>
                <h3>{workflow.name}</h3>
                <p>{workflow.description || '未填写说明'}</p>
                <div className="workflow-card-meta">
                  <span>{workflow.step_count || 0} 个应用</span>
                  <Tag color={workflow.execution_mode === 'manual' ? 'gold' : 'blue'}>
                    {workflow.execution_mode === 'manual' ? '手动执行' : '自动执行'}
                  </Tag>
                </div>
                <div className="workflow-card-actions">
                  <OutlinedButton onClick={() => navigate(`/workflows/${workflow.id}/edit`)} />
                  {workflow.can_delete && (
                    <Popconfirm
                      title="删除工作流"
                      description={`确定删除“${workflow.name}”吗？此操作不可撤销。`}
                      okText="删除"
                      cancelText="取消"
                      okButtonProps={{ danger: true }}
                      onConfirm={() => remove(workflow)}
                    >
                      <Button
                        danger
                        icon={<DeleteOutlined />}
                        loading={deletingWorkflowId === workflow.id}
                        aria-label={`删除 ${workflow.name}`}
                      >
                        删除
                      </Button>
                    </Popconfirm>
                  )}
                  <Button
                    type="primary"
                    icon={workflow.execution_mode === 'manual'
                      ? <AppstoreOutlined /> : <PlayCircleOutlined />}
                    disabled={!workflow.step_count}
                    onClick={() => start(workflow)}
                  >
                    {workflow.execution_mode === 'manual' ? '打开' : '运行'}
                  </Button>
                </div>
              </Card>
            ))}</div>}

          <section className="workflow-history">
            <div className="workflow-history-heading">
              <div><HistoryOutlined /><h2>执行历史</h2></div>
              <span>所有状态来自统一 Run 事件流</span>
            </div>
            {runs.length === 0 ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无执行历史" />
            ) : (
              <div className="workflow-history-list">
                {runs.map((run) => {
                  const definition = run.definition_snapshot as {
                    workflow_name?: string;
                    workflow_steps?: unknown[];
                    execution_mode?: 'manual' | 'automatic';
                  };
                  return (
                    <div key={run.id} className="workflow-history-item">
                      <button
                        type="button"
                        className="workflow-history-link"
                        onClick={() => navigate(definition.execution_mode === 'manual'
                          ? `/workflows/${run.source_id}/manual?runId=${run.id}`
                          : `/runs/${run.id}`)}
                      >
                        <span className="workflow-history-icon"><HistoryOutlined /></span>
                        <span className="workflow-history-copy">
                          <strong>{definition.workflow_name || `Workflow ${run.source_id || ''}`}</strong>
                          <small>{new Date(run.created_at || '').toLocaleString()}</small>
                        </span>
                        <span className="workflow-history-progress">
                          {definition.execution_mode === 'manual' ? '手动执行 · ' : ''}
                          {definition.workflow_steps?.length || 0} 个应用
                        </span>
                        <span className={`workflow-history-status workflow-history-status--${run.status}`}>
                          {run.status === 'succeeded' ? '已完成'
                            : run.status === 'failed' ? '失败'
                              : run.status === 'cancelled' ? '已取消' : '进行中'}
                        </span>
                      </button>
                      {run.can_delete && (
                        <Popconfirm
                          title="删除执行历史"
                          description={['succeeded', 'failed', 'cancelled'].includes(run.status)
                            ? '确定删除这条执行历史吗？相关事件和产物也会删除，且无法恢复。'
                            : '执行仍在进行。删除时会先自动取消或结束工作流，再清理相关事件和产物。'}
                          okText="删除"
                          cancelText="取消"
                          okButtonProps={{ danger: true }}
                          onConfirm={() => removeRun(run)}
                        >
                          <Button
                            type="text"
                            danger
                            icon={<DeleteOutlined />}
                            loading={deletingRunId === run.id}
                            aria-label={`删除 ${definition.workflow_name || '工作流'} 的执行历史`}
                          />
                        </Popconfirm>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
};

const OutlinedButton = ({ onClick }: { onClick: () => void }) => (
  <Button icon={<EditOutlined />} onClick={onClick}>编辑</Button>
);

export default WorkflowsPage;
