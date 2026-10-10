import { useEffect, useRef, useState } from 'react';
import { Button, Spin, Tag } from 'antd';
import { useRunStream } from '@/features/run-stream';
import { repoTerminal, type RepoTask } from '@/services/repoExplainer';

const labels: Record<string, string> = {
  queued: '排队中', running: '执行中', waiting_input: '等待输入', waiting_children: '等待子任务',
  cancelling: '正在取消', succeeded: '已完成', failed: '失败', cancelled: '已取消',
};
const kinds: Record<string, string> = { import: '源码导入', analyze: '功能分析', write: '文案生成' };
const stages: Record<string, string> = {
  queued: '任务已入队，等待执行器接单。', running: '执行器已接单，正在准备任务。',
  waiting_input: '任务正在等待输入。', waiting_children: '任务正在等待子任务完成。',
  cancelling: '已请求取消，正在停止任务。', succeeded: '结果已保存，可在对应页签查看。',
  failed: '任务失败，可以重新提交。', cancelled: '任务已取消。',
};

export default function RepoTaskProgress({ task, organization, busy, onCancel, onSettled }: {
  task: RepoTask; organization: string; busy: boolean; onCancel: () => void; onSettled: () => void;
}) {
  const { state, connected, error } = useRunStream({
    organizationId: organization, runId: task.run_id || null, enabled: !repoTerminal(task.status),
  });
  // Poll responses and event replays can arrive in either order. Never replace
  // a newer persisted status with an older event from the reconnect backlog.
  const live = state.runId === task.run_id && state.nextSequence - 1 >= (task.event_sequence ?? 0);
  const status = !repoTerminal(task.status) && live ? state.status || task.status : task.status;
  const progress = live && state.progress ? state.progress : task.progress;
  const terminal = repoTerminal(status);
  const notified = useRef(false);
  useEffect(() => {
    if (terminal && !repoTerminal(task.status) && !notified.current) {
      notified.current = true;
      onSettled();
    }
  }, [terminal, task.status, onSettled]);
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    if (terminal) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [terminal]);
  const seconds = Math.max(0, Math.floor((now - Date.parse(task.created_at || '')) / 1000));
  const stage = status === 'failed' ? task.error || stages.failed
    : status === 'running' ? String(progress.stage || stages.running) : stages[status] || status;
  return <section className="repo-card repo-task" aria-label={`${kinds[task.kind] || '任务'}进度`}>
    <div className="repo-task-header">
      {!terminal && <Spin size="small" />}
      <strong>{kinds[task.kind] || '任务'}</strong>
      <Tag color={status === 'failed' ? 'error' : status === 'succeeded' ? 'success' : 'processing'}>{labels[status] || status}</Tag>
      {!terminal && <Button disabled={busy || status === 'cancelling'} onClick={onCancel}>取消任务</Button>}
    </div>
    <p role="status" aria-live="polite">{stage}</p>
    <div className="repo-task-meta">
      {!terminal && Number.isFinite(seconds) && <span>已等待 {Math.floor(seconds / 60)} 分 {seconds % 60} 秒</span>}
      {status === 'running' && progress.activity === 'waiting_model' && <span>等待模型响应，当前阶段可能需要几分钟</span>}
      {status === 'running' && progress.activity === 'responding' && <span>模型正在输出{typeof progress.characters === 'number' ? ` · 已接收 ${progress.characters} 字符` : ''}</span>}
      {!terminal && <span>{connected ? '实时更新已连接' : error ? '实时连接中断，正在重连并定时刷新' : '正在同步进度，定时刷新已开启'}</span>}
    </div>
  </section>;
}
