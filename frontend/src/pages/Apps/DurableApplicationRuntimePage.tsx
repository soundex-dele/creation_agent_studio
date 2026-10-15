import { useEffect, useRef, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Input,
  Progress,
  Space,
  Spin,
  Tag,
  Typography,
  message,
} from 'antd';
import applicationModules from 'virtual:application-packages';
import { useParams, useSearchParams } from 'react-router-dom';

import {
  ApplicationRuntimeProvider,
  useApplicationRuntime,
} from '@/components/Applications/ApplicationRuntimeContext';
import { useRunStream } from '@/features/run-stream';
import { resolveApplicationPresentation } from '@/lib/applicationPresentation';
import { createIdempotencyKey } from '@/lib/idempotencyKey';
import {
  loadApplicationRuntime,
  type ApplicationRuntimeDescriptor,
  type RunResource,
} from '@/services/applicationRuntime';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import './DurableApplicationRuntimePage.css';
import RunArtifacts from '@/components/Applications/RunArtifacts';


function RuntimeConsole({ descriptor, showApplicationHeader }: {
  descriptor: ApplicationRuntimeDescriptor;
  showApplicationHeader: boolean;
}) {
  const runtime = useApplicationRuntime();
  const [inputText, setInputText] = useState('{}');
  const [run, setRun] = useState<RunResource | null>(null);
  const [starting, setStarting] = useState(false);
  const pendingRequest = useRef<{ fingerprint: string; key: string }>();
  const projection = useRunStream({
    organizationId: descriptor.organization_id,
    runId: run?.id ?? null,
  });
  const progress = projection.state.progress;
  const TaskView = applicationModules.find(module => module.rendererKey === descriptor.definition.renderer_key)?.taskView;
  const current = Number(progress?.current ?? 0);
  const total = Number(progress?.total ?? 0);
  const percent = total > 0 ? Math.min(100, Math.round((current / total) * 100)) : 0;

  const start = async (providedInput?: Record<string, unknown>) => {
    let input: Record<string, unknown>;
    if (providedInput) {
      input = providedInput;
    } else {
      try {
        const parsed = JSON.parse(inputText);
        if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
          throw new Error('输入必须是 JSON 对象');
        }
        input = parsed;
      } catch (error) {
        message.error(error instanceof Error ? error.message : '无效 JSON');
        return;
      }
    }
    setStarting(true);
    try {
      const fingerprint = JSON.stringify([descriptor.organization_id, descriptor.application_id, input]);
      if (pendingRequest.current?.fingerprint !== fingerprint) {
        pendingRequest.current = { fingerprint, key: createIdempotencyKey('application') };
      }
      setRun(await runtime.startRun(input, pendingRequest.current.key));
      pendingRequest.current = undefined;
    } catch (error) {
      message.error(error instanceof Error ? error.message : '启动失败');
    } finally {
      setStarting(false);
    }
  };

  const cancel = async () => {
    if (!run) return;
    await runtime.sendCommand(run.id, {
      type: 'cancel',
      idempotency_key: createIdempotencyKey('application-command'),
      payload: { reason: 'user_requested' },
    });
  };

  if (TaskView) return <TaskView descriptor={descriptor} showApplicationHeader={showApplicationHeader}
    run={run} starting={starting} projection={projection} total={total} percent={percent} start={start} cancel={cancel} />;
  return (
    <div className="runtime-console">
      {showApplicationHeader && (
        <div>
          <Typography.Title level={2} style={{ margin: '12px 0 20px' }}>
            {descriptor.name}
          </Typography.Title>
        </div>
      )}
      <Card>
        <Typography.Paragraph type="secondary">
          Revision {descriptor.revision_no} ·{' '}
          {String(descriptor.definition.executor_key ?? '')}
        </Typography.Paragraph>
        <Input.TextArea
          value={inputText}
          onChange={(event) => setInputText(event.target.value)}
          autoSize={{ minRows: 7, maxRows: 18 }}
          spellCheck={false}
        />
        <Space style={{ marginTop: 12 }}>
          <Button type="primary" loading={starting} onClick={() => start()}>启动 Run</Button>
          <Button danger disabled={!run || ['succeeded', 'failed', 'cancelled'].includes(projection.state.status ?? '')}
            onClick={cancel}>取消</Button>
          {run && <Tag color={projection.connected ? 'processing' : 'default'}>
            {projection.state.status ?? run.status}
          </Tag>}
        </Space>
      </Card>
      {projection.error && <Alert type="warning" showIcon message="事件流正在重连"
        description={projection.error.message} />}
      {run && <Card title={`Run ${run.id}`}>
        {total > 0 && <Progress percent={percent} status={(projection.state.status ?? run?.status) === 'failed' ? 'exception' : undefined} />}
        <Typography.Paragraph style={{ whiteSpace: 'pre-wrap' }}>
          {projection.state.output || '等待输出…'}
        </Typography.Paragraph>
      </Card>}
      {run && <RunArtifacts key={`${descriptor.organization_id}:${run.id}`}
        organizationId={descriptor.organization_id} runId={run.id}
        active={!['succeeded', 'failed', 'cancelled'].includes(projection.state.status ?? run.status)} />}
    </div>
  );
}


export default function DurableApplicationRuntimePage() {
  const { applicationId } = useParams<{ applicationId: string }>();
  const [searchParams] = useSearchParams();
  const { showApplicationHeader } = resolveApplicationPresentation(searchParams);
  const organizationId = useOrganizationStore((state) => state.currentOrganizationId);
  const [descriptor, setDescriptor] = useState<ApplicationRuntimeDescriptor | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setDescriptor(null);
    setError(null);
    if (!organizationId || !applicationId) {
      setError('请选择组织并提供 Application ID');
      return;
    }
    loadApplicationRuntime(organizationId, applicationId)
      .then(setDescriptor)
      .catch((reason) => setError(reason instanceof Error ? reason.message : '加载失败'));
  }, [applicationId, organizationId]);

  if (error) return <Alert type="error" showIcon message="无法加载 Application" description={error} />;
  if (!descriptor) return <div style={{ display: 'grid', placeItems: 'center', minHeight: 320 }}><Spin /></div>;
  return (
    <ApplicationRuntimeProvider
      organizationId={descriptor.organization_id}
      applicationId={descriptor.application_id}
    >
      <RuntimeConsole
        descriptor={descriptor}
        showApplicationHeader={showApplicationHeader}
      />
    </ApplicationRuntimeProvider>
  );
}
