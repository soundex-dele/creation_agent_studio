import { useEffect, useMemo, useState } from 'react';
import { Alert, Button, Progress, Select, Spin } from 'antd';
import { useSearchParams } from 'react-router-dom';
import { isActive, type DouyinAccount } from '@/services/douyinBenchmark';
import { documentError } from '@/services/documents';
import { researchApi, researchLabels, type Idea, type ResearchTask } from '@/services/douyinResearch';
import { allRows, Field, Pager, useRows } from './ResearchCommon';
import { ResearchLibrary } from './ResearchLibrary';
import { IdeaLibrary } from './IdeaLibrary';
import { CreationCenter, CreatorProfiles } from './CreationCenter';
import { PublicationReview } from './PublicationReview';
import { SubscriptionCenter } from './SubscriptionCenter';
import { ResearchResult } from './ResearchResult';

export function ResearchHub({ base, section, onSection, openAccount }: { base: string; section: string; onSection: (section: string) => void; openAccount: (id: string | null) => void }) {
  const client = useMemo(() => researchApi(base), [base]); const [params, setParams] = useSearchParams();
  const [accounts, setAccounts] = useState<DouyinAccount[]>([]); const [refresh, setRefresh] = useState(0); const [error, setError] = useState(''); const [idea, setIdea] = useState<Idea | null>(null);
  const [task, setTask] = useState<ResearchTask | null>(null); const taskId = params.get('task') || ''; const [retry, setRetry] = useState(0);
  const history = useRows<ResearchTask>(client, 'tasks');
  useEffect(() => { let alive = true; void allRows<DouyinAccount>(client, 'accounts').then(rows => { if (alive) setAccounts(rows); }).catch(e => { if (alive) setError(documentError(e)); }); return () => { alive = false; }; }, [client, refresh]);
  useEffect(() => {
    let alive = true; let timer: ReturnType<typeof setTimeout>; setTask(null); if (!taskId) return;
    const poll = async () => { try { const value = await client.task(taskId); if (!alive) return; setTask(value); setError(''); if (isActive(value)) timer = setTimeout(() => void poll(), 2500); } catch (e) { if (alive) { setError(documentError(e)); timer = setTimeout(() => void poll(), 5000); } } };
    void poll(); return () => { alive = false; clearTimeout(timer); };
  }, [client, taskId, retry]);
  function selectTask(id: string) { setParams(old => { const next = new URLSearchParams(old); next.set('task', id); return next; }); }
  async function run(body: Record<string, unknown>) { const value = await client.start(body); setTask(value); selectTask(value.id); history.reload(); }
  return <div className="douyin-research-hub">{error && <Alert type="error" message={error} action={<Button onClick={() => { setError(''); setRetry(v => v + 1); setRefresh(v => v + 1); }}>重试加载</Button>} />}
    {section === 'research' && <ResearchLibrary client={client} accounts={accounts} run={run} onAccounts={() => onSection('')} />}
    {section === 'ideas' && <IdeaLibrary client={client} onCreate={value => { setIdea(value); onSection('create'); }} />}
    {section === 'create' && <CreationCenter client={client} initialIdea={idea} run={run} onProfiles={() => onSection('profiles')} />}
    {section === 'profiles' && <CreatorProfiles client={client} />}
    {section === 'review' && <PublicationReview client={client} accounts={accounts} reloadAccounts={() => setRefresh(v => v + 1)} run={run} />}
    {section === 'subscriptions' && <SubscriptionCenter client={client} accounts={accounts} openAccount={openAccount} onTask={selectTask} />}
    <section className="douyin-panel douyin-form"><div className="douyin-section-title"><h2>研究与创作任务</h2><Button onClick={history.reload}>刷新任务记录</Button></div>{history.error && <Alert type="error" message={history.error} />}<Field label="任务历史"><Select aria-label="研究任务历史" value={taskId || undefined} options={history.results.map(t => ({ value: t.id, label: `${researchLabels[t.kind] || t.kind} · ${new Date(t.created_at).toLocaleString()} · ${t.stage}` }))} onChange={selectTask} /></Field><Pager rows={history} />
      {taskId && !task && !error && <Spin />}{task && <><div className="douyin-section-title"><h3>{researchLabels[task.kind] || task.kind} · {task.stage}</h3>{isActive(task) && <Button onClick={() => { void client.cancel(task.id).then(() => setRetry(v => v + 1)).catch(e => setError(documentError(e))); }}>取消任务</Button>}</div>
        {isActive(task) && <p role="status"><Spin size="small" /> 正在处理，可离开页面后回来查看。</p>}{task.status === 'cancelled' && <Alert type="info" message="任务已取消，已取得的资料保留。" />}{task.error && <Alert type="error" message={task.error} />}{!!task.progress.total && <Progress percent={Math.min(100, Math.round((task.progress.current || 0) / task.progress.total * 100))} />}
        <ResearchResult key={task.id} client={client} task={task} run={run} />
      </>}
    </section>
  </div>;
}
