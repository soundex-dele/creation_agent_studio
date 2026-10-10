import { useCallback, useEffect, useMemo, useState } from 'react';
import { Alert, Button, Empty, Input, Modal, Select, Spin, Tabs, Tag } from 'antd';
import { useSearchParams } from 'react-router-dom';
import { isActive, productionFormats, type DouyinAccount, type DouyinTask, type ProductionFormat } from '@/services/douyinBenchmark';
import { researchApi, researchTaskStatus, type CreatorProfile, type Inspiration, type ResearchClient, type ResearchTask, type ResearchWork, type VoiceContent, type VoiceSample, type VoiceVersion } from '@/services/douyinResearch';
import { documentError } from '@/services/documents';
import { allRows, Field, Pager, useRows } from './ResearchCommon';
import { ResearchResult } from './ResearchResult';
import { GenerationPreview } from './GenerationPreview';
import { KnowledgePicker } from './CreationKnowledge';
import { knowledgeSelection, type KnowledgeSnapshot } from '@/services/douyinKnowledge';
import './OwnedAccounts.css';

const blankContent: VoiceContent = { current_positioning: '', positioning: '', audience: '', content_pillars: '', content_boundaries: '', rules: '', examples: '', avoid: '', prompt: '' };
const contentLabels: Record<keyof VoiceContent, string> = { current_positioning: '历史作品呈现的定位', positioning: '希望建立的定位', audience: '目标受众（推测）', content_pillars: '内容支柱', content_boundaries: '内容边界', rules: '保留与改善的表达规则', examples: '原文示例', avoid: '避免的表达', prompt: '完整创作提示词' };
const usageOptions = [{ value: 'style', label: '代表我的风格' }, { value: 'content', label: '只参考内容' }, { value: 'exclude', label: '不学习' }];

export function OwnedAccounts({ base, openAccount }: { base: string; openAccount: (id: string) => void }) {
  const client = useMemo(() => researchApi(base), [base]);
  const [params, setParams] = useSearchParams(); const selected = params.get('owned') || '';
  const [accounts, setAccounts] = useState<DouyinAccount[]>([]); const [tick, setTick] = useState(0);
  const [error, setError] = useState(''); const [loading, setLoading] = useState(true); const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false); const [adding, setAdding] = useState(false); const [source, setSource] = useState(''); const [existing, setExisting] = useState<string>();
  useEffect(() => { let alive = true; setLoading(true); void allRows<DouyinAccount>(client, 'accounts').then(rows => { if (alive) setAccounts(rows); }).catch(e => { if (alive) setError(documentError(e)); }).finally(() => { if (alive) setLoading(false); }); return () => { alive = false; }; }, [client, tick]);
  useEffect(() => { const warn = (e: BeforeUnloadEvent) => { if (dirty) { e.preventDefault(); e.returnValue = ''; } }; window.addEventListener('beforeunload', warn); return () => window.removeEventListener('beforeunload', warn); }, [dirty]);
  const confirmLeave = (next: () => void) => { if (dirty) Modal.confirm({ title: '有未保存的编辑', content: '离开将丢弃未保存的样本或文风修改。', okText: '丢弃并继续', cancelText: '返回编辑', onOk: next }); else next(); };
  const select = (id: string) => confirmLeave(() => { setDirty(false); setParams(old => { const next = new URLSearchParams(old); next.set('owned', id); return next; }); });
  const owned = accounts.filter(a => a.is_owned); const account = owned.find(a => a.id === selected);
  async function add() {
    setBusy(true); setError('');
    try {
      const value = existing ? await client.update<DouyinAccount>('accounts', existing, { is_owned: true }) : await client.editor.create({ source, is_owned: true, count: 20, group: '', notes: '' });
      setAdding(false); setSource(''); setExisting(undefined); setTick(v => v + 1); select(value.id);
    } catch (e) { setError(documentError(e)); } finally { setBusy(false); }
  }
  return <section className="douyin-owned douyin-form" aria-label="我的账号工作台">
    <div className="douyin-section-title"><div><h2>我的账号</h2><p>同一个你，不同的内容方向。每个账号独立保存定位与文风。</p></div><Button onClick={() => confirmLeave(() => setAdding(true))}>添加自己的账号</Button></div>
    {error && <Alert type="error" message={error} action={<Button onClick={() => { setError(''); setTick(v => v + 1); }}>重试</Button>} />}
    {loading ? <Spin /> : !owned.length ? <Empty description="添加账号，或把已有对标账号标记为自己的账号。" /> : <Field label="当前创作账号"><Select aria-label="当前创作账号" placeholder="选择自己的账号" value={account?.id} options={owned.map(a => ({ value: a.id, label: a.name || '待采集账号' }))} onChange={select} /></Field>}
    {account && <OwnedWorkspace key={account.id} client={client} account={account} onDirty={setDirty} openAccount={() => confirmLeave(() => openAccount(account.id))} />}
    <Modal title="添加自己的账号" open={adding} confirmLoading={busy} okText={existing ? '标记为我的账号' : '添加并采集20条'} onCancel={() => !busy && setAdding(false)} onOk={() => void add()} okButtonProps={{ disabled: !existing && !source.trim() }}>
      <div className="douyin-form"><Field label="选择已有账号"><Select aria-label="选择已有账号" allowClear value={existing} options={accounts.filter(a => !a.is_owned).map(a => ({ value: a.id, label: a.name || a.source_url }))} onChange={setExisting} /></Field>
        {!existing && <Field label="主页链接或分享文本"><Input.TextArea aria-label="自己的账号链接" value={source} maxLength={4000} onChange={e => setSource(e.target.value)} /></Field>}
        {error && <Alert type="error" message={error} />}
      </div>
    </Modal>
  </section>;
}

function OwnedWorkspace({ client, account, onDirty, openAccount }: { client: ResearchClient; account: DouyinAccount; onDirty: (value: boolean) => void; openAccount: () => void }) {
  const [knowledge, setKnowledge] = useState<KnowledgeSnapshot[]>([]);
  const [profile, setProfile] = useState<CreatorProfile | null>(null); const [unbound, setUnbound] = useState<CreatorProfile[]>([]); const [bindId, setBindId] = useState<string>();
  const [samples, setSamples] = useState<VoiceSample[]>([]); const [versions, setVersions] = useState<VoiceVersion[]>([]); const [materials, setMaterials] = useState<Inspiration[]>([]);
  const [tasks, setTasks] = useState<ResearchTask[]>([]); const [transcripts, setTranscripts] = useState<DouyinTask[]>([]);
  const [selectedTask, setSelectedTask] = useState(''); const [tab, setTab] = useState('samples');
  const [pollError, setPollError] = useState(''); const [pollRevision, setPollRevision] = useState(0); const [factsDirty, setFactsDirty] = useState(false); const [articleDirty, setArticleDirty] = useState(false);
  const [draft, setDraft] = useState<VoiceContent>(blankContent); const [draftSource, setDraftSource] = useState(''); const [draftDirty, setDraftDirty] = useState(false);
  const [editing, setEditing] = useState<Partial<VoiceSample> | null>(null); const [error, setError] = useState(''); const [message, setMessage] = useState(''); const [busy, setBusy] = useState(false); const [loading, setLoading] = useState(true);
  const [format, setFormat] = useState<ProductionFormat>('talking_head'); const [theme, setTheme] = useState('');
  const works = useRows<ResearchWork>(client, 'works', { account: account.id });
  const load = useCallback(async () => {
    const [profiles, allMaterials] = await Promise.all([allRows<CreatorProfile>(client, 'creator-profiles'), allRows<Inspiration>(client, 'inspirations')]);
    const current = profiles.find(p => p.account === account.id) || null;
    const [ss, vv] = current ? await Promise.all([allRows<VoiceSample>(client, 'voice-samples', { profile: current.id }), client.voiceVersions(current.id)]) : [[], []];
    setProfile(current); setUnbound(profiles.filter(p => !p.account && !p.active_version)); setMaterials(allMaterials.filter(m => m.kind === 'text')); setSamples(ss); setVersions(vv);
    return current;
  }, [client, account.id]);
  useEffect(() => { let alive = true; void load().catch(e => { if (alive) setError(documentError(e)); }).finally(() => { if (alive) setLoading(false); }); return () => { alive = false; }; }, [load]);
  useEffect(() => { onDirty(draftDirty || factsDirty || articleDirty || !!editing); return () => onDirty(false); }, [draftDirty, factsDirty, articleDirty, editing, onDirty]);
  useEffect(() => {
    let alive = true; let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const [tt, tr] = await Promise.all([allRows<ResearchTask>(client, 'tasks', { target_account: account.id }), allRows<DouyinTask>(client, `accounts/${account.id}/tasks`)]);
        if (!alive) return; setPollError(''); setTasks(tt); setTranscripts(tr.filter(t => t.kind === 'transcribe'));
        works.reload();
        if (tt.some(isActive) || tr.some(isActive)) timer = setTimeout(() => void poll(), 2500);
      } catch (e) { if (alive) { setPollError(documentError(e)); timer = setTimeout(() => void poll(), 5000); } }
    };
    void poll(); return () => { alive = false; clearTimeout(timer); };
    // Work refresh does not change the polling identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, account.id, pollRevision]);
  async function action(fn: () => Promise<void>) { setBusy(true); setError(''); setMessage(''); try { await fn(); } catch (e) { setError(documentError(e)); } finally { setBusy(false); } }
  async function run(body: Record<string, unknown>) {
    const value = await client.start({ ...body, target_account_id: account.id, ...(body.kind === 'topics' && knowledge.length ? { knowledge_cards: knowledgeSelection(knowledge) } : {}) }); setTasks(old => [value, ...old.filter(t => t.id !== value.id)]); setSelectedTask(value.id); setPollRevision(v => v + 1);
  }
  const leaveArticle = (next: () => void) => { if (articleDirty) Modal.confirm({ title: '文章有未保存的修改', content: '离开将丢弃未保存的文章修改。', okText: '丢弃并继续', cancelText: '继续编辑', onOk: next }); else next(); };
  const currentTask = tasks.find(t => t.id === selectedTask);
  const analysisTasks = tasks.filter(t => t.kind === 'voice_analysis');
  const active = versions.find(v => v.id === profile?.active_version);
  const replaceDraft = (content: VoiceContent, source = '') => {
    const apply = () => { setDraft({ ...content }); setDraftSource(source); setDraftDirty(true); setTab('voice'); };
    if (draftDirty) Modal.confirm({ title: '替换未保存的文风修改？', okText: '替换草稿', cancelText: '保留编辑', onOk: apply }); else apply();
  };
  async function transcribe(sample: VoiceSample, force = false) {
    if (!sample.work) return;
    const task = await client.editor.start(account.id, { kind: 'transcribe', work_id: sample.work, force });
    setTranscripts(old => [task, ...old.filter(t => t.id !== task.id)]);
    setPollRevision(v => v + 1);
  }
  async function importWork(work: ResearchWork) {
    if (!profile) return;
    const sample = await client.create<VoiceSample>('voice-samples', { profile: profile.id, work: work.id, title: (work.title || '未命名作品').slice(0, 300), text: '', usage: 'style' });
    await load();
    if (!sample.text && work.kind === 'video') await transcribe(sample);
  }
  async function saveDraft() {
    if (!profile) return;
    await client.confirmVoice(profile.id, { revision: profile.revision, content: draft, ...(draftSource && { source_task_id: draftSource }) });
    setDraftDirty(false); await load(); setMessage('已保存并启用新文风版本，可以开始创作。');
  }
  if (loading) return <Spin />;
  return <div className="douyin-form">
    {error && <Alert type="error" message={error} action={<Button onClick={() => void action(async () => { await load(); works.reload(); setPollRevision(v => v + 1); setMessage('资料已刷新，未保存的草稿保留。'); })}>刷新资料</Button>} />}{message && <Alert type="success" message={message} />}
    {pollError && <Alert type="warning" message={`任务状态刷新失败，正在重试：${pollError}`} action={<Button onClick={() => setPollRevision(v => v + 1)}>刷新任务状态</Button>} />}
    <div className="douyin-section-title"><h3>{account.name || '我的账号'} {active ? <Tag>当前文风 v{active.number}</Tag> : <Tag>待确认文风</Tag>}</h3><Button onClick={openAccount}>采集与作品库</Button></div>
    {!profile ? <div className="douyin-research-card douyin-form"><p>为此账号建立独立档案，不会自动继承其他账号的文风。</p><Field label="绑定已有独立档案"><Select aria-label="绑定已有独立档案" allowClear value={bindId} options={unbound.map(p => ({ value: p.id, label: p.name }))} onChange={setBindId} /></Field><Button type="primary" loading={busy} onClick={() => void action(async () => { if (bindId) { const p = unbound.find(p => p.id === bindId)!; await client.update('creator-profiles', p.id, { revision: p.revision, account: account.id }); } else await client.create('creator-profiles', { account: account.id, name: (account.name || '我的账号').slice(0, 100) }); await load(); })}>{bindId ? '绑定独立档案' : '建立账号档案'}</Button></div> : <>
      <Tabs activeKey={tab} onChange={value => leaveArticle(() => setTab(value))} items={[{ key: 'samples', label: '1 · 准备样本' }, { key: 'analysis', label: '2 · 分析定位与文风' }, { key: 'voice', label: '3 · 确认创作档案' }, { key: 'create', label: '4 · 按账号创作' }]} />
      {tab === 'samples' && <>
        <p>建议选择5—10篇代表作。数据好不一定代表你的文风；仅标题不能用于文风分析。</p>
        <div className="douyin-actions"><Button onClick={() => setEditing({ title: '', text: '', usage: 'style' })}>粘贴自己的文案</Button><Button onClick={() => void action(async () => { await load(); works.reload(); })}>刷新样本与作品</Button></div>
        <div className="douyin-owned-grid">{samples.map(s => { const t = transcripts.find(t => t.work_id === s.work); return <article className="douyin-research-card" key={s.id}><h4>{s.title}</h4><Tag>{usageOptions.find(o => o.value === s.usage)?.label}</Tag><p>{s.text ? `${s.text.slice(0, 100)}${s.text.length > 100 ? '…' : ''}` : s.work_kind === 'image_album' ? '尚无发布文案：可从已采集资料补充，或手动粘贴。' : '尚无正文：请转写或手动补充'}</p>{s.work_kind === 'image_album' && <p>图文正文使用发布文案，不含图片内文字识别。</p>}{s.source_missing && <p>来源已失效，已保存的正文保留。</p>}
          {t && <p role="status">转写：{researchTaskStatus(t)}{t.error && ` · ${t.error}`}</p>}
          <div className="douyin-actions"><Button onClick={() => setEditing(s)}>校正与用途</Button>{s.work && s.work_kind === 'video' && <Button disabled={busy || !!t && isActive(t)} onClick={() => void action(() => transcribe(s, !!t))}>{t?.status === 'failed' ? '重试转写' : '重新转写'}</Button>}
            {s.work_kind === 'image_album' && !s.text.trim() && <Button disabled={busy} onClick={() => void action(async () => { await client.update('voice-samples', s.id, { revision: s.revision, import_caption: true }); await load(); })}>补充已采集发布文案</Button>}
            {t?.status === 'succeeded' && <Button onClick={() => setEditing({ ...s, text: t.output.text || t.output.segments?.map(v => v.text).join('\n') || '', source_task: t.id })}>使用转写正文</Button>}
            {t && isActive(t) && <Button onClick={() => void action(async () => { await client.editor.cancel(account.id, t.id); })}>取消转写</Button>}
          </div></article>; })}</div>
        <h4>从已采集作品添加</h4>{works.error && <Alert type="error" message={works.error} />}{works.loading && <Spin />}
        <div className="douyin-owned-grid">{works.results.map(w => <article className="douyin-research-card" key={w.id}><h4>{w.title}</h4><p>{w.kind === 'video' ? '优先复用已有转写，缺失时开始转写。' : w.kind === 'image_album' ? '自动导入已采集的发布文案；图片内文字需另行识别。' : '添加后请手动补充正文。'}</p><Button disabled={busy || samples.some(s => s.work === w.id)} onClick={() => void action(() => importWork(w))}>{samples.some(s => s.work === w.id) ? '已添加' : '作为样本添加'}</Button></article>)}</div><Pager rows={works} />
      </>}
      {tab === 'analysis' && <>
        <p>不学习的样本会排除。尚未取得正文的作品只用于初步定位；“只参考内容”的正文不用于学习文风。</p>
        <div className="douyin-actions"><Button type="primary" loading={busy} disabled={!samples.some(s => s.usage === 'style' && s.text.trim())} onClick={() => void action(() => run({ kind: 'voice_analysis' }))}>分析有效样本的定位与文风</Button><Button disabled={busy || !samples.some(s => s.usage !== 'exclude')} onClick={() => void action(() => run({ kind: 'voice_analysis', analysis_mode: 'positioning' }))}>仅分析定位</Button></div>
        <Field label="分析历史"><Select aria-label="分析历史" value={analysisTasks.some(t => t.id === selectedTask) ? selectedTask : undefined} options={analysisTasks.map(t => ({ value: t.id, label: `${new Date(t.created_at).toLocaleString()} · ${researchTaskStatus(t)}` }))} onChange={id => leaveArticle(() => setSelectedTask(id))} /></Field>
        {currentTask?.kind === 'voice_analysis' && <div className="douyin-form"><TaskStatus client={client} task={currentTask} /><GenerationPreview key={currentTask.id} task={currentTask} />{currentTask.output.warning && <Alert type="warning" message={currentTask.output.warning} />}
          {currentTask.output.findings?.map((f, i) => <article className="douyin-research-card" key={i}><Tag>{{ positioning: '定位判断', keep: '建议保留', improve: '建议改善' }[f.category]}</Tag><p>{f.text}</p><blockquote>{f.quote}</blockquote><small>出处：{currentTask.output.voice_evidence?.find(s => s.id === f.sample_id)?.title}</small></article>)}
          {currentTask.status === 'succeeded' && currentTask.output.content && <Button type="primary" onClick={() => replaceDraft(currentTask.output.content!, currentTask.id)}>编辑分析结果并确认</Button>}
        </div>}
      </>}
      <div hidden={tab !== 'voice'}><SharedFacts client={client} profile={profile} materials={materials} onSaved={load} onDirty={setFactsDirty} /></div>
      {tab === 'voice' && <>
        <div className="douyin-actions"><Button disabled={!active} onClick={() => active && replaceDraft(active.content)}>编辑当前生效版本</Button><Button onClick={() => replaceDraft({ ...blankContent, positioning: profile.positioning, audience: profile.audience })}>手动填写新版本</Button></div>
        {draftDirty && <div className="douyin-form"><Alert type="info" message="这是未生效草稿。请核对正文依据，并使完整提示词与上方规则保持一致；生成时以确认后的完整提示词为表达要求。" />
          <div className="douyin-owned-grid">{(Object.keys(contentLabels) as (keyof VoiceContent)[]).map(key => <Field key={key} label={contentLabels[key]}><Input.TextArea aria-label={contentLabels[key]} rows={key === 'prompt' ? 12 : 4} maxLength={20000} value={draft[key]} onChange={e => setDraft({ ...draft, [key]: e.target.value })} /></Field>)}</div>
          <div className="douyin-actions"><Button onClick={() => setDraft({ ...draft, prompt: (['positioning', 'audience', 'rules', 'examples', 'avoid'] as const).map(k => `【${contentLabels[k]}】\n${draft[k]}`).join('\n\n') + '\n\n【真实素材约束】\n只使用明确提供的事实和经历，不编造；保留个人特点，精简空话与重复。\n\n【本次任务】\n遵循本次主题、内容支柱、内容边界、时长与制作条件。' })}>按当前规则重建提示词</Button><Button type="primary" loading={busy} disabled={factsDirty || !draft.positioning.trim() || !draft.prompt.trim()} onClick={() => void action(saveDraft)}>确认并启用新版本</Button><Button onClick={() => { setDraftDirty(false); setDraftSource(''); }}>丢弃草稿</Button></div>{factsDirty && <p>请先保存素材设置，再确认新版本。</p>}
        </div>}
        {versions.map(v => <article className="douyin-research-card" key={v.id}><h4>文风 v{v.number} {v.id === profile.active_version && <Tag>生效中</Tag>}</h4><p>{v.content.positioning}</p><details><summary>查看完整提示词与依据</summary><pre className="douyin-owned-prompt">{v.content.prompt}</pre>{v.evidence.map(e => <details key={e.id}><summary>{e.title}</summary><p className="douyin-owned-prompt">{e.text || '仅标题资料'}</p></details>)}</details><div className="douyin-actions"><Button onClick={() => replaceDraft(v.content)}>以此版本编辑</Button><Button onClick={() => void action(async () => { if (!navigator.clipboard?.writeText) throw new Error('当前环境不支持自动复制，请展开提示词后手动选择复制。'); await navigator.clipboard.writeText(v.content.prompt); setMessage('提示词已复制'); })}>复制提示词</Button><Button disabled={busy || profile.active_version === v.id || draftDirty || factsDirty} onClick={() => void action(async () => { await client.activateVoice(profile.id, v.id, profile.revision); await load(); setMessage(`已启用文风 v${v.number}`); })}>启用此版本</Button></div></article>)}
      </>}
      {tab === 'create' && <>
        {!active ? <Alert type="info" message="请先确认并启用一个定位与文风版本。" /> : <p>为「{account.name}」创作 · 文风 v{active.number}。选题及后续脚本使用提交时的版本。</p>}
        <Field label="本次主题（可选）"><Input.TextArea aria-label="本次主题（可选）" value={theme} maxLength={2000} placeholder="留空时，根据账号定位推荐下一条内容" onChange={e => setTheme(e.target.value)} /></Field>
        <KnowledgePicker key={account.id} client={client} query={[theme, active?.content.positioning, active?.content.audience].filter(Boolean).join(' ')} selected={knowledge} onChange={setKnowledge} />
        <Field label="视频形式"><Select aria-label="我的账号视频形式" value={format} options={Object.entries(productionFormats).map(([value, f]) => ({ value, label: f.label }))} onChange={setFormat} /></Field>
        <Button type="primary" disabled={!active || busy || articleDirty} onClick={() => void action(() => run({ kind: 'topics', theme, production_format: format, duration: 60 }))}>生成3个账号专属选题</Button>
        <Field label="此账号的创作历史"><Select aria-label="此账号的创作历史" value={tasks.some(t => t.id === selectedTask && ['topics', 'script', 'article'].includes(t.kind)) ? selectedTask : undefined} options={tasks.filter(t => ['topics', 'script', 'article'].includes(t.kind)).map(t => ({ value: t.id, label: `${t.kind === 'topics' ? '选题' : t.kind === 'article' ? '文章' : '脚本'} · ${new Date(t.created_at).toLocaleString()} · ${researchTaskStatus(t)}` }))} onChange={id => leaveArticle(() => setSelectedTask(id))} /></Field>
        {currentTask && ['topics', 'script', 'article'].includes(currentTask.kind) && <><TaskStatus client={client} task={currentTask} /><ResearchResult key={currentTask.id} client={client} task={currentTask} run={run} onDirty={setArticleDirty} /></>}
      </>}
    </>}
    <Modal className="douyin-owned-modal" title="样本文案与用途" open={!!editing} confirmLoading={busy} onCancel={() => setEditing(null)} okText="保存样本" okButtonProps={{ disabled: !editing?.title?.trim() || (!editing?.work && !editing?.text?.trim()) }} onOk={() => void action(async () => { if (!profile || !editing) return; const body = { profile: profile.id, title: editing.title, text: editing.text, usage: editing.usage, source_task: editing.source_task || null, ...(editing.id && { revision: editing.revision }) }; if (editing.id) await client.update('voice-samples', editing.id, body); else await client.create('voice-samples', body); setEditing(null); await load(); })}>
      {editing && <div className="douyin-form"><Field label="样本标题"><Input aria-label="样本标题" value={editing.title} maxLength={300} onChange={e => setEditing({ ...editing, title: e.target.value })} /></Field><Field label="学习用途"><Select aria-label="学习用途" options={usageOptions} value={editing.usage} onChange={usage => setEditing({ ...editing, usage })} /></Field><Field label="正文或校正后的转写"><Input.TextArea aria-label="正文或校正后的转写" rows={12} maxLength={20000} value={editing.text} onChange={e => setEditing({ ...editing, text: e.target.value })} /></Field>{error && <Alert type="error" message={error} />}</div>}
    </Modal>
  </div>;
}

function TaskStatus({ client, task }: { client: ResearchClient; task: ResearchTask }) {
  const [error, setError] = useState('');
  return <div role="status"><p>{researchTaskStatus(task)}</p>{isActive(task) && <><Spin size="small" /><Button onClick={() => { void client.cancel(task.id).catch(e => setError(documentError(e))); }}>取消任务</Button></>}{(task.error || error) && <Alert type="error" message={task.error || error} />}{task.status === 'cancelled' && <p>已取消，已保存的样本和文风版本保留。</p>}</div>;
}

function SharedFacts({ client, profile, materials, onSaved, onDirty }: { client: ResearchClient; profile: CreatorProfile; materials: Inspiration[]; onSaved: () => Promise<unknown>; onDirty: (value: boolean) => void }) {
  const [selected, setSelected] = useState(profile.shared_inspiration_ids || []); const [experiences, setExperiences] = useState(profile.experiences); const [products, setProducts] = useState(profile.products); const [conditions, setConditions] = useState(profile.conditions); const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  useEffect(() => { onDirty(JSON.stringify(selected) !== JSON.stringify(profile.shared_inspiration_ids || []) || experiences !== profile.experiences || products !== profile.products || conditions !== profile.conditions); return () => onDirty(false); }, [selected, experiences, products, conditions, profile, onDirty]);
  return <details><summary>账号真实素材与拍摄条件（用于下次确认的版本）</summary><div className="douyin-form"><p>共享素材来自选题库的文本灵感，仅引用你为此账号勾选的条目。</p><Field label="允许引用的共享素材"><Select aria-label="允许引用的共享素材" mode="multiple" value={selected} options={materials.map(m => ({ value: m.id, label: m.title }))} onChange={setSelected} /></Field>{[['账号专属经历', experiences, setExperiences], ['账号专属产品事实', products, setProducts], ['拍摄条件', conditions, setConditions]].map(([label, value, setter]) => <Field key={String(label)} label={String(label)}><Input.TextArea aria-label={String(label)} value={String(value)} maxLength={20000} onChange={e => (setter as (v: string) => void)(e.target.value)} /></Field>)}{error && <Alert type="error" message={error} />}<Button loading={busy} onClick={() => { setBusy(true); void client.update('creator-profiles', profile.id, { revision: profile.revision, shared_inspiration_ids: selected, experiences, products, conditions }).then(onSaved).catch(e => setError(documentError(e))).finally(() => setBusy(false)); }}>保存素材设置</Button></div></details>;
}
