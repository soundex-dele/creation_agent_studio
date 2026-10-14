import { useState, type ReactNode } from 'react';
import { Button, Tag } from 'antd';
import { activeTask, type Task } from '@/services/projectPromotion';

export function TaskRecord({ task, label, children }: { task: Task; label: string; children: ReactNode }) {
  const [open, setOpen] = useState(() => activeTask(task));
  return <details className="promotion-card" open={open} onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>{label} · {activeTask(task) ? '生成中' : task.status === 'succeeded' ? task.applied ? '已加入草稿' : '待查看' : '未完成'} <span className="promotion-muted">{new Date(task.created_at).toLocaleString()}</span></summary>
    {children}
  </details>;
}

const labels = { running: '正在执行', completed: '已完成', failed: '失败', stopped: '未完成' };

export default function TaskActivity({ task }: { task: Task }) {
  const [expanded, setExpanded] = useState(false);
  const items = task.activity?.items || [];
  const visible = expanded ? items : items.slice(-8);
  return <section className="promotion-activity" aria-label="Agent 执行过程">
    <div className="promotion-activity-heading"><h3>Agent 执行过程</h3><span className="promotion-muted">{items.length ? `${items.length} 条记录` : activeTask(task) ? '等待执行事件' : '暂无执行记录'}</span></div>
    {!items.length && <p className="promotion-muted">{activeTask(task) ? '启动后会自动展示执行步骤，每 3 秒刷新。' : '此任务未保存执行过程，重新生成后可查看。'}</p>}
    {!!task.activity?.dropped && <p className="promotion-muted">较早的 {task.activity.dropped} 条记录已省略，保留最近 100 条。</p>}
    {items.length > 8 && <Button type="text" aria-expanded={expanded} onClick={() => setExpanded(value => !value)}>{expanded ? '只看最近 8 条' : `展开全部 ${items.length} 条记录`}</Button>}
    <ol className="promotion-activity-list">
      {visible.map(item => {
        const status = item.status === 'running' && !activeTask(task) ? 'stopped' : item.status;
        return <li key={item.id} className="promotion-activity-item">
          <div className="promotion-activity-meta"><strong>{item.title}</strong><Tag color={status === 'failed' ? 'error' : status === 'running' ? 'processing' : undefined}>{labels[status]}</Tag><time className="promotion-muted" dateTime={item.created_at}>{new Date(item.created_at).toLocaleTimeString()}</time></div>
          {item.detail && <details className="promotion-activity-detail"><summary>查看命令与详情</summary><pre>{item.detail}</pre></details>}
        </li>;
      })}
    </ol>
  </section>;
}
