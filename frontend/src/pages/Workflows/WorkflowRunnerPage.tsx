import { useEffect, useState } from 'react';
import { Alert, Button, Card, Descriptions, List, Progress, Space, Spin, Tag, Typography } from 'antd';
import { useParams } from 'react-router-dom';

import { useRunStream } from '@/features/run-stream';
import { api } from '@/services/api';
import type { RunResource } from '@/services/applicationRuntime';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import { tenantApiRoot } from '@/services/tenantContext';

const terminal = ['succeeded', 'failed', 'cancelled'];

const WorkflowRunnerPage = () => {
  const { runId } = useParams<{ runId: string }>();
  const organizationId = useOrganizationStore((state) => state.currentOrganizationId);
  const [run, setRun] = useState<RunResource | null>(null);
  const [error, setError] = useState<string | null>(null);
  const projection = useRunStream({
    organizationId: organizationId || '',
    runId: runId || null,
    enabled: Boolean(organizationId && runId),
  });

  useEffect(() => {
    if (!organizationId || !runId) return;
    api.get<RunResource>(`${tenantApiRoot(organizationId)}/runs/${runId}`)
      .then(setRun)
      .catch((reason: any) => setError(reason?.response?.data?.detail || 'Run 加载失败'));
  }, [organizationId, runId]);

  const cancel = async () => {
    if (!organizationId || !runId) return;
    await api.post(`${tenantApiRoot(organizationId)}/runs/${runId}/commands`, {
      type: 'cancel',
      idempotency_key: crypto.randomUUID(),
      payload: { reason: 'user_requested' },
    });
  };

  if (error) return <Alert type="error" showIcon message={error} />;
  if (!run) return <div style={{ display: 'grid', placeItems: 'center', minHeight: 320 }}><Spin /></div>;

  const definition = run.definition_snapshot as {
    workflow_name?: string;
    workflow_steps?: Array<{ id: string; key: string; name: string; depends_on?: string[] }>;
  };
  const progress = projection.state.progress;
  const current = Number(progress?.current ?? 0);
  const total = Number(progress?.total ?? definition.workflow_steps?.length ?? 0);
  const percent = total > 0 ? Math.round((current / total) * 100) : 0;
  const status = projection.state.status || run.status;

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%', padding: 24 }}>
      <Card
        title={definition.workflow_name || `Run ${run.id}`}
        extra={<Space>
          <Tag color={projection.connected ? 'processing' : 'default'}>{status}</Tag>
          <Button danger disabled={terminal.includes(status)} onClick={cancel}>取消</Button>
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
      <Card title="输出">
        <Typography.Paragraph style={{ whiteSpace: 'pre-wrap' }}>
          {projection.state.output || JSON.stringify(run.output_summary || {}, null, 2) || '等待输出…'}
        </Typography.Paragraph>
      </Card>
      <Card title="步骤">
        <List
          dataSource={definition.workflow_steps || []}
          locale={{ emptyText: '该 Run 没有步骤快照' }}
          renderItem={(step, index) => (
            <List.Item>
              <List.Item.Meta
                title={`${index + 1}. ${step.name}`}
                description={(() => {
                  const eventType = projection.state.tools[`workflow:${step.key}`]?.event_type;
                  const stateLabel = eventType === 'workflow.step.completed' ? '已完成'
                    : eventType === 'workflow.step.started' ? '执行中'
                      : eventType === 'workflow.step.failed' ? '重试或失败'
                        : eventType === 'workflow.step.skipped' ? '条件未满足，已跳过' : '等待依赖';
                  const dependencies = step.depends_on?.length
                    ? ` · 依赖 ${step.depends_on.join(', ')}` : ' · 无依赖，可并行';
                  return `${stateLabel}${dependencies}`;
                })()}
              />
            </List.Item>
          )}
        />
      </Card>
    </Space>
  );
};

export default WorkflowRunnerPage;
