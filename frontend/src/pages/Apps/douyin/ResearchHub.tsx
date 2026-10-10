import { useEffect, useMemo, useState } from 'react';
import { Alert, Button, Progress, Select, Spin } from 'antd';
import { useSearchParams } from 'react-router-dom';
import { isActive, type DouyinAccount } from '@/services/douyinBenchmark';
import { documentError } from '@/services/documents';
import { researchApi, researchLabels, type ResearchTask } from '@/services/douyinResearch';
import { allRows, Field, Pager, useRows } from './ResearchCommon';
import { ResearchLibrary } from './ResearchLibrary';
import { IdeaLibrary } from './IdeaLibrary';
import { CreationCenter, CreatorProfiles } from './CreationCenter';
import { PublicationReview } from './PublicationReview';
import { SubscriptionCenter } from './SubscriptionCenter';
import { ResearchResult } from './ResearchResult';
import { douyinLocation, taskKinds, taskSection } from './navigation';
import { KnowledgeLibrary } from './CreationKnowledge';

export function ResearchHub({ base, section, onSection, openAccount }: { base: string; section: string; onSection: (section: string) => void; openAccount: (id: string | null) => void }) {
  const client = useMemo(() => researchApi(base), [base]); const [params, setParams] = useSearchParams();
  const [accounts, setAccounts] = useState<DouyinAccount[]>([]); const [refresh, setRefresh] = useState(0); const [error, setError] = useState('');
  const [task, setTask] = useState<ResearchTask | null>(null); const taskId = params.get('task') || ''; const [retry, setRetry] = useState(0);
  const creator = params.get('owned') || '';
  const showHistory = !!taskKinds[section] || section === 'tasks';
  const history = useRows<ResearchTask>(client, 'tasks', { ...(section !== 'tasks' && { kind: taskKinds[section] || 'none' }), ...(['create', 'review'].includes(section) && creator && { target_account: creator }) });
  useEffect(() => { let alive = true; void allRows<DouyinAccount>(client, 'accounts').then(rows => { if (alive) setAccounts(rows); }).catch(e => { if (alive) setError(documentError(e)); }); return () => { alive = false; }; }, [client, refresh]);
  useEffect(() => {
    let alive = true; let timer: ReturnType<typeof setTimeout>; setTask(null); if (!taskId) return;
    const poll = async () => {
      try {
        const value = await client.task(taskId); if (!alive) return;
        const mode = ['rewrite', 'transcribe'].includes(value.kind) ? 'rewrite' : value.kind === 'variants' ? 'variants' : undefined;
        if (section !== 'tasks' && !(taskKinds[section] || '').split(',').includes(value.kind)) {
          setParams(old => douyinLocation(old, taskSection(value.kind), { task: value.id, mode, owned: value.output.creation_context?.target_account_id || old.get('owned') || undefined }), { replace: true }); return;
        }
        if (section === 'create' && mode && params.get('mode') !== mode) {
          setParams(old => { const next = new URLSearchParams(old); next.set('mode', mode); return next; }, { replace: true }); return;
        }
        setTask(value); setError(''); if (isActive(value)) timer = setTimeout(() => void poll(), 2500);
      } catch (e) { if (alive) { setError(documentError(e)); timer = setTimeout(() => void poll(), 5000); } }
    };
    void poll(); return () => { alive = false; clearTimeout(timer); };
  }, [client, taskId, retry, section, setParams, params]);
  function selectTask(id: string, kind?: string, restore = false) { setParams(old => { const row = history.results.find(t => t.id === id); const destination = kind && ['account', 'collect'].includes(kind) && row?.account_id ? 'accounts' : kind ? taskSection(kind) : 'tasks'; const next = !restore && destination === section ? new URLSearchParams(old) : douyinLocation(old, destination, { account: destination === 'accounts' ? row?.account_id || undefined : undefined, owned: row?.output.creation_context?.target_account_id || old.get('owned') || undefined }); next.set('task', id); if (kind && ['rewrite', 'transcribe'].includes(kind)) next.set('mode', 'rewrite'); if (kind === 'variants') next.set('mode', 'variants'); return next; }); }
  async function run(body: Record<string, unknown>) { const value = await client.start(body); setTask(value); selectTask(value.id, value.kind); history.reload(); }
  return <div className="douyin-research-hub">{error && <Alert type="error" message={error} action={<Button onClick={() => { setError(''); setRetry(v => v + 1); setRefresh(v => v + 1); }}>重试加载</Button>} />}
    {section === 'knowledge' && <KnowledgeLibrary client={client} />}
    {section === 'research' && <ResearchLibrary client={client} accounts={accounts} run={run} onAccounts={() => onSection('')} />}
    {['ideas', 'materials', 'inspirations'].includes(section) && <IdeaLibrary key={section} resource={section === 'ideas' ? 'ideas' : 'inspirations'} client={client} onCreate={value => setParams(old => douyinLocation(old, 'create', { idea: value.id, mode: 'write' }))} />}
    {section === 'create' && <CreationCenter key={[creator, params.get('profile'), params.get('source'), params.get('topic'), params.get('mode'), params.get('output')].join(':')} client={client} run={run} onProfiles={() => onSection('owned')} />}
    {section === 'profiles' && <CreatorProfiles client={client} />}
    {section === 'review' && <PublicationReview key={creator || 'all'} accountId={creator} onAccount={id => setParams(old => douyinLocation(old, 'review', { owned: id || undefined }))} client={client} accounts={accounts} reloadAccounts={() => setRefresh(v => v + 1)} run={run} />}
    {section === 'subscriptions' && <SubscriptionCenter key={params.get('subscription') || 'all'} initialAccount={params.get('subscription') || undefined} client={client} accounts={accounts} openAccount={openAccount} onTask={selectTask} />}
    {showHistory && <section className="douyin-panel douyin-form"><div className="douyin-section-title"><h2>{section === 'tasks' ? '全部任务记录' : '本模块任务记录'}</h2><Button onClick={history.reload}>刷新任务记录</Button></div>{history.error && <Alert type="error" message={history.error} />}<Field label="任务历史"><Select aria-label="研究任务历史" value={taskId || undefined} options={history.results.map(t => ({ value: t.id, label: `${researchLabels[t.kind] || t.kind} · ${new Date(t.created_at).toLocaleString()} · ${t.stage}` }))} onChange={id => selectTask(id, history.results.find(t => t.id === id)?.kind, true)} /></Field><Pager rows={history} />
      {taskId && !task && !error && <Spin />}{task && <><div className="douyin-section-title"><h3>{researchLabels[task.kind] || task.kind} · {task.stage}</h3>{isActive(task) && <Button onClick={() => { void client.cancel(task.id).then(() => setRetry(v => v + 1)).catch(e => setError(documentError(e))); }}>取消任务</Button>}</div>
        {isActive(task) && <p role="status"><Spin size="small" /> 正在处理，可离开页面后回来查看。</p>}{task.status === 'cancelled' && <Alert type="info" message="任务已取消，已取得的资料保留。" />}{task.error && <Alert type="error" message={task.error} />}{!!task.progress.total && <Progress percent={Math.min(100, Math.round((task.progress.current || 0) / task.progress.total * 100))} />}
        <ResearchResult onCreate={(source, topic, output) => setParams(old => douyinLocation(old, 'create', { source, topic: String(topic), output, mode: 'write', owned: task.output.creation_context?.target_account_id }))} key={task.id} client={client} task={task} run={run} />
      </>}
    </section>}
  </div>;
}
