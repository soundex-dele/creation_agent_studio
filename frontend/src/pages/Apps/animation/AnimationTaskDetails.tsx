import { useEffect, useState } from 'react';
import { Alert, Button, Modal, Spin } from 'antd';
import { CheckCircle2, Circle, CircleX, Clock3 } from 'lucide-react';
import type { ApplicationRuntimeClient } from '@/services/applicationRuntime';
import { animationStatus, animationTerminal, type AnimationRun } from '@/services/animationStudio';
import './AnimationTaskDetails.css';

type Progress = Record<string, unknown>;
type Entry = { key: string; title: string; detail: string; time: string; errorMessage?: string };
const stages: Record<string, string> = {
  storyboard: 'AI 正在生成分镜', generating: 'AI 正在制作画面', repairing: 'AI 正在修复场景',
  building_preview: '正在构建并校验预览', building_cover: '正在生成封面',
  speech: '正在合成配音', transcribing: '正在识别字幕', rendering: '正在渲染视频', saving: '正在保存制作结果',
};
const statuses: Record<string, string> = {
  'run.queued': 'queued', 'run.started': 'running', 'run.retry_scheduled': 'queued',
  'run.waiting_input': 'waiting_input', 'run.waiting_children': 'waiting_children',
  'run.cancelling': 'cancelling', 'run.cancelled': 'cancelled', 'run.failed': 'failed', 'run.succeeded': 'succeeded',
};
const positive = (value: unknown) => typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : undefined;
function describe(progress: Progress): Omit<Entry, 'time'> {
  const stage = typeof progress.stage === 'string' ? progress.stage : '';
  const index = positive(progress.scene_index); const total = positive(progress.scene_total);
  const attempt = positive(progress.attempt); const characters = positive(progress.characters);
  const details = [
    index && total ? `第 ${index} / ${total} 幕` : '',
    typeof progress.scene_title === 'string' ? progress.scene_title : '',
    stage !== 'build_failed' && attempt && attempt > 1 ? `第 ${attempt - 1} 次修复` : '',
    stage === 'build_failed' ? (progress.will_retry === true ? `接下来进行第 ${attempt || 1} 次修复` : '不再自动修复') : '',
    progress.activity === 'responding' ? `AI 正在返回内容${characters ? ` · 已接收 ${characters.toLocaleString('zh-CN')} 字符` : ''}` : '',
  ].filter(Boolean);
  const title = stage === 'build_failed' ? (attempt && attempt > 1 ? `第 ${attempt - 1} 次修复后仍失败` : '首次构建失败') : stages[stage] || '正在处理任务';
  return { key: `${stage}:${progress.scene_id || ''}:${attempt || ''}`, title, detail: details.join(' · '),
    errorMessage: typeof progress.error_message === 'string' ? progress.error_message : undefined };
}
function formatTime(value?: string | null) {
  return value && Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleTimeString('zh-CN', { hour12: false }) : '';
}

export default function AnimationTaskDetails({ run, runtime, onClose }: {
  run: AnimationRun; runtime: ApplicationRuntimeClient; onClose: () => void;
}) {
  const [open, setOpen] = useState(true);
  const [progress, setProgress] = useState<Progress>();
  const [entries, setEntries] = useState<Entry[]>([]);
  const [streamStatus, setStreamStatus] = useState(run.status);
  const [error, setError] = useState('');
  const [connection, setConnection] = useState('connecting');
  const [compacted, setCompacted] = useState(false);
  const [reload, setReload] = useState(0);
  const status = animationTerminal(run.status) ? run.status : streamStatus;
  const terminal = animationTerminal(status);
  useEffect(() => {
    if (!open) return;
    let alive = true; let sequence = 0;
    setConnection('connecting'); setEntries([]); setProgress(undefined); setCompacted(false);
    const append = (entry: Entry) => setEntries(current => {
      const last = current[current.length - 1];
      // Coalesce streamed character counts, keeping the stage's original timestamp.
      const next = last?.key === entry.key ? [...current.slice(0, -1), { ...entry, errorMessage: entry.errorMessage || last.errorMessage, time: last.time }]
        : [...current, entry];
      // Keep every failure even when routine streaming progress exceeds the history limit.
      if (next.filter(item => !item.errorMessage).length > 100) next.splice(next.findIndex(item => !item.errorMessage), 1);
      return next;
    });
    const stream = runtime.subscribeRun(run.id, {
      onEvent: event => {
        if (!alive || event.run_id !== run.id || event.sequence <= sequence) return;
        sequence = event.sequence;
        if (event.type === 'progress.updated') {
          setProgress(event.payload);
          append({ ...describe(event.payload), time: event.created_at });
        } else if (statuses[event.type]) {
          const next = statuses[event.type]; setStreamStatus(next);
          append({ key: event.type, title: animationStatus(next), detail: '', time: event.created_at });
          if (next === 'failed') setError(typeof event.payload.error_message === 'string' ? event.payload.error_message : '制作失败，请返回作品调整后重试。');
        }
      },
      onSnapshot: snapshot => {
        if (!alive || snapshot.run_id !== run.id || snapshot.through_sequence < sequence) return;
        sequence = snapshot.through_sequence; setCompacted(true);
        if (snapshot.projection.status) setStreamStatus(snapshot.projection.status);
        if (snapshot.projection.progress) {
          setProgress(snapshot.projection.progress);
          append({ ...describe(snapshot.projection.progress), time: snapshot.updated_at });
        }
      },
      onConnectionChange: connected => { if (alive) setConnection(connected ? 'live' : 'reconnecting'); },
      onError: () => { if (alive) setConnection('error'); },
    });
    return () => { alive = false; stream.abort(); };
  }, [run.id, runtime, open, reload]);
  const current = progress ? describe(progress) : undefined;
  return <Modal open={open} title="制作详情" width={680} rootClassName="animation-task-modal"
    onCancel={() => setOpen(false)} afterClose={onClose}
    footer={<Button onClick={() => setOpen(false)}>关闭</Button>}>
    <div className="animation-task-details">
      <div className="animation-task-current" role="status">
        {terminal ? status === 'succeeded' ? <CheckCircle2 size={24} aria-hidden="true" /> : <CircleX size={24} aria-hidden="true" /> : <Spin size="small" />}
        <div><strong>{terminal || status === 'cancelling' ? animationStatus(status) : current?.title || animationStatus(status)}</strong>
          <p>{terminal ? '任务已结束，可关闭详情返回作品。' : current?.detail || (status === 'queued' ? '任务已提交，正在等待执行。' : '等待任务上报进度，收到后会自动更新。')}</p></div>
      </div>
      {(error || run.error_message) && <Alert showIcon type="error" message="本次制作失败" description={run.error_message || error} />}
      {!terminal && ['reconnecting', 'error'].includes(connection) && <Alert type="warning" showIcon message="进度连接中断，正在重连；制作任务仍在后台执行。"
        action={<Button size="small" onClick={() => setReload(value => value + 1)}>重新连接</Button>} />}
      <div className="animation-task-log-heading"><h3>制作进展</h3><span>{terminal ? '任务已结束' : connection === 'live' ? '实时更新' : '连接进度中'}</span></div>
      {compacted && <p className="animation-task-note">较早记录已归档，已恢复最近的制作进度。</p>}
      {entries.length ? <ol className="animation-task-log">{entries.map((entry, index) => <li key={`${index}:${entry.key}`}>
        <Circle size={10} aria-hidden="true" /><div><strong>{entry.title}</strong>{entry.detail && <p>{entry.detail}</p>}
          {entry.errorMessage && <details className="animation-task-error" open><summary>报错内容</summary><pre>{entry.errorMessage}</pre></details>}</div>
        <time dateTime={entry.time || undefined}>{formatTime(entry.time)}</time>
      </li>)}</ol> : <p className="animation-task-note">暂无进度记录，任务开始后会在这里显示。</p>}
      <p className="animation-task-note"><Clock3 size={14} aria-hidden="true" />{run.started_at ? `开始于 ${formatTime(run.started_at)}` : '等待开始'} · 最多展示最近 100 条常规进度，保留本次任务的报错记录。关闭此窗口不会取消制作。</p>
    </div>
  </Modal>;
}
