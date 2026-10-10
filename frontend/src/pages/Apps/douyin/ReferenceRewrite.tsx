import { SaveCaseButton } from './CaseIntegration';
import { useEffect, useState } from 'react';
import { Alert, Button, Select, Spin } from 'antd';
import { useSearchParams } from 'react-router-dom';
import { isActive, type DouyinTask, type DouyinWork, type Kind } from '@/services/douyinBenchmark';
import type { ResearchClient, ResearchWork } from '@/services/douyinResearch';
import { documentError } from '@/services/documents';
import { allRows, Field } from './ResearchCommon';
import { RewritePanel } from './RewritePanel';

export function ReferenceRewrite({ client }: { client: ResearchClient }) {
  const [params, setParams] = useSearchParams();
  const workId = params.get('work') || '';
  const taskId = params.get('task') || '';
  const [works, setWorks] = useState<ResearchWork[]>([]);
  const [task, setTask] = useState<(DouyinTask & { account_id?: string | null }) | null>(null);
  const [draft, setDraft] = useState<DouyinWork | null>(null);
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false); const [retry, setRetry] = useState(0);
  const work = works.find(w => w.id === workId);
  const accountId = task?.account_id || work?.account_id || params.get('referenceAccount') || '';
  useEffect(() => { let alive = true; void allRows<ResearchWork>(client, 'works').then(rows => { if (alive) setWorks(rows); }).catch(e => { if (alive) setError(documentError(e)); }); return () => { alive = false; }; }, [client]);
  useEffect(() => {
    let alive = true; let timer: ReturnType<typeof setTimeout>; setTask(null); setError('');
    if (!taskId) return;
    const poll = async () => {
      try {
        const value = await client.task(taskId);
        if (!alive) return;
        if (!['transcribe', 'rewrite'].includes(value.kind)) { setError('请选择转写或改写任务。'); return; }
        setTask({ ...value, kind: value.kind as Kind, output: { ...value.output, topics: undefined } });
        if (isActive(value)) timer = setTimeout(() => void poll(), 2500);
      } catch (e) { if (alive) setError(documentError(e)); }
    };
    void poll(); return () => { alive = false; clearTimeout(timer); };
  }, [client, taskId, retry]);
  useEffect(() => {
    let alive = true; setDraft(null);
    if (taskId || !work || work.kind !== 'image_album') return;
    void client.editor.works(work.account_id, { search: '', sort: 'published_at', outstanding: false }).then(data => {
      if (alive) setDraft(data.items.find(w => w.id === work.id) || { ...work, platform_id: '', cover: '', duration: null, ratio: null, outstanding: false, has_upload: false, published_at: work.published_at || null });
    }).catch(e => { if (alive) setError(documentError(e)); });
    return () => { alive = false; };
  }, [client, work, taskId]);
  async function run(body: { kind: Kind; [key: string]: unknown }) {
    setBusy(true); setError('');
    try {
      const value = await client.editor.start(accountId, body);
      setParams(old => { const next = new URLSearchParams(old); next.set('task', value.id); next.set('referenceAccount', accountId); return next; });
    } catch (e) { setError(documentError(e)); } finally { setBusy(false); }
  }
  return <div className="douyin-form"><p>参考改写保留来源主题与事实，使用你填写的改写要求；不会自动套用账号文风。按账号文风写作请使用“已有选题，开始写作”。</p>
    <Field label="参考作品"><Select aria-label="参考作品" value={workId || undefined} options={works.map(w => ({ value: w.id, label: `${w.account_name} · ${w.title}` }))} onChange={id => setParams(old => { const next = new URLSearchParams(old); next.set('work', id); next.delete('task'); next.set('referenceAccount', works.find(w => w.id === id)!.account_id); return next; })} /></Field>
    {error && <Alert type="error" message={error} action={<Button onClick={() => setRetry(v => v + 1)}>重新加载</Button>} />}
    {taskId && !task && !error && <Spin />}
    {work?.kind === 'video' && !taskId && <Button type="primary" loading={busy} onClick={() => void run({ kind: 'transcribe', work_id: workId })}>转写参考作品</Button>}
    {task && <><p role="status">{task.stage}</p>{task.error && <Alert type="error" message={task.error} />}{isActive(task) && <Button onClick={() => { void client.cancel(task.id).then(() => setRetry(v => v + 1)).catch(e => setError(documentError(e))); }}>取消任务</Button>}
      {task.kind === 'transcribe' && task.status === 'succeeded' && task.work_id && <SaveCaseButton client={client.editor} workId={task.work_id} taskId={task.id} />}
      {(task.kind === 'rewrite' || task.status === 'succeeded') && <RewritePanel key={task.id} client={client.editor} accountId={accountId} task={task} busy={busy} onRun={run} />}
      {task.kind === 'transcribe' && ['failed', 'cancelled'].includes(task.status) && <Button disabled={busy} onClick={() => void run({ kind: 'transcribe', work_id: task.work_id, force: true })}>重试转写</Button>}
    </>}
    {!taskId && draft && <RewritePanel key={draft.id} client={client.editor} accountId={accountId} draftWork={draft} busy={busy} onRun={run} />}
  </div>;
}
