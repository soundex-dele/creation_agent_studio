import { useCallback, useEffect, useMemo, useState } from 'react';
import { Alert, Button, Card, Empty, Input, List, Space, Spin, Steps, Tag, Typography, message } from 'antd';
import { ArrowLeftOutlined, CheckOutlined, ReloadOutlined, SendOutlined } from '@ant-design/icons';
import { useNavigate, useParams } from 'react-router-dom';

import { useRunStream } from '@/features/run-stream';
import { api } from '@/services/api';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import type { SupervisorPlan } from '@/types/delegate';
import './Delegates.css';

interface RunResource { id: string; status: string; version: number; pending_input_request_id?: string | null; output_summary?: Record<string, any> }
interface ConversationDetail { id: number; title: string; messages: Array<{ id: number; role: string; content: string }>; active_run?: RunResource | null; latest_run?: RunResource | null }
interface ChildRun { id: string; node_key: string; status: string; definition_snapshot: Record<string, any>; error_message?: string }
interface Artifact { id: string; run_id: string; kind: string; mime_type: string; size: number; metadata: Record<string, any> }

const DelegateTaskPage = () => {
  const { conversationId } = useParams<{ id: string; conversationId: string }>();
  const navigate = useNavigate();
  const organizationId = useOrganizationStore((state) => state.currentOrganizationId) || '';
  const [conversation, setConversation] = useState<ConversationDetail | null>(null);
  const [run, setRun] = useState<RunResource | null>(null);
  const [children, setChildren] = useState<ChildRun[]>([]);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [goal, setGoal] = useState('');
  const [feedback, setFeedback] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const projection = useRunStream({ organizationId, runId: run?.id || null });

  const refreshConversation = useCallback(async () => {
    if (!conversationId) return;
    const value = await api.get<ConversationDetail>(`/conversations/${conversationId}/`);
    setConversation(value);
    setRun(value.active_run || value.latest_run || null);
    if (!value.active_run && !value.latest_run) {
      setChildren([]);
      setArtifacts([]);
    }
  }, [conversationId]);

  const refreshRun = useCallback(async () => {
    if (!run?.id || !organizationId) return;
    const [nextRun, childRuns, artifactPage] = await Promise.all([
      api.get<RunResource>(`/organizations/${organizationId}/runs/${run.id}`),
      api.get<ChildRun[]>(`/organizations/${organizationId}/runs/${run.id}/children`),
      api.get<any>(`/organizations/${organizationId}/runs/${run.id}/artifacts`, { include_descendants: true }),
    ]);
    setRun(nextRun);
    setChildren(childRuns);
    setArtifacts(Array.isArray(artifactPage) ? artifactPage : artifactPage.results || []);
    if (['succeeded', 'failed', 'cancelled'].includes(nextRun.status)) void refreshConversation();
  }, [organizationId, refreshConversation, run?.id]);

  useEffect(() => { void refreshConversation(); }, [refreshConversation]);
  useEffect(() => {
    if (run?.id) void refreshRun();
  }, [projection.state.nextSequence, refreshRun, run?.id]);

  const plan = useMemo(() => {
    const pending = projection.state.pendingInput as any;
    if (pending?.plan) return pending.plan as SupervisorPlan;
    const value = projection.state.tools['supervisor:plan'] as any;
    return value?.tasks ? value as SupervisorPlan : null;
  }, [projection.state.pendingInput, projection.state.tools]);

  const send = async () => {
    if (!conversationId || !goal.trim()) return;
    setSubmitting(true);
    try {
      const next = await api.post<RunResource>(`/conversations/${conversationId}/send_message/`, {
        content: goal.trim(),
      }, { headers: { 'Idempotency-Key': crypto.randomUUID() } });
      setRun(next); setGoal(''); await refreshConversation();
    } catch (error: any) { message.error(error?.response?.data?.detail || '任务提交失败'); }
    finally { setSubmitting(false); }
  };

  const command = async (type: 'approve_plan' | 'revise_plan') => {
    if (!run?.pending_input_request_id || !plan) return;
    setSubmitting(true);
    try {
      await api.post(`/organizations/${organizationId}/runs/${run.id}/commands`, {
        type,
        idempotency_key: crypto.randomUUID(),
        input_request_id: run.pending_input_request_id,
        expected_run_version: run.version,
        payload: { plan_version: plan.plan_version, feedback },
      });
      setFeedback(''); await refreshRun();
    } catch (error: any) { message.error(error?.response?.data?.detail || '计划操作失败'); }
    finally { setSubmitting(false); }
  };

  const childCommand = async (type: 'answer' | 'grant_permission' | 'deny_permission') => {
    if (!run?.pending_input_request_id) return;
    setSubmitting(true);
    try {
      await api.post(`/organizations/${organizationId}/runs/${run.id}/commands`, {
        type,
        idempotency_key: crypto.randomUUID(),
        input_request_id: run.pending_input_request_id,
        expected_run_version: run.version,
        payload: type === 'answer' ? { text: feedback } : {},
      });
      setFeedback(''); await refreshRun();
    } catch (error: any) { message.error(error?.response?.data?.detail || '提交失败'); }
    finally { setSubmitting(false); }
  };

  const openArtifact = async (artifact: Artifact) => {
    const access = await api.get<{ url: string }>(
      `/organizations/${organizationId}/runs/${artifact.run_id}/artifacts/${artifact.id}/access`,
    );
    window.open(access.url, '_blank', 'noopener,noreferrer');
  };

  if (!conversation) return <Spin size="large" />;
  return (
    <div className="delegate-task-page">
      <section className="delegate-chat-pane">
        <header>
          <Space>
            <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate('/delegates')} aria-label="返回分身实例" />
            <h2>{conversation.title || `分身实例 #${conversation.id}`}</h2>
          </Space>
          <Tag>{projection.connected ? '实时连接' : '任务会话'}</Tag>
        </header>
        <div className="delegate-message-list">
          {conversation.messages.length === 0 ? <Empty description="告诉分身你想完成什么" /> : conversation.messages.map((item) => (
            <div className={`delegate-message delegate-message--${item.role}`} key={item.id}>
              <strong>{item.role === 'user' ? '你' : 'AI 分身'}</strong>
              <Typography.Paragraph>{item.content}</Typography.Paragraph>
            </div>
          ))}
          {projection.state.output && run && !['succeeded', 'failed', 'cancelled'].includes(run.status) && (
            <div className="delegate-message delegate-message--assistant"><strong>AI 分身</strong><Typography.Paragraph>{projection.state.output}</Typography.Paragraph></div>
          )}
        </div>
        <div className="delegate-composer">
          <Input.TextArea
            value={goal}
            autoSize={{ minRows: 1, maxRows: 6 }}
            size="large"
            disabled={Boolean(run && !['succeeded', 'failed', 'cancelled'].includes(run.status))}
            placeholder="描述目标、背景和期望交付…"
            onChange={(event) => setGoal(event.target.value)}
          />
          <Button
            type="primary"
            icon={<SendOutlined />}
            loading={submitting}
            disabled={!goal.trim() || Boolean(run && !['succeeded', 'failed', 'cancelled'].includes(run.status))}
            onClick={() => void send()}
          >发送</Button>
        </div>
      </section>
      <aside className="delegate-board-pane">
        <div className="delegate-board-heading"><h2>执行看板</h2><Button icon={<ReloadOutlined />} onClick={() => void refreshRun()} /></div>
        {!run ? <Empty description="提交任务后将在这里生成执行计划" /> : (
          <>
            <Card size="small" title={`状态 · ${run.status}`}>
              {projection.error && <Alert type="warning" message={projection.error.message} />}
              {plan ? <><h3>{plan.objective}</h3><p>计划版本 v{plan.plan_version}</p><Steps direction="vertical" size="small" items={plan.tasks.map((task) => {
                const child = children.find((item) => item.definition_snapshot?.supervisor_task_key === task.key && item.definition_snapshot?.supervisor_plan_version === plan.plan_version);
                return { title: task.title, description: `${task.target_type} #${task.target_id} · ${task.expected_output}`, status: child?.status === 'succeeded' ? 'finish' : child?.status === 'failed' ? 'error' : child ? 'process' : 'wait' };
              })} /></> : <Spin />}
            </Card>
            {run.status === 'waiting_input' && run.pending_input_request_id && plan
              && projection.state.pendingInput?.input_kind === 'plan_approval' && (
              <Card size="small" title="计划审批">
                <Input.TextArea value={feedback} rows={3} placeholder="如需调整，请说明修改意见" onChange={(event) => setFeedback(event.target.value)} />
                <Space style={{ marginTop: 12 }}><Button type="primary" icon={<CheckOutlined />} loading={submitting} onClick={() => void command('approve_plan')}>批准执行</Button><Button disabled={!feedback.trim()} loading={submitting} onClick={() => void command('revise_plan')}>要求修改</Button></Space>
              </Card>
            )}
            {run.status === 'waiting_input' && run.pending_input_request_id
              && projection.state.pendingInput?.input_kind !== 'plan_approval' && (
              <Card size="small" title="子任务需要你的决定">
                <Typography.Paragraph>{String(
                  projection.state.pendingInput?.question
                  || projection.state.pendingInput?.prompt
                  || '执行者需要补充信息后才能继续。'
                )}</Typography.Paragraph>
                {projection.state.pendingInput?.input_kind === 'permission' ? (
                  <Space><Button type="primary" loading={submitting} onClick={() => void childCommand('grant_permission')}>允许</Button><Button danger loading={submitting} onClick={() => void childCommand('deny_permission')}>拒绝</Button></Space>
                ) : <><Input.TextArea rows={3} value={feedback} onChange={(event) => setFeedback(event.target.value)} /><Button type="primary" style={{ marginTop: 12 }} disabled={!feedback.trim()} loading={submitting} onClick={() => void childCommand('answer')}>提交回答</Button></>}
              </Card>
            )}
            <Card size="small" title="子任务">
              <List dataSource={children} locale={{ emptyText: '尚未执行子任务' }} renderItem={(child) => <List.Item><List.Item.Meta title={child.definition_snapshot?.supervisor_task_title || child.node_key} description={child.error_message || `${child.definition_snapshot?.supervisor_target_type || ''} · ${child.status}`} /></List.Item>} />
            </Card>
            <Card size="small" title={`产物 (${artifacts.length})`}>
              <List dataSource={artifacts} locale={{ emptyText: '暂无产物' }} renderItem={(artifact) => <List.Item actions={[<Button key="open" type="link" onClick={() => void openArtifact(artifact)}>打开</Button>]}><List.Item.Meta title={String(artifact.metadata?.filename || artifact.kind)} description={`${artifact.mime_type} · ${artifact.size} bytes`} /></List.Item>} />
            </Card>
          </>
        )}
      </aside>
    </div>
  );
};

export default DelegateTaskPage;
