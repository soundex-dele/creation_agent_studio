import { useCallback, useEffect, useState } from 'react';
import { Alert, Button, Checkbox, Empty, Input, InputNumber, Modal, Progress, Select, Spin, Tabs, Tag, Upload } from 'antd';
import { ChartNoAxesCombined, Clapperboard, Film, NotebookPen, RefreshCw, ScanSearch, UsersRound } from 'lucide-react';
import { type Brief, type DouyinAccount, type DouyinClient, type DouyinTask, type WorkResult, type Kind, type ProductionFormat, productionFormats, kindLabels, isActive, metric } from '@/services/douyinBenchmark';
import { documentError } from '@/services/documents';
import { AnalysisResult } from './AnalysisResult';
import { ScriptEditor } from './ScriptEditor';
import { RewritePanel } from './RewritePanel';

export function DouyinWorkspace({ client, accountId, onRemoved }: { client: DouyinClient; accountId: string; onRemoved: () => void }) {
  const [account, setAccount] = useState<DouyinAccount | null>(null); const [tasks, setTasks] = useState<DouyinTask[]>([]);
  const [taskPage, setTaskPage] = useState(1); const [taskCount, setTaskCount] = useState(0);
  const [works, setWorks] = useState<WorkResult | null>(null); const [tab, setTab] = useState('account');
  const [selectedId, setSelectedId] = useState(''); const [selectedTask, setSelectedTask] = useState<DouyinTask | null>(null);
  const [search, setSearch] = useState(''); const [sort, setSort] = useState('likes'); const [outstanding, setOutstanding] = useState(false); const [batchId, setBatchId] = useState<string | undefined>();
  const [count, setCount] = useState(50); const [busy, setBusy] = useState(false); const [loading, setLoading] = useState(true); const [error, setError] = useState('');
  const [refresh, setRefresh] = useState(0); const [editing, setEditing] = useState(false); const [deleting, setDeleting] = useState(false);
  const [notes, setNotes] = useState({ group: '', notes: '' }); const [brands, setBrands] = useState<{ id: string; name: string }[]>([]);
  const [brief, setBrief] = useState<Brief>({ production_format: 'talking_head', positioning: '', audience: '', theme: '', duration: 60, conditions: '' }); const [source, setSource] = useState('');
  useEffect(() => { let active = true; void client.brands().then((rows) => { if (active) setBrands(rows); }).catch(() => { /* Brand reference is optional; ordinary creation remains available. */ }); return () => { active = false; }; }, [client]);
  useEffect(() => {
    let active = true; let timer: ReturnType<typeof setTimeout>;
    const load = async () => {
      try {
        const [a, t, w] = await Promise.all([client.account(accountId), client.tasks(accountId), client.works(accountId, { batch_id: batchId, search, sort, outstanding })]);
        if (!active) return;
        setAccount(a); setWorks(w); setTaskCount(t.count);
        setTasks((old) => [...t.results, ...old.filter((x) => !t.results.some((n) => n.id === x.id))]);
        if (t.results.some(isActive)) timer = setTimeout(() => void load(), 3000);
      } catch (e) { if (active) setError(documentError(e)); }
      finally { if (active) setLoading(false); }
    };
    setError(''); void load();
    return () => { active = false; clearTimeout(timer); };
  }, [client, accountId, batchId, search, sort, outstanding, refresh]);
  useEffect(() => {
    if (!selectedId) { setSelectedTask(null); return; }
    let active = true; let timer: ReturnType<typeof setTimeout>;
    setSelectedTask(null);
    const poll = async () => {
      try {
        const value = await client.task(accountId, selectedId);
        if (!active) return;
        setSelectedTask(value);
        if (isActive(value)) timer = setTimeout(() => void poll(), 2000);
      } catch (e) { if (active) setError(documentError(e)); }
    };
    void poll(); return () => { active = false; clearTimeout(timer); };
  }, [client, accountId, selectedId, refresh]);
  const run = useCallback(async (body: { kind: Kind; [key: string]: unknown }) => {
    setBusy(true); setError('');
    try {
      const task = await client.start(accountId, body);
      setTasks(old => [task, ...old.filter(item => item.id !== task.id)]); setSelectedId(task.id); setRefresh((v) => v + 1);
      setTab(['transcribe', 'rewrite'].includes(body.kind) ? 'rewrite' : body.kind === 'collect' ? 'works' : body.kind === 'account' ? 'account' : body.kind === 'breakdown' ? 'breakdown' : 'create');
    } catch (e) { setError(documentError(e)); }
    finally { setBusy(false); }
  }, [client, accountId]);
  const activeCollection = tasks.some((t) => t.kind === 'collect' && isActive(t));
  const taskOptions = tasks.filter((t) => tab === 'rewrite' ? ['transcribe', 'rewrite'].includes(t.kind) : tab === 'account' ? t.kind === 'account' : tab === 'works' ? t.kind === 'collect' : tab === 'breakdown' ? t.kind === 'breakdown' : ['topics', 'script'].includes(t.kind));
  const visibleTask = selectedTask && taskOptions.some((t) => t.id === selectedTask.id) ? selectedTask : null;
  return <section className="douyin-panel douyin-workspace">
    {error && <Alert type="error" message={error} action={<Button onClick={() => setRefresh((v) => v + 1)}>重新加载</Button>} />}
    {loading && !account ? <div className="douyin-loading" role="status"><Spin /><span>正在打开账号工作台…</span></div> : account && <>
      <div className="douyin-section-title"><div><h2>{account.name || '待采集账号'}</h2><p>{account.profile.signature}</p><Tag>{account.group || '未分组'}</Tag></div><div className="douyin-actions"><a href={account.source_url} target="_blank" rel="noreferrer">打开主页</a><Button onClick={() => { setNotes({ group: account.group, notes: account.notes }); setEditing(true); }}>编辑备注</Button><Button danger onClick={() => setDeleting(true)}>移除账号</Button></div></div>
      <div className="douyin-toolbar douyin-collection-bar"><Select aria-label="刷新采集数量" value={count} options={[20, 50, 100].map((v) => ({ value: v, label: `最近 ${v} 条` }))} onChange={setCount} /><Button icon={<RefreshCw size={15} aria-hidden="true" />} loading={busy} disabled={activeCollection} onClick={() => void run({ kind: 'collect', count })}>{activeCollection ? '正在采集' : '刷新作品数据'}</Button><small>添加时采集，之后由你手动刷新</small></div>
      <Tabs className="douyin-tabs" activeKey={tab} onChange={setTab} items={[{ key: 'account', label: '对标账号', icon: <UsersRound size={16} aria-hidden="true" /> }, { key: 'works', label: '作品库', icon: <Film size={16} aria-hidden="true" /> }, { key: 'breakdown', label: '视频拆解', icon: <ScanSearch size={16} aria-hidden="true" /> }, { key: 'rewrite', label: '爆款复刻', icon: <NotebookPen size={16} aria-hidden="true" /> }, { key: 'create', label: '脚本创作', icon: <NotebookPen size={16} aria-hidden="true" /> }]} />
      {tab === 'account' && <div className="douyin-guide"><span className="douyin-guide-icon"><ChartNoAxesCombined size={26} aria-hidden="true" /></span><div><h3>从作品样本，看懂账号的内容方向</h3><p className="douyin-hint">{account.notes || '记录你想学习的内容方向、表达特点或拍摄方法。'}</p><Button type="primary" disabled={busy || !works?.items.length} onClick={() => void run({ kind: 'account', ...(works?.batch ? { batch_id: works.batch.id } : {}) })}>分析当前批次账号</Button><p className="douyin-footnote">分析只覆盖已采集样本，标题判断会标记为初步推测。</p></div></div>}
      {tab === 'works' && <>
        <div className="douyin-toolbar"><Input.Search aria-label="筛选作品标题" value={search} placeholder="筛选作品标题" onChange={(e) => setSearch(e.target.value)} /><Select aria-label="历史采集批次" value={batchId || ''} onChange={(v) => setBatchId(v || undefined)} options={[{ value: '', label: '最新有数据的批次' }, ...tasks.filter((t) => t.kind === 'collect').map((t) => ({ value: t.id, label: new Date(t.created_at).toLocaleString('zh-CN') }))]} /><Select aria-label="作品排序" value={sort} onChange={setSort} options={[['likes', '点赞'], ['comments', '评论'], ['collects', '收藏'], ['shares', '分享'], ['published_at', '发布时间'], ['ratio', '突出倍数']].map(([value, label]) => ({ value, label: `按${label}排序` }))} /><Checkbox checked={outstanding} onChange={(e) => setOutstanding(e.target.checked)}>只看表现突出</Checkbox></div>
        <Alert type="info" message={works?.explanation || '等待作品数据'} />
        {works?.batch && <p>本批次 {works.batch.output.actual ?? works.items.length} / {works.batch.output.requested ?? '—'} 条 · {works.batch.output.complete ? '本次数量已采集完成或已到末页' : '部分数据'} · {new Date(works.batch.output.captured_at || works.batch.created_at).toLocaleString('zh-CN')}{works.batch.output.warning && <span> · {works.batch.output.warning}</span>}</p>}
        {!works?.items.length ? <Empty description="暂无匹配作品，请采集或调整筛选条件。" /> : <div className="douyin-work-list">{works.items.map((w) => <article className="douyin-work" key={w.id}>
          {w.cover ? <img loading="lazy" referrerPolicy="no-referrer" src={w.cover} alt={`${w.title} 封面`} /> : <div className="douyin-cover-placeholder" aria-hidden="true"><Film size={26} /><span>暂无封面</span></div>}
          <div className="douyin-work-body"><h3>{w.title || '未命名作品'}</h3><div className="douyin-actions">{w.kind === 'video' && (w.video_url ? <a href={w.video_url} target="_blank" rel="noreferrer">播放视频</a> : <small>刷新作品数据以获取视频地址</small>)}<a href={w.url} target="_blank" rel="noreferrer">抖音来源页</a>{w.kind === 'image_album' && <Tag>图文作品</Tag>}</div><small>{w.published_at ? new Date(w.published_at).toLocaleDateString('zh-CN') : '发布时间未获取'} · {w.duration == null ? '时长未获取' : `${w.duration.toFixed(1)}秒`}</small>
            <dl>{([['likes', '赞'], ['comments', '评'], ['collects', '藏'], ['shares', '转']] as const).map(([key, label]) => <div key={key}><dt>{label}</dt><dd>{metric(w[key])}</dd></div>)}</dl>
            {w.ratio != null && <Tag color={w.outstanding ? 'gold' : undefined}>{w.outstanding ? '表现突出 · ' : ''}{w.ratio} 倍</Tag>}
          </div><div className="douyin-work-actions"><Button disabled={busy || w.kind !== 'video'} onClick={() => void run({ kind: 'transcribe', work_id: w.id })}>爆款复刻</Button><Button type="primary" disabled={busy || w.kind === 'image_album'} onClick={() => void run({ kind: 'breakdown', work_id: w.id })}>转写并拆解</Button><Upload showUploadList={false} accept="video/*" beforeUpload={(file) => { setBusy(true); setError(''); void client.upload(accountId, w.id, file).then(() => setRefresh((v) => v + 1)).catch((e) => setError(documentError(e))).finally(() => setBusy(false)); return false; }}><Button disabled={busy}>{w.has_upload ? '替换补传视频' : '补传原视频'}</Button></Upload></div>
        </article>)}</div>}
      </>}
      {tab === 'breakdown' && <div className="douyin-guide"><span className="douyin-guide-icon"><Clapperboard size={26} aria-hidden="true" /></span><div><h3>拆开一条视频，理解它的表达方式</h3><p className="douyin-hint">在作品库中选择视频开始拆解，或在下方打开历史成果。最多抽取16帧，结论可以逐条核对出处。</p><Button onClick={() => setTab('works')}>前往作品库</Button></div></div>}
      {tab === 'rewrite' && !visibleTask && <div className="douyin-guide"><div><h3>把好内容，改写成自然的新表达</h3><p>从作品库选择视频，自动转写后校正原文，再生成同主题文案；也可以打开下方历史任务继续。</p><Button onClick={() => setTab('works')}>前往作品库</Button></div></div>}
      {tab === 'create' && <div className="douyin-form">
        <fieldset className="douyin-format-field"><legend>视频形式</legend><div className="douyin-format-options">
          {(Object.entries(productionFormats) as [ProductionFormat, typeof productionFormats[ProductionFormat]][]).map(([value, option]) => <label key={value} className={brief.production_format === value ? 'is-selected' : ''}><input type="radio" name="production-format" value={value} checked={brief.production_format === value} onChange={() => setBrief({ ...brief, production_format: value })} /><span><strong>{option.label}</strong><small>{option.hint}</small></span></label>)}
        </div><p className="douyin-footnote">新选题会保存所选形式，后续分镜沿用该选题的形式。更换形式后请重新生成选题。</p></fieldset>
        <label>参考拆解<Select aria-label="参考拆解" value={source || undefined} placeholder="选择已完成的视频拆解" options={tasks.filter((t) => t.kind === 'breakdown' && t.status === 'succeeded').map((t) => ({ value: t.id, label: `${new Date(t.created_at).toLocaleString('zh-CN')} · ${t.work_id?.slice(0, 8)}` }))} onChange={setSource} /></label>
        <div className="douyin-form-grid">{(['positioning', 'audience', 'theme', 'conditions'] as const).map((field) => <label key={field}>{({ positioning: '我的账号定位', audience: '目标受众', theme: '本次主题', conditions: '拍摄条件与真实经历' })[field]}<Input.TextArea aria-label={field} maxLength={field === 'conditions' ? 3000 : 2000} rows={3} value={brief[field]} onChange={(e) => setBrief({ ...brief, [field]: e.target.value })} /></label>)}</div>
        <div className="douyin-toolbar"><label>目标时长（秒）<InputNumber aria-label="目标时长" min={15} max={brief.production_format === 'animation' ? 120 : 600} value={brief.duration} onChange={(value) => setBrief({ ...brief, duration: value || 60 })} /></label><label>品牌定位与语气（可选）<Select aria-label="引用品牌资料" allowClear value={brief.brand_profile_id || undefined} options={brands.map((b) => ({ value: b.id, label: b.name }))} onChange={(value) => setBrief({ ...brief, brand_profile_id: value || null })} /></label></div>
        {brief.production_format === 'animation' && <Alert type={brief.duration > 120 ? 'warning' : 'info'} message="动画演示最多 30 个分镜、120 秒，可在脚本保存后导入动画制作。" />}
        <Button type="primary" loading={busy} disabled={!source || !brief.positioning.trim() || !brief.theme.trim() || (brief.production_format === 'animation' && brief.duration > 120)} onClick={() => void run({ kind: 'topics', source_task_id: source, ...brief })}>生成 3 个选题方向</Button>
      </div>}
      <div className="douyin-history"><h3>历史{tab === 'rewrite' ? '文案转写与复刻' : tab === 'create' ? '选题与脚本' : tab === 'works' ? '采集任务' : tab === 'account' ? '账号分析' : '视频拆解'}</h3><Select aria-label="历史任务" placeholder="选择历史任务" value={visibleTask?.id} options={taskOptions.map((t) => ({ value: t.id, label: `${kindLabels[t.kind]} · ${new Date(t.created_at).toLocaleString('zh-CN')} · ${t.stage}` }))} onChange={setSelectedId} />{tasks.length < taskCount && <Button onClick={() => { void client.tasks(accountId, taskPage + 1).then((data) => { setTasks((old) => [...old, ...data.results.filter((t) => !old.some((v) => v.id === t.id))]); setTaskPage((p) => p + 1); }).catch((e) => setError(documentError(e))); }}>加载更早记录</Button>}</div>
      {visibleTask && <section className="douyin-task"><div className="douyin-section-title"><h3>{kindLabels[visibleTask.kind]} · {visibleTask.stage}</h3>{isActive(visibleTask) && <Button onClick={() => { void client.cancel(accountId, visibleTask.id).then(() => setRefresh((v) => v + 1)).catch((e) => setError(documentError(e))); }}>取消任务</Button>}</div>
        {visibleTask.kind === 'transcribe' && visibleTask.status !== 'succeeded' && <p>来源作品：{visibleTask.copy_context?.work_title || '未命名作品'}</p>}
        <div role="status" aria-live="polite">{isActive(visibleTask) && <><Spin size="small" /> 正在处理，可离开页面后回来查看</>}{visibleTask.status === 'cancelled' && '任务已取消，之前的成果仍保留。'}</div>
        {visibleTask.progress.total != null && visibleTask.progress.total > 0 && <Progress percent={Math.min(100, Math.round((visibleTask.progress.current || 0) / visibleTask.progress.total * 100))} />}
        {visibleTask.error && <Alert type="error" message={visibleTask.error} />}
        {visibleTask.output.production_format && <Tag>视频形式：{productionFormats[visibleTask.output.production_format]?.label}</Tag>}
        {visibleTask.kind === 'collect' && <p>已获取 {visibleTask.output.actual ?? visibleTask.progress.current ?? 0} 条。{visibleTask.output.warning}</p>}
        {['account', 'breakdown'].includes(visibleTask.kind) && <AnalysisResult key={visibleTask.id} client={client} accountId={accountId} task={visibleTask} />}
        {visibleTask.kind === 'breakdown' && visibleTask.status === 'succeeded' && <Button type="primary" onClick={() => { setSource(visibleTask.id); setTab('create'); }}>用这份拆解创作</Button>}
        {visibleTask.kind === 'topics' && visibleTask.output.topics && <div className="douyin-account-grid">{visibleTask.output.topics.map((topic, index) => <article className="douyin-topic" key={index}><h3>{topic.title}</h3><p>{topic.angle}</p><blockquote>{topic.hook}</blockquote><Button disabled={busy || visibleTask.status !== 'succeeded'} onClick={() => void run({ kind: 'script', source_task_id: visibleTask.id, topic_index: index })}>选择并生成拍摄脚本</Button></article>)}</div>}
        {visibleTask.kind === 'transcribe' && visibleTask.status !== 'succeeded' && !isActive(visibleTask) && <Button disabled={busy} onClick={() => void run({ kind: 'transcribe', work_id: visibleTask.work_id, force: true })}>重试转写</Button>}
        {(visibleTask.kind === 'rewrite' || (visibleTask.kind === 'transcribe' && visibleTask.status === 'succeeded')) && <RewritePanel key={visibleTask.id} client={client} accountId={accountId} task={visibleTask} busy={busy} onRun={run} />}
        {visibleTask.kind === 'script' && visibleTask.status === 'succeeded' && <ScriptEditor key={visibleTask.id} client={client} accountId={accountId} taskId={visibleTask.id} />}
      </section>}
      <Modal className="douyin-modal" open={editing} title="账号备注" onCancel={() => setEditing(false)} confirmLoading={busy} onOk={() => { setBusy(true); void client.save(accountId, notes).then((a) => { setAccount(a); setEditing(false); }).catch((e) => setError(documentError(e))).finally(() => setBusy(false)); }}><div className="douyin-form"><label>分组<Input value={notes.group} maxLength={100} onChange={(e) => setNotes({ ...notes, group: e.target.value })} /></label><label>备注<Input.TextArea rows={6} value={notes.notes} maxLength={5000} onChange={(e) => setNotes({ ...notes, notes: e.target.value })} /></label></div></Modal>
      <Modal title="移除对标账号" open={deleting} okText="移除账号" okButtonProps={{ danger: true }} onCancel={() => setDeleting(false)} onOk={() => { void client.remove(accountId).then(onRemoved).catch((e) => setError(documentError(e))); }}><p>将删除该账号的作品数据、分析和脚本历史，并取消正在执行的任务。已导出的文件保留。</p></Modal>
    </>}
  </section>;
}
