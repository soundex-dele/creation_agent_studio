import { useEffect, useState } from 'react';
import {
  Alert, Button, Card, Empty, Progress, Spin, Typography, message,
} from 'antd';
import {
  ArrowLeftOutlined, CheckOutlined, ClockCircleOutlined, CloseCircleOutlined,
  ExportOutlined, FileTextOutlined, FolderOpenOutlined, LoadingOutlined,
  MinusOutlined, PartitionOutlined, ReloadOutlined, StopOutlined,
} from '@ant-design/icons';
import { useNavigate, useParams } from 'react-router-dom';

import { useRunStream } from '@/features/run-stream';
import { createIdempotencyKey } from '@/lib/idempotencyKey';
import { api } from '@/services/api';
import type { RunResource } from '@/services/applicationRuntime';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import { tenantApiRoot } from '@/services/tenantContext';
import './WorkflowRunnerPage.css';

const terminal = ['succeeded', 'failed', 'cancelled'];

const runLabels: Record<string, string> = {
  queued: '排队中', running: '执行中', waiting_input: '等待输入',
  waiting_children: '执行中', cancelling: '正在取消', succeeded: '执行完成',
  failed: '执行失败', cancelled: '已取消',
};

function StatusIcon({ status }: { status: string }) {
  if (status === 'succeeded') return <CheckOutlined aria-hidden />;
  if (status === 'failed') return <CloseCircleOutlined aria-hidden />;
  if (status === 'running' || status === 'waiting_children') return <LoadingOutlined aria-hidden />;
  if (status === 'cancelled' || status === 'skipped') return <MinusOutlined aria-hidden />;
  return <ClockCircleOutlined aria-hidden />;
}

function stepStatus(eventType: unknown, runStatus: string) {
  if (eventType === 'workflow.step.completed') return { status: 'succeeded', label: '已完成' };
  if (eventType === 'workflow.step.failed') return { status: 'failed', label: '执行异常' };
  if (eventType === 'workflow.step.skipped') return { status: 'skipped', label: '已跳过' };
  if (eventType === 'workflow.step.started') {
    if (terminal.includes(runStatus)) return { status: 'cancelled', label: '已结束' };
    return { status: 'running', label: runStatus === 'waiting_input' ? '等待输入' : '执行中' };
  }
  return { status: 'queued', label: terminal.includes(runStatus) ? '未执行' : '待执行' };
}

type WorkflowRunResource = RunResource & {
  workflow_conversations?: Record<string, string>;
};

const WorkflowRunnerPage = () => {
  const { runId } = useParams<{ runId: string }>();
  const navigate = useNavigate();
  const organizationId = useOrganizationStore((state) => state.currentOrganizationId);
  const [run, setRun] = useState<WorkflowRunResource | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [openingWorkspace, setOpeningWorkspace] = useState(false);
  const [retryingStep, setRetryingStep] = useState<string | null>(null);
  const projection = useRunStream({
    organizationId: organizationId || '',
    runId: runId || null,
    enabled: Boolean(organizationId && runId),
  });

  useEffect(() => {
    if (!organizationId || !runId) return;
    let disposed = false;
    setRun(null);
    setError(null);
    setCancelling(false);
    api.get<WorkflowRunResource>(`${tenantApiRoot(organizationId)}/runs/${runId}`)
      .then((result) => { if (!disposed) setRun(result); })
      .catch((reason: any) => {
        if (!disposed) setError(reason?.response?.data?.detail || '工作流执行记录加载失败');
      });
    return () => { disposed = true; };
  }, [organizationId, runId]);

  const cancel = async () => {
    if (!organizationId || !runId) return;
    setCancelling(true);
    try {
      await api.post(`${tenantApiRoot(organizationId)}/runs/${runId}/commands`, {
        type: 'cancel',
        idempotency_key: createIdempotencyKey('workflow-command'),
        payload: { reason: 'user_requested' },
      });
    } catch (reason: any) {
      setCancelling(false);
      message.error(reason?.response?.data?.detail || '取消工作流失败');
    }
  };

  const openWorkspace = async () => {
    if (!organizationId || !runId || openingWorkspace) return;
    setOpeningWorkspace(true);
    try {
      await api.post(
        `${tenantApiRoot(organizationId)}/runs/${runId}/open-workspace`,
        {},
      );
    } catch (reason: any) {
      message.error(reason?.response?.data?.detail || '无法打开当前工作流目录');
    } finally {
      setOpeningWorkspace(false);
    }
  };

  const retryStep = async (stepKey: string) => {
    if (!runId || !run?.source_id) return;
    setRetryingStep(stepKey);
    try {
      const nextRun = await api.post<{ id: string }>(
        `/workflows/${run.source_id}/retry-step/`,
        { run_id: runId, step_key: stepKey },
        { headers: { 'Idempotency-Key': createIdempotencyKey('workflow-retry') } },
      );
      navigate(`/runs/${nextRun.id}`);
    } catch (reason: any) {
      message.error(reason?.response?.data?.detail || '失败节点重跑失败');
    } finally {
      setRetryingStep(null);
    }
  };

  if (error) return (
    <div className="workflow-execution workflow-execution-loading">
      <Alert type="error" showIcon message={error} action={
        <Button onClick={() => navigate('/workflows')}>返回工作流</Button>
      } />
    </div>
  );
  if (!run) return (
    <div className="workflow-execution workflow-execution-loading" role="status">
      <Spin size="large" />
      <p>正在加载执行记录…</p>
    </div>
  );

  const definition = run.definition_snapshot as {
    workflow_name?: string;
    workflow_steps?: Array<{
      id: string;
      key: string;
      name: string;
      depends_on?: string[];
      conversation_id?: string;
      content?: { kind?: string };
    }>;
  };
  const steps = definition.workflow_steps || [];
  const progress = projection.state.progress;
  const inferredCurrent = steps.filter((step) => {
    const eventType = projection.state.tools[`workflow:${step.key}`]?.event_type;
    return eventType === 'workflow.step.completed' || eventType === 'workflow.step.skipped';
  }).length;
  const current = Math.max(Number(progress?.current ?? 0), inferredCurrent);
  const total = Number(progress?.total ?? steps.length);
  const percent = total > 0 ? Math.min(100, Math.round((current / total) * 100)) : 0;
  const status = projection.state.status || run.status;
  const isTerminal = terminal.includes(status);
  const activeSteps = steps.filter((step) =>
    stepStatus(projection.state.tools[`workflow:${step.key}`]?.event_type, status).status === 'running',
  );
  const summary = projection.state.output || (Object.keys(run.output_summary || {}).length
    ? JSON.stringify(run.output_summary, null, 2) : '');
  const statusDescription = status === 'succeeded' ? '本次执行已完成，可以查看各节点的执行结果。'
    : status === 'failed' ? '执行遇到异常，请查看节点错误信息后重跑。'
      : status === 'cancelled' ? '本次执行已取消，已产生的输出仍可查看。'
        : status === 'waiting_input' ? '工作流正在等待输入，请打开对应节点的对话继续。'
          : status === 'cancelling' ? '正在停止执行，请稍候。'
            : activeSteps.length ? `${activeSteps.length} 个节点正在执行，输出将实时更新。`
              : '工作流准备就绪，等待节点开始执行。';

  return (
    <div className="workflow-execution">
      <nav className="workflow-execution-nav" aria-label="工作流导航">
        <Button type="text" icon={<ArrowLeftOutlined aria-hidden />} onClick={() => navigate('/workflows')}>
          返回工作流
        </Button>
        <span className="workflow-execution-nav-divider" aria-hidden>/</span>
        <span>执行详情</span>
        <span className={`workflow-execution-connection ${projection.connected ? 'is-connected' : ''}`}>
          <span aria-hidden />
          {isTerminal ? '执行已结束' : projection.connected ? '实时同步中' : projection.error ? '正在重新连接' : '正在连接'}
        </span>
      </nav>

      <section className="workflow-execution-overview" aria-labelledby="execution-title">
        <header className="workflow-execution-heading">
          <div className="workflow-execution-identity">
            <span className="workflow-execution-symbol"><PartitionOutlined aria-hidden /></span>
            <div>
              <div className="workflow-execution-eyebrow">工作流执行</div>
              <h1 id="execution-title">{definition.workflow_name || '未命名工作流'}</h1>
            </div>
          </div>
          <div className="workflow-execution-actions">
            <Button icon={<FolderOpenOutlined aria-hidden />} loading={openingWorkspace}
              className="workflow-execution-workspace" onClick={() => void openWorkspace()}>
              打开目录
            </Button>
            <Button danger icon={<StopOutlined aria-hidden />}
              loading={cancelling && !isTerminal}
              disabled={isTerminal || status === 'cancelling'} onClick={cancel}>
              取消执行
            </Button>
          </div>
        </header>
        <div className="workflow-execution-overview-body">
          <div className="workflow-execution-status-copy">
            <span className={`workflow-execution-badge is-${status}`} role="status">
              <StatusIcon status={status} />{runLabels[status] || status}
            </span>
            <p>{statusDescription}</p>
          </div>
          <div className="workflow-execution-progress">
            <div className="workflow-execution-progress-label">
              <span>节点进度 <strong>{Math.min(current, total)}<small> / {total}</small></strong></span>
              <span className="workflow-execution-percentage">{percent}<small>%</small></span>
            </div>
            <Progress percent={percent} showInfo={false}
              status={status === 'failed' ? 'exception' : status === 'succeeded' ? 'success' : 'normal'}
              strokeColor={status === 'failed' ? 'var(--color-error)'
                : status === 'succeeded' ? 'var(--color-success)' : 'var(--color-primary)'}
              trailColor="var(--color-bg-elevated)"
              aria-label={`节点进度：已处理 ${Math.min(current, total)} 个，共 ${total} 个`} />
            <small>进度包含已完成和已跳过的节点</small>
          </div>
        </div>
      </section>

      {projection.error && !isTerminal && <Alert type="warning" showIcon message="实时连接暂时中断，正在重连"
        description={projection.error.message} />}

      <div className="workflow-execution-grid">
        <section className="workflow-execution-timeline" aria-labelledby="execution-steps-title">
          <div className="workflow-execution-section-heading">
            <div><h2 id="execution-steps-title">执行步骤</h2><span className="workflow-execution-count">{steps.length}</span></div>
            <span>按工作流顺序展示</span>
          </div>
          {steps.length === 0 ? <div className="workflow-execution-panel"><Empty description="该执行记录没有步骤快照" /></div> : (
            <ol className="workflow-execution-steps">
              {steps.map((step, index) => {
                const stepState = projection.state.tools[`workflow:${step.key}`] || {};
                const presentation = stepStatus(stepState.event_type, status);
                const conversationId = String(stepState.conversation_id || step.conversation_id
                  || run.workflow_conversations?.[step.key] || '');
                const completedOutput = stepState.output as Record<string, unknown> | undefined;
                const output = String(stepState.stream_output || completedOutput?.result || '');
                return (
                  <li key={step.key} className={`workflow-execution-step is-${presentation.status}`}>
                    <span className="workflow-execution-step-marker" aria-hidden>
                      {presentation.status === 'queued' ? String(index + 1).padStart(2, '0')
                        : <StatusIcon status={presentation.status} />}
                    </span>
                    <article className="workflow-execution-step-card">
                      <header className="workflow-execution-step-heading">
                        <div className="workflow-execution-step-title">
                          <span className="workflow-execution-step-caption">步骤 {String(index + 1).padStart(2, '0')} · {step.content?.kind === 'chat' ? '智能体对话' : '应用任务'}</span>
                          <h3>{step.name || step.key}</h3>
                        </div>
                        <span className={`workflow-execution-badge is-${presentation.status}`}>
                          <StatusIcon status={presentation.status} />{presentation.label}
                        </span>
                      </header>
                      <div className="workflow-execution-dependencies">
                        <PartitionOutlined aria-hidden />
                        <span>{step.depends_on?.length
                          ? `依赖：${step.depends_on.map((key) => steps.find((item) => item.key === key)?.name || key).join('、')}`
                          : '无前置依赖，可独立执行'}</span>
                      </div>
                      {output ? (
                        <div className="workflow-execution-output">
                          <div className="workflow-execution-output-label"><FileTextOutlined aria-hidden />节点输出</div>
                          <Typography.Paragraph className="workflow-execution-output-text" tabIndex={0}
                            role="region" aria-label={`${step.name || step.key}的节点输出`}>
                            {output}
                          </Typography.Paragraph>
                        </div>
                      ) : presentation.status === 'running' && (
                        <div className="workflow-execution-output-pending"><LoadingOutlined aria-hidden />正在处理，输出将在这里显示…</div>
                      )}
                      {(stepState.event_type === 'workflow.step.failed' || step.content?.kind === 'chat') && (
                        <footer className="workflow-execution-step-actions">
                          {stepState.event_type === 'workflow.step.failed' && <Button icon={<ReloadOutlined aria-hidden />}
                            loading={retryingStep === step.key} onClick={() => void retryStep(step.key)}>
                            重跑此节点
                          </Button>}
                          {step.content?.kind === 'chat' && <Button icon={<ExportOutlined aria-hidden />}
                            disabled={!conversationId} title={conversationId ? '在新窗口查看对话' : '步骤开始后可查看对话'}
                            onClick={() => window.open(`/chat?conversation=${encodeURIComponent(conversationId)}`, '_blank', 'noopener,noreferrer')}>
                            查看对话
                          </Button>}
                        </footer>
                      )}
                    </article>
                  </li>
                );
              })}
            </ol>
          )}
        </section>

        <aside className="workflow-execution-sidebar" aria-label="执行结果与详情">
          <Card className="workflow-execution-panel" title={<h2><FileTextOutlined aria-hidden />工作流汇总</h2>}>
            {summary ? <Typography.Paragraph className="workflow-execution-summary" copyable>{summary}</Typography.Paragraph>
              : <div className="workflow-execution-empty">
                <span className="workflow-execution-empty-icon"><FileTextOutlined aria-hidden /></span>
                <strong>{isTerminal ? '暂无汇总内容' : '等待汇总结果'}</strong>
                <p>{isTerminal ? '可在各节点中查看执行输出。' : '各节点的实时输出显示在左侧，汇总结果将在这里呈现。'}</p>
              </div>}
          </Card>
          <details className="workflow-execution-details">
            <summary>运行详情<span>编号与执行环境</span></summary>
            <dl>
              <div><dt>运行编号</dt><dd><Typography.Text copyable>{run.id}</Typography.Text></dd></div>
              <div><dt>执行器</dt><dd>{[run.executor_kind, run.executor_key].filter(Boolean).join(' / ') || '—'}</dd></div>
              {run.created_at && <div><dt>创建时间</dt><dd>{new Date(run.created_at).toLocaleString('zh-CN', { hour12: false })}</dd></div>}
            </dl>
          </details>
        </aside>
      </div>
    </div>
  );
};

export default WorkflowRunnerPage;
