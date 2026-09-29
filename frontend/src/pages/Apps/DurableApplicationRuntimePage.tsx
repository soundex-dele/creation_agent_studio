import { useEffect, useState } from 'react';
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
import { Image, Layers } from 'lucide-react';
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
import HtmlToPngInput from './HtmlToPngInput';
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
  const projection = useRunStream({
    organizationId: descriptor.organization_id,
    runId: run?.id ?? null,
  });
  const progress = projection.state.progress;
  const isHtmlToPng = descriptor.definition.renderer_key === 'html-to-png';
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
      setRun(await runtime.startRun(input, createIdempotencyKey('application')));
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

  return (
    <div className={isHtmlToPng ? "conversion-page app-scroll-page" : "runtime-console"}>
      {isHtmlToPng ? showApplicationHeader && <header className="conversion-header"><span className="conversion-app-icon"><Image size={28} aria-hidden="true" /></span><div><span className="conversion-eyebrow">让排版成为可分享的图片</span><h1>{descriptor.name}</h1><p>选择目录，设置画面，一次完成批量转换。</p></div><span className="conversion-format">HTML <span aria-hidden="true">→</span> PNG</span></header> : showApplicationHeader && (
        <div>
          <Typography.Title level={2} style={{ margin: '12px 0 20px' }}>
            {descriptor.name}
          </Typography.Title>
        </div>
      )}
      {isHtmlToPng ? <HtmlToPngInput loading={starting} onStart={start} /> : <Card>
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
      </Card>}
      {projection.error && <Alert type="warning" showIcon message="事件流正在重连"
        description={projection.error.message} />}
      {isHtmlToPng && !run && <section className="conversion-result-empty"><Layers size={26} aria-hidden="true" /><div><h2>转换结果</h2><p>开始转换后，在这里查看进度、预览图片并下载文件。</p></div></section>}
      {run && <Card className={isHtmlToPng ? "conversion-result" : undefined} title={isHtmlToPng ? "转换进度" : `Run ${run.id}`} extra={isHtmlToPng && <Tag>{({ queued: "等待转换", running: "正在转换", cancelling: "正在取消", cancelled: "已取消", failed: "转换失败", succeeded: "转换完成" } as Record<string, string>)[projection.state.status ?? run.status] || "处理中"}</Tag>}>
        {total > 0 && <Progress percent={percent} status={(projection.state.status ?? run?.status) === 'failed' ? 'exception' : undefined} />}
        <Typography.Paragraph style={{ whiteSpace: 'pre-wrap' }}>
          {projection.state.output || (isHtmlToPng ? '转换消息将在这里显示。' : '等待输出…')}
        </Typography.Paragraph>
        {isHtmlToPng && <Button danger disabled={['succeeded', 'failed', 'cancelled', 'cancelling'].includes(projection.state.status ?? run.status)} onClick={cancel}>取消当前转换</Button>}
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
