import { useEffect, useState } from 'react';
import {
  Alert, Button, Card, Descriptions, List, Progress, Space, Spin, Tag, Tooltip,
  Typography, message,
} from 'antd';
import { ArrowLeftOutlined, ExportOutlined, FolderOpenOutlined } from '@ant-design/icons';
import { useNavigate, useParams } from 'react-router-dom';

import { useRunStream } from '@/features/run-stream';
import { api } from '@/services/api';
import type { RunResource } from '@/services/applicationRuntime';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import { tenantApiRoot } from '@/services/tenantContext';

const terminal = ['succeeded', 'failed', 'cancelled'];

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
  const projection = useRunStream({
    organizationId: organizationId || '',
    runId: runId || null,
    enabled: Boolean(organizationId && runId),
  });

  useEffect(() => {
    if (!organizationId || !runId) return;
    api.get<WorkflowRunResource>(`${tenantApiRoot(organizationId)}/runs/${runId}`)
      .then(setRun)
      .catch((reason: any) => setError(reason?.response?.data?.detail || 'Run 加载失败'));
  }, [organizationId, runId]);

  const cancel = async () => {
    if (!organizationId || !runId) return;
    setCancelling(true);
    try {
      await api.post(`${tenantApiRoot(organizationId)}/runs/${runId}/commands`, {
        type: 'cancel',
        idempotency_key: crypto.randomUUID(),
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

  if (error) return <Alert type="error" showIcon message={error} />;
  if (!run) return <div style={{ display: 'grid', placeItems: 'center', minHeight: 320 }}><Spin /></div>;

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
  const progress = projection.state.progress;
  const inferredCurrent = (definition.workflow_steps || []).filter((step) => {
    const eventType = projection.state.tools[`workflow:${step.key}`]?.event_type;
    return eventType === 'workflow.step.completed' || eventType === 'workflow.step.skipped';
  }).length;
  const current = Math.max(Number(progress?.current ?? 0), inferredCurrent);
  const total = Number(progress?.total ?? definition.workflow_steps?.length ?? 0);
  const percent = total > 0 ? Math.min(100, Math.round((current / total) * 100)) : 0;
  const status = projection.state.status || run.status;

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%', padding: 24 }}>
      <div>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/workflows')}>
          返回工作流
        </Button>
      </div>
      <Card
        title={definition.workflow_name || `Run ${run.id}`}
        extra={<Space>
          <Tag color={projection.connected ? 'processing' : 'default'}>{status}</Tag>
          <Tooltip title="打开目录">
            <Button
              type="text"
              shape="circle"
              icon={<FolderOpenOutlined />}
              loading={openingWorkspace}
              aria-label="打开目录"
              onClick={() => void openWorkspace()}
            />
          </Tooltip>
          <Button
            danger
            loading={cancelling && !terminal.includes(status)}
            disabled={terminal.includes(status) || status === 'cancelling'}
            onClick={cancel}
          >
            取消
          </Button>
        </Space>}
      >
        <Descriptions size="small" column={2}>
          <Descriptions.Item label="Run ID">{run.id}</Descriptions.Item>
          <Descriptions.Item label="执行器">{run.executor_kind}/{run.executor_key}</Descriptions.Item>
        </Descriptions>
        {total > 0 && <Progress percent={percent} />}
      </Card>
      {projection.error && <Alert type="warning" showIcon message="事件流正在重连"
        description={projection.error.message} />}
      <Card title="工作流汇总">
        <Typography.Paragraph style={{ whiteSpace: 'pre-wrap' }}>
          {projection.state.output || (Object.keys(run.output_summary || {}).length
            ? JSON.stringify(run.output_summary, null, 2)
            : '每个智能体的实时输出显示在对应步骤中。')}
        </Typography.Paragraph>
      </Card>
      <Card title="步骤">
        <List
          dataSource={definition.workflow_steps || []}
          locale={{ emptyText: '该 Run 没有步骤快照' }}
          renderItem={(step, index) => {
            const stepState = projection.state.tools[`workflow:${step.key}`] || {};
            const conversationId = String(
              stepState.conversation_id
              || step.conversation_id
              || run.workflow_conversations?.[step.key]
              || '',
            );
            const isChatStep = step.content?.kind === 'chat';
            return (
              <List.Item
                actions={isChatStep ? [
                  <Button
                    key="conversation"
                    size="small"
                    icon={<ExportOutlined />}
                    disabled={!conversationId}
                    title={conversationId ? '在新窗口查看对话' : '步骤开始后可查看对话'}
                    onClick={() => window.open(
                      `/chat?conversation=${encodeURIComponent(conversationId)}`,
                      '_blank',
                      'noopener,noreferrer',
                    )}
                  >
                    查看对话
                  </Button>,
                ] : undefined}
              >
                <List.Item.Meta
                  title={`${index + 1}. ${step.name}`}
                  description={(() => {
                    const eventType = stepState.event_type;
                    const stateLabel = eventType === 'workflow.step.completed' ? '已完成'
                      : eventType === 'workflow.step.started' ? '执行中'
                        : eventType === 'workflow.step.failed' ? '重试或失败'
                          : eventType === 'workflow.step.skipped' ? '条件未满足，已跳过' : '等待依赖';
                    const dependencies = step.depends_on?.length
                      ? ` · 依赖 ${step.depends_on.join(', ')}` : ' · 无依赖，可并行';
                    const completedOutput = stepState.output as Record<string, unknown> | undefined;
                    const output = String(
                      stepState.stream_output
                      || completedOutput?.result
                      || '',
                    );
                    return (
                      <div>
                        <div>{stateLabel}{dependencies}</div>
                        {output && (
                          <Typography.Paragraph
                            style={{
                              margin: '10px 0 0', padding: 12, maxHeight: 360,
                              overflow: 'auto', whiteSpace: 'pre-wrap',
                              borderRadius: 8, background: 'var(--color-bg-elevated)',
                            }}
                          >
                            {output}
                          </Typography.Paragraph>
                        )}
                      </div>
                    );
                  })()}
                />
              </List.Item>
            );
          }}
        />
      </Card>
    </Space>
  );
};

export default WorkflowRunnerPage;
