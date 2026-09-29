import { useEffect, useState } from 'react';
import { Alert, Button, Empty, Modal, Tag } from 'antd';
import { type DouyinClient, type DouyinTask, type Claim } from '@/services/douyinBenchmark';
import { documentError } from '@/services/documents';

const labels = { observation: '观察事实', inference: '初步推测', suggestion: '创作建议' };
export function AnalysisResult({ task, client, accountId }: { task: DouyinTask; client: DouyinClient; accountId: string }) {
  const [ref, setRef] = useState<string | null>(null);
  const segment = task.output.segments?.find((s) => s.id === ref);
  const frame = task.output.frames?.find((f) => f.id === ref);
  const work = task.sources?.find((w) => w.id === ref);
  return <section className="douyin-result">
    {task.output.visual_note && <Alert type={task.output.visual_status === 'completed' ? 'info' : 'warning'} message={task.output.visual_note} />}
    {task.output.transcript_note && <Alert type="warning" message={task.output.transcript_note} />}
    {task.output.statistics && <div className="douyin-metrics"><div><strong>{task.output.statistics.sample_count}</strong><span>本次样本</span></div><div><strong>{task.output.statistics.observed_days}</strong><span>样本跨度（天）</span></div><div><strong>{task.output.statistics.posts_per_week ?? '—'}</strong><span>样本内每周发布</span></div></div>}
    {!task.output.claims?.length && <Empty description="分析完成后，带出处的结论会显示在这里。" />}
    {task.output.claims?.map((claim: Claim, index) => <article className="douyin-claim" key={index}><Tag color={claim.type === 'observation' ? 'blue' : claim.type === 'inference' ? 'orange' : 'green'}>{labels[claim.type]}</Tag><p>{claim.text}</p><div className="douyin-actions">{claim.refs.map((id) => <Button size="small" key={id} onClick={() => setRef(id)} aria-label={`查看出处 ${id}`}>出处 {id.length > 10 ? id.slice(0, 8) : id}</Button>)}</div></article>)}
    {!!task.output.segments?.length && <details><summary>查看带时间戳的口播转写</summary>{task.output.segments.map((s) => <p key={s.id}><Button size="small" onClick={() => setRef(s.id)}>{s.start.toFixed(1)}–{s.end.toFixed(1)}秒</Button> {s.text}</p>)}</details>}
    {!!task.output.frames?.length && <details><summary>查看抽样关键帧（最多16帧）</summary><div className="douyin-actions">{task.output.frames.map((f) => <Button key={f.id} onClick={() => setRef(f.id)}>{f.time.toFixed(1)}秒</Button>)}</div></details>}
    <Modal className="douyin-modal" open={!!ref} title="核对分析出处" footer={null} onCancel={() => setRef(null)}>
      {segment && <><p>{segment.start.toFixed(1)}–{segment.end.toFixed(1)}秒 · {segment.id}</p><p>{segment.text}</p></>}
      {frame && <Frame key={`${task.id}:${frame.id}`} client={client} accountId={accountId} taskId={task.id} frame={frame} />}
      {work && <><h3>{work.title}</h3><p>{work.description}</p><a href={work.url} target="_blank" rel="noreferrer">打开来源作品</a></>}
      {!segment && !frame && !work && ref && <ReferencedBreakdown client={client} accountId={accountId} taskId={ref} />}
    </Modal>
  </section>;
}
function ReferencedBreakdown({ client, accountId, taskId }: { client: DouyinClient; accountId: string; taskId: string }) {
  const [source, setSource] = useState<DouyinTask | null>(null); const [error, setError] = useState('');
  useEffect(() => { let active = true; void client.task(accountId, taskId).then((t) => { if (active) setSource(t); }).catch((e) => { if (active) setError(documentError(e)); }); return () => { active = false; }; }, [client, accountId, taskId]);
  return error ? <Alert type="error" message={error} /> : source ? <AnalysisResult task={source} client={client} accountId={accountId} /> : <p>正在加载来源拆解…</p>;
}
function Frame({ client, accountId, taskId, frame }: { client: DouyinClient; accountId: string; taskId: string; frame: { id: string; time: number } }) {
  const [src, setSrc] = useState(''); const [error, setError] = useState('');
  useEffect(() => {
    let active = true; let url = '';
    void client.frame(accountId, taskId, frame.id).then((blob) => { if (active) { url = URL.createObjectURL(blob); setSrc(url); } }).catch((e) => { if (active) setError(documentError(e)); });
    return () => { active = false; if (url) URL.revokeObjectURL(url); };
  }, [client, accountId, taskId, frame.id]);
  return <>{error && <Alert type="error" message={error} />}<p>{frame.time.toFixed(1)}秒 · 抽样关键帧</p>{src && <img className="douyin-frame" src={src} alt={`${frame.time.toFixed(1)}秒关键帧`} />}</>;
}
