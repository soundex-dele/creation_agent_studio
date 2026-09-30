import { useCallback, useEffect, useRef, useState } from 'react';
import { Alert, Button, Empty, Input, Select, Spin, Tag } from 'antd';
import { Copy, Heart, RefreshCw, ShieldCheck } from 'lucide-react';
import { createUuid } from '@/lib/uuid';
import { inputOf, isActiveTask, promptError, scenes, type Answers, type PromptClient, type PromptInput, type PromptSession, type PromptTask, type PromptVersion, type TaskKind } from '@/services/promptMaster';
import { PromptForm } from './PromptForm';
import { QuestionCard } from './QuestionCard';

export function PromptWorkspace({ client, id, onDirty }: { client: PromptClient; id: string; onDirty: (dirty: boolean) => void }) {
  const [session, setSession] = useState<PromptSession | null>(null);
  const [form, setForm] = useState<PromptInput | null>(null);
  const [answers, setAnswers] = useState<Answers>({});
  const [task, setTask] = useState<PromptTask | null>(null);
  const [selected, setSelected] = useState<PromptVersion | null>(null);
  const [versions, setVersions] = useState<PromptVersion[]>([]);
  const [versionPage, setVersionPage] = useState(1); const [versionCount, setVersionCount] = useState(0);
  const [standard, setStandard] = useState(''); const [concise, setConcise] = useState('');
  const [instruction, setInstruction] = useState(''); const [editingInput, setEditingInput] = useState(false);
  const [busy, setBusy] = useState(false); const [loading, setLoading] = useState(true);
  const [error, setError] = useState(''); const [notice, setNotice] = useState('');
  const mounted = useRef(true); const operation = useRef(false);
  const active = isActiveTask(task); const disabled = busy || active;
  const bodyDirty = !!selected && (standard !== selected.standard || concise !== selected.concise);
  const answersDirty = !!session && JSON.stringify(answers) !== JSON.stringify(session.answers);
  const inputDirty = !!session && !!form && JSON.stringify(form) !== JSON.stringify(inputOf(session));
  const dirty = bodyDirty || answersDirty || inputDirty || !!instruction.trim();
  const chooseVersion = useCallback((v: PromptVersion | null) => {
    setSelected(v); setStandard(v?.standard || ''); setConcise(v?.concise || '');
  }, []);
  const apply = useCallback((s: PromptSession) => {
    setSession(s); setForm(inputOf(s)); setAnswers(s.answers); setTask(s.latest_task); chooseVersion(s.latest_version);
  }, [chooseVersion]);
  const refreshVersions = useCallback(async () => {
    const page = await client.versions(id);
    if (mounted.current) { setVersions(page.results); setVersionCount(page.count); setVersionPage(1); }
  }, [client, id]);
  const reload = useCallback(async () => {
    const s = await client.get(id);
    if (mounted.current) apply(s);
    await refreshVersions();
  }, [client, id, apply, refreshVersions]);
  useEffect(() => {
    mounted.current = true;
    void reload().catch((e) => { if (mounted.current) setError(promptError(e)); }).finally(() => { if (mounted.current) setLoading(false); });
    return () => { mounted.current = false; };
  }, [reload]);
  useEffect(() => { onDirty(dirty); return () => onDirty(false); }, [dirty, onDirty]);
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ''; };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);
  useEffect(() => {
    if (!task || !active) return;
    let stopped = false; let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next = await client.task(id, task.id);
        if (stopped) return;
        setTask(next);
        if (!isActiveTask(next)) {
          await reload();
          if (!stopped) setNotice(next.status === 'succeeded' ? '已完成，结果已保存。' : '');
          return;
        }
      } catch (e) { if (!stopped) setError(promptError(e)); }
      if (!stopped) timer = setTimeout(poll, 2000);
    };
    timer = setTimeout(poll, 1200);
    return () => { stopped = true; clearTimeout(timer); };
  }, [active, task?.id, client, id, reload]); // eslint-disable-line react-hooks/exhaustive-deps

  const run = async (action: () => Promise<void>) => {
    if (operation.current) return;
    operation.current = true; setBusy(true); setError(''); setNotice('');
    try { await action(); } catch (e) { if (mounted.current) setError(promptError(e)); }
    finally { operation.current = false; if (mounted.current) setBusy(false); }
  };
  const start = (kind: TaskKind) => void run(async () => {
    if (!session) return;
    let current = session; let version = selected;
    if (answersDirty) {
      current = await client.update(id, current.revision, { answers });
      setSession(current); setAnswers(current.answers);
    }
    if (bodyDirty && version) {
      current = await client.saveVersion(id, current.revision, version.id, standard, concise);
      version = current.latest_version; apply(current); await refreshVersions();
    }
    const next = await client.start(id, current.revision, kind, createUuid(), instruction,
      kind === 'check' || (kind !== 'analyze' && instruction.trim()) ? version?.id : undefined);
    if (mounted.current) { setTask(next); setInstruction(''); setEditingInput(false); }
  });
  const saveInput = () => void run(async () => {
    if (!session || !form) return;
    const current = await client.update(id, session.revision, form); apply(current); setEditingInput(false);
    const next = await client.start(id, current.revision, 'analyze', createUuid()); setTask(next);
  });
  const copyText = async (value: string) => {
    try { await navigator.clipboard.writeText(value); setNotice('提示词已复制。'); }
    catch { setError('复制失败，请在文本框中全选并手动复制。'); }
  };
  if (loading) return <div className="pm-loading" role="status"><Spin /><p>正在恢复你的需求与历史…</p></div>;
  if (!session || !form) return <Alert type="error" message={error || '无法读取会话'} action={<Button onClick={() => void run(reload)}>重试</Button>} />;

  const currentStep = selected && !session.results_stale ? 2 : session.rounds ? 1 : 0;
  return <section className="pm-workspace" aria-label="提示词工作区">
    <div className="pm-session-heading"><div><Tag>{scenes[session.scene === 'auto' ? session.detected_scene : session.scene]}</Tag><h2>{session.title}</h2></div>
      <Button disabled={disabled || dirty} icon={<Heart size={16} aria-hidden="true" fill={session.favorite ? 'currentColor' : 'none'} />}
        onClick={() => void run(async () => { apply(await client.update(id, session.revision, { favorite: !session.favorite })); })}>{session.favorite ? '已收藏' : '收藏'}</Button></div>
    <ol className="pm-steps" aria-label="生成进度">{['描述需求', '补齐关键细节', '获得提示词'].map((label, i) => <li key={label} aria-current={i === currentStep ? 'step' : undefined}><span>{i + 1}</span>{label}</li>)}</ol>
    {error && <Alert type="error" showIcon message={error} description="你的输入仍保留在页面中。若发生版本冲突，请先复制未保存内容，再重新加载。" action={<Button disabled={busy || active} onClick={() => void run(reload)}>重新加载</Button>} />}
    {notice && <div role="status"><Alert type="success" message={notice} /></div>}
    {active && <div className="pm-task" role="status"><Spin size="small" /><span>{task?.kind === 'analyze' ? '正在梳理需求与关键问题…' : task?.kind === 'check' ? '正在检查两个版本…' : '正在生成标准版与精简版…'} 可以离开页面，稍后回来查看。</span>
      <Button disabled={busy} onClick={() => void run(async () => { if (task) { setTask(await client.cancel(id, task.id)); await reload(); } })}>取消任务</Button></div>}
    {task && ['failed', 'stale', 'cancelled'].includes(task.status) && <Alert type={task.status === 'failed' ? 'error' : 'info'}
      message={task.error || '任务已取消，已保存的内容不受影响。'}
      action={<Button disabled={disabled || inputDirty || editingInput} onClick={() => start(task.kind)}>重新尝试</Button>} />}
    {session.results_stale && <Alert type="warning" message="需求或回答已变化，下方历史结果已过期。重新生成后会保留旧版本。" />}

    <section className="pm-card"><div className="pm-section-heading"><h3>{session.mode === 'optimize' ? '原始提示词与目标' : '需求摘要'}</h3>
      {session.rounds > 0 && <Button type="text" disabled={disabled || bodyDirty || answersDirty} onClick={() => setEditingInput(!editingInput)}>{editingInput ? '收起' : '修改需求'}</Button>}</div>
      {editingInput || (!session.rounds && !active) ? <><PromptForm value={form} onChange={setForm} disabled={disabled} submit={saveInput} label="保存并分析需求" />
        {editingInput && <p className="pm-muted">保存修改后重新提问，原结果仍保留在历史版本中。</p>}</> : <>
        <p className="pm-preserve">{session.analysis.summary || session.topic || session.original}</p>
        {session.mode === 'optimize' && <details><summary>查看保留的原文</summary><p className="pm-preserve">{session.original}</p></details>}
        {!!session.analysis.issues?.length && <div className="pm-health">{session.analysis.issues.map((item, i) => <p key={i}><strong>{item.problem}</strong><br />{item.suggestion}</p>)}</div>}
      </>}
    </section>

    {session.rounds > 0 && !editingInput && <section className="pm-card"><div className="pm-section-heading"><div><h3>{session.questions.length ? '让结果更贴近你的想法' : '信息已充分，可以生成'}</h3><p className="pm-muted">已完成 {session.rounds} / 2 轮分析。未回答的问题将按推荐处理，并在结果中列出假设。</p></div></div>
      {session.questions.map((q, index) => <QuestionCard key={q.id} question={q} index={index} value={answers[q.id]} disabled={disabled} onChange={(value) => setAnswers({ ...answers, [q.id]: value })} />)}
      <div className="pm-actions"><Button type="primary" size="large" disabled={disabled || inputDirty} onClick={() => start(session.mode)}>{selected ? '按当前需求重新生成' : '生成标准版与精简版'}</Button>
        {session.rounds < 2 && session.questions.length > 0 && <Button disabled={disabled || inputDirty} onClick={() => start('analyze')}>检查是否需要补问</Button>}
        {answersDirty && <Button disabled={disabled} onClick={() => void run(async () => { const updated = await client.update(id, session.revision, { answers }); setSession(updated); setAnswers(updated.answers); setNotice('回答已保存。'); })}>保存回答</Button>}</div>
    </section>}

    {selected && <section className="pm-card pm-result"><div className="pm-section-heading"><div><h3>你的提示词</h3><p className="pm-muted">可直接编辑；保存会创建新版本。</p></div>
      <Select aria-label="历史版本" disabled={disabled || dirty} value={selected.id} options={versions.map((v) => ({ value: v.id, label: `${new Date(v.created_at).toLocaleString('zh-CN')} · ${{ manual: '手动编辑', check: '体检', optimize: '优化', generate: '生成' }[v.source] || v.source}` }))}
        onChange={(value) => chooseVersion(versions.find((v) => v.id === value) || null)} />
      {versions.length < versionCount && <Button disabled={disabled} onClick={() => void run(async () => { const page = await client.versions(id, versionPage + 1); setVersions([...versions, ...page.results]); setVersionPage(versionPage + 1); })}>更多版本</Button>}</div>
      <div className="pm-results-grid">{([['标准版', standard, setStandard, 40000], ['精简版', concise, setConcise, 20000]] as const).map(([label, value, update, max]) => <div className="pm-version" key={label}>
        <div className="pm-section-heading"><label htmlFor={`pm-${label}`}>{label}</label><Button icon={<Copy size={14} aria-hidden="true" />} onClick={() => void copyText(value)}>复制{label}</Button></div>
        <Input.TextArea id={`pm-${label}`} value={value} disabled={disabled || editingInput} autoSize={{ minRows: 10, maxRows: 32 }} maxLength={max} onChange={(e) => update(e.target.value)} />
      </div>)}</div>
      <div className="pm-actions"><Button disabled={disabled || !bodyDirty || !standard.trim() || !concise.trim() || answersDirty || inputDirty} onClick={() => void run(async () => { apply(await client.saveVersion(id, session.revision, selected.id, standard, concise)); await refreshVersions(); setNotice('新版本已保存，体检待更新。'); })}>保存为新版本</Button>
        <Button icon={<ShieldCheck size={16} aria-hidden="true" />} disabled={disabled || !standard.trim() || !concise.trim() || inputDirty || editingInput} onClick={() => start('check')}>{bodyDirty ? '保存并体检' : '重新体检'}</Button>
        {(bodyDirty || selected.health_stale) && <Tag color="orange">体检待更新</Tag>}</div>
      <div className="pm-insights"><div><h4>采用的假设</h4>{selected.assumptions.length ? <ul>{selected.assumptions.map((item, i) => <li key={i}>{item}</li>)}</ul> : <p className="pm-muted">未额外采用假设。</p>}</div>
        <div><h4>提示词体检</h4>{(bodyDirty || selected.health_stale) && <p className="pm-muted">以下为上次体检记录，编辑后的内容尚未检查。</p>}{selected.health.length ? selected.health.map((item, i) => <p key={i}><strong>{item.problem}</strong><br />{item.suggestion}</p>) : <p className="pm-muted">本次检查未发现明确问题，尚未进行效果试运行。</p>}</div></div>
      {!!selected.changes.length && <details><summary>本次改进说明</summary><ul>{selected.changes.map((item, i) => <li key={i}>{item}</li>)}</ul></details>}
      {!!selected.constraints.length && <details><summary>关键约束核对（{selected.constraints.length} 项）</summary>{selected.constraints.map((item, i) => <div className="pm-constraint" key={i}><strong>{item.text}</strong><p>标准版：{item.standard_excerpt}</p><p>精简版：{item.concise_excerpt}</p></div>)}</details>}
      <div className="pm-refine"><label htmlFor="pm-refinement">还希望怎样调整？</label><Input.TextArea id="pm-refinement" disabled={disabled || editingInput} value={instruction} maxLength={5000} autoSize={{ minRows: 2, maxRows: 5 }}
        placeholder="例如：更具体一些，保留预算限制，输出改为表格。" onChange={(e) => setInstruction(e.target.value)} />
        <Button type="primary" icon={<RefreshCw size={15} aria-hidden="true" />} disabled={disabled || !instruction.trim() || inputDirty || editingInput || !standard.trim() || !concise.trim()} onClick={() => start('optimize')}>按修改意见优化</Button></div>
    </section>}
    {!selected && !active && session.rounds > 0 && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="回答后生成，两种提示词会出现在这里。" />}
  </section>;
}
