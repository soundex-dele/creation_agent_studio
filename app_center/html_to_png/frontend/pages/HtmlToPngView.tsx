import { Alert, Button, Card, Progress, Tag, Typography } from 'antd';
import { Image, Layers } from 'lucide-react';
import type { ApplicationTaskViewProps } from '@platform/applications';
import RunArtifacts from '@platform/components/Applications/RunArtifacts';
import HtmlToPngInput from './HtmlToPngInput';
import './HtmlToPngView.css';

export default function HtmlToPngView({ descriptor, showApplicationHeader, run, starting, projection, total, percent, start, cancel }: ApplicationTaskViewProps) {
  return (
    <div className="conversion-page app-scroll-page">
      {showApplicationHeader && <header className="conversion-header"><span className="conversion-app-icon"><Image size={28} aria-hidden="true" /></span><div><span className="conversion-eyebrow">让排版成为可分享的图片</span><h1>{descriptor.name}</h1><p>选择目录，设置画面，一次完成批量转换。</p></div><span className="conversion-format">HTML <span aria-hidden="true">→</span> PNG</span></header>}
      <HtmlToPngInput loading={starting} onStart={start} />
      {projection.error && <Alert type="warning" showIcon message="事件流正在重连"
        description={projection.error.message} />}
      {!run && <section className="conversion-result-empty"><Layers size={26} aria-hidden="true" /><div><h2>转换结果</h2><p>开始转换后，在这里查看进度、预览图片并下载文件。</p></div></section>}
      {run && <Card className="conversion-result" title="转换进度" extra={<Tag>{({ queued: "等待转换", running: "正在转换", cancelling: "正在取消", cancelled: "已取消", failed: "转换失败", succeeded: "转换完成" } as Record<string, string>)[projection.state.status ?? run.status] || "处理中"}</Tag>}>
        {total > 0 && <Progress percent={percent} status={(projection.state.status ?? run?.status) === 'failed' ? 'exception' : undefined} />}
        <Typography.Paragraph style={{ whiteSpace: 'pre-wrap' }}>
          {projection.state.output || '转换消息将在这里显示。'}
        </Typography.Paragraph>
        {<Button danger disabled={['succeeded', 'failed', 'cancelled', 'cancelling'].includes(projection.state.status ?? run.status)} onClick={cancel}>取消当前转换</Button>}
      </Card>}
      {run && <RunArtifacts key={`${descriptor.organization_id}:${run.id}`}
        organizationId={descriptor.organization_id} runId={run.id}
        active={!['succeeded', 'failed', 'cancelled'].includes(projection.state.status ?? run.status)} />}
    </div>
  );
}
