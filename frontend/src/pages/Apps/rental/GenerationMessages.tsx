import { useEffect, useRef, useState } from 'react';
import { Button } from 'antd';
import { activeTask, subscribeRentalTask, type Task } from '@/services/rentalGrowth';
import { rentalStreamText } from '@/services/rentalStreamText';

const terminalLabels: Record<string, string> = { succeeded: '生成完成，结果已保存', failed: '生成失败，已保留收到的消息', cancelled: '已取消生成' };

export function GenerationMessages({ task }: { task: Task }) {
  const [open, setOpen] = useState(() => activeTask(task));
  const [raw, setRaw] = useState('');
  const [phase, setPhase] = useState('正在连接生成消息…');
  const [connection, setConnection] = useState('');
  const [following, setFollowing] = useState(true);
  const output = useRef<HTMLDivElement>(null);
  const follow = useRef(true);
  const initialStatus = useRef(task.status);
  const { run_id, organization_id } = task;
  useEffect(() => {
    if (!open || !run_id || !organization_id) return;
    let alive = true;
    let lastSequence = 0;
    let terminal = false;
    setRaw(''); setPhase('正在连接生成消息…'); setConnection('');
    const handle = subscribeRentalTask({ run_id, organization_id }, {
      onEvent: event => {
        if (!alive || event.sequence <= lastSequence) return;
        lastSequence = event.sequence;
        if (event.type === 'output.delta' && typeof event.payload.text === 'string') {
          const text = event.payload.text;
          setRaw(old => (old + text).slice(0, 200000));
        } else if (event.type === 'output.snapshot' && typeof event.payload.text === 'string') {
          setRaw(event.payload.text.slice(0, 200000));
        } else if (event.type === 'progress.updated' && typeof event.payload.stage === 'string') {
          setPhase(event.payload.stage);
        } else if (event.type === 'run.started') setPhase('已开始生成，等待模型输出…');
        else if (event.type === 'run.queued') setPhase('任务已排队，等待开始…');
        const status = event.type.replace('run.', '');
        if (terminalLabels[status]) { terminal = true; setPhase(terminalLabels[status]); setConnection(''); }
      },
      onSnapshot: snapshot => {
        if (!alive) return;
        lastSequence = snapshot.through_sequence;
        setRaw((snapshot.projection.output || '').slice(0, 200000));
        const status = snapshot.projection.status || '';
        const stage = snapshot.projection.progress?.stage;
        if (terminalLabels[status]) {
          terminal = true; setPhase(terminalLabels[status]); setConnection(''); handle?.abort();
        } else if (typeof stage === 'string') setPhase(stage);
      },
      onConnectionChange: connected => {
        if (!alive || terminal) return;
        setConnection(connected ? '' : '连接中断，正在重新连接；已收到的消息会保留。');
        if (connected) setPhase(old => old === '正在连接生成消息…' ? initialStatus.current === 'queued' ? '任务已排队，等待开始…' : '已连接，等待生成消息…' : old);
      },
      onError: () => { if (alive && !terminal) setConnection('暂时无法获取实时消息，正在重试。也可刷新页面恢复。'); },
    });
    void handle?.done.catch(() => { if (alive) setConnection('消息连接已停止，请重新打开消息记录。'); });
    return () => { alive = false; handle?.abort(); };
  }, [open, run_id, organization_id]);
  const text = rentalStreamText(raw);
  useEffect(() => { if (follow.current && output.current) output.current.scrollTop = output.current.scrollHeight; }, [text]);
  if (!run_id || !organization_id) return null;
  const active = activeTask(task);
  return <section className="rental-generation-messages" aria-label="生成消息">
    <div className="rental-message-header"><strong>{active ? '实时生成消息' : '生成消息记录'}</strong><Button type="text" size="small" aria-expanded={open} aria-controls={`rental-messages-${task.id}`} onClick={() => setOpen(value => !value)}>{open ? '收起消息' : '查看消息'}</Button></div>
    {open && <div id={`rental-messages-${task.id}`}>
      <p role="status" className="rental-message-status">{terminalLabels[task.status] || phase}</p>
      {connection && <p className="rental-muted">{connection}</p>}
      <div className="rental-message-output" ref={output} role="region" aria-label="逐步生成的内容" tabIndex={0} onScroll={() => {
        const node = output.current;
        if (node) { const next = node.scrollHeight - node.scrollTop - node.clientHeight < 32; follow.current = next; setFollowing(next); }
      }}>{text || (active ? '模型开始输出后，内容会逐步显示在这里。' : '暂无可回放的文案消息。')}</div>
      {!following && <Button size="small" onClick={() => { follow.current = true; setFollowing(true); if (output.current) output.current.scrollTop = output.current.scrollHeight; }}>回到最新消息</Button>}
      {active && <p className="rental-muted">生成中的内容尚未校验，完成后可打开文案编辑与复制。</p>}
    </div>}
  </section>;
}
