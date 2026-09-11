import { useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Empty,
  Input,
  List,
  Progress,
  Space,
  Spin,
  Tag,
  Typography,
  message,
} from 'antd';
import { useParams } from 'react-router-dom';

import {
  ApplicationRuntimeProvider,
  useApplicationRuntime,
} from '@/components/Applications/ApplicationRuntimeContext';
import { useRunStream } from '@/hooks/useRunStream';
import {
  loadApplicationRuntime,
  type V2ApplicationRuntimeDescriptor,
  type V2RunArtifact,
  type V2RunResource,
} from '@/services/applicationRuntimeV2';
import { useOrganizationStore } from '@/stores/useOrganizationStore';


function RuntimeConsole({ descriptor }: { descriptor: V2ApplicationRuntimeDescriptor }) {
  const runtime = useApplicationRuntime();
  const [inputText, setInputText] = useState('{}');
  const [run, setRun] = useState<V2RunResource | null>(null);
  const [starting, setStarting] = useState(false);
  const [artifacts, setArtifacts] = useState<V2RunArtifact[]>([]);
  const projection = useRunStream({
    organizationId: descriptor.organization_id,
    runId: run?.id ?? null,
  });
  const progress = projection.state.progress;
  const current = Number(progress?.current ?? 0);
  const total = Number(progress?.total ?? 0);
  const percent = total > 0 ? Math.min(100, Math.round((current / total) * 100)) : 0;

  useEffect(() => {
    if (!run || projection.state.artifactIds.length === 0) return;
    runtime.listArtifacts(run.id).then((page) => setArtifacts(page.results));
  }, [projection.state.artifactIds.length, run, runtime]);

  const start = async () => {
    let input: Record<string, unknown>;
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
    setStarting(true);
    setArtifacts([]);
    try {
      setRun(await runtime.startRun(input, crypto.randomUUID()));
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
      idempotency_key: crypto.randomUUID(),
      payload: { reason: 'user_requested' },
    });
  };

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Card title={`${descriptor.name} · Revision ${descriptor.revision_no}`}>
        <Typography.Paragraph type="secondary">
          {descriptor.description || descriptor.slug} · {descriptor.environment} ·{' '}
          {String(descriptor.definition.executor_key ?? '')}
        </Typography.Paragraph>
        <Input.TextArea
          value={inputText}
          onChange={(event) => setInputText(event.target.value)}
          autoSize={{ minRows: 7, maxRows: 18 }}
          spellCheck={false}
        />
        <Space style={{ marginTop: 12 }}>
          <Button type="primary" loading={starting} onClick={start}>启动 Run</Button>
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
        {total > 0 && <Progress percent={percent} />}
        <Typography.Paragraph style={{ whiteSpace: 'pre-wrap' }}>
          {projection.state.output || '等待输出…'}
        </Typography.Paragraph>
      </Card>}
      {run && <Card title="Artifacts">
        {artifacts.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} /> : (
          <List dataSource={artifacts} renderItem={(artifact) => (
            <List.Item actions={[<Button key="open" type="link" onClick={async () => {
              const access = await runtime.getArtifactAccess(run.id, artifact.id);
              window.open(access.url, '_blank', 'noopener,noreferrer');
            }}>打开</Button>]}> 
              <List.Item.Meta title={String(artifact.metadata.filename ?? artifact.kind)}
                description={`${artifact.mime_type} · ${artifact.size} bytes`} />
            </List.Item>
          )} />
        )}
      </Card>}
    </Space>
  );
}


export default function V2ApplicationRuntimePage() {
  const { applicationId } = useParams<{ applicationId: string }>();
  const organizationId = useOrganizationStore((state) => state.currentOrganizationId);
  const [descriptor, setDescriptor] = useState<V2ApplicationRuntimeDescriptor | null>(null);
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

  if (error) return <Alert type="error" showIcon message="无法加载 V2 Application" description={error} />;
  if (!descriptor) return <div style={{ display: 'grid', placeItems: 'center', minHeight: 320 }}><Spin /></div>;
  return (
    <ApplicationRuntimeProvider
      organizationId={descriptor.organization_id}
      applicationId={descriptor.application_id}
      environment={descriptor.environment}
    >
      <RuntimeConsole descriptor={descriptor} />
    </ApplicationRuntimeProvider>
  );
}
