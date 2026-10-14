import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Button, Empty, Input, Pagination, Spin, Tag } from 'antd';
import { AppstoreOutlined, BulbOutlined, CalendarOutlined, LineChartOutlined, PlusOutlined, SoundOutlined } from '@ant-design/icons';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { tenantApiRoot } from '@/services/tenantContext';
import { resolveApplicationPresentation } from '@/lib/applicationPresentation';
import BrandReferencePicker from '@/components/BrandReferencePicker';
import type { BrandSelection } from '@/services/brandLibrary';
import { promotionApi, promotionError, activeTask, platforms, statuses, directions, materialTypes, broadExplorationFocuses, explorationFocuses, explorationFocusDescriptions, materialType, sourceIds, resources, string, type PromotionRecord, type Resource, type Task, type Report, type Data, type Destination, type Handoff, type Group } from '@/services/projectPromotion';
import { Choice, Field, MaterialPicker, RecordEditor, VersionEditor, caseFields, type Library } from './promotion/Editors';
import './ProjectPromotionPage.css';
import TaskActivity, { TaskRecord } from './promotion/TaskActivity';
import type { SourceSnapshot } from '@/services/projectPromotion';

const navigation = [
  { id: 'cases', name: '项目素材库', icon: AppstoreOutlined }, { id: 'topics', name: '选题与创作', icon: BulbOutlined },
  { id: 'channels', name: '发布看板', icon: CalendarOutlined }, { id: 'feedback', name: '反馈复盘', icon: LineChartOutlined },
] as const;
const tasksLabels: Record<string, string> = { project: '探索项目', case: '整理素材', topics: '策划选题', copy: '生成渠道内容', review: '反馈复盘' };
const initialLibrary = (): Library => ({ cases: [], topics: [], channels: [], feedback: [] });
const brandConfig = { enabled: true, default_modules: ['positioning', 'voice'] as ('positioning' | 'voice')[], fields: {} };

function Metrics({ groups, channel }: { groups: Group[]; channel?: boolean }) {
  return <div className="promotion-grid">{groups.map(g => <article className="promotion-card" key={g.key}><h3>{channel ? platforms[g.label] || g.label : g.label}</h3><p className="promotion-muted">{g.publications} 条已发布内容</p><dl className="promotion-metrics">{Object.entries({ views: '阅读／播放', interactions: '互动', inquiries: '私信咨询' }).map(([key, label]) => <div key={key}><dt>{label}</dt><dd>{g.metrics[key].total ?? '未记录'}</dd><small>{g.metrics[key].samples} 条有数据</small></div>)}</dl></article>)}</div>;
}

export function ProjectPromotionWorkspace({ base, root }: { base: string; root: string }) {
  const api = useMemo(() => promotionApi(base), [base]); const [params, setParams] = useSearchParams();
  const tab = (resources.includes(params.get('tab') as Resource) ? params.get('tab') : 'cases') as Resource;
  const [library, setLibrary] = useState<Library>(initialLibrary); const [tasks, setTasks] = useState<Task[]>([]); const taskRef = useRef(tasks); taskRef.current = tasks;
  const [report, setReport] = useState<Report | null>(null); const [destinations, setDestinations] = useState<Destination[]>([]); const [handoffs, setHandoffs] = useState<Handoff[]>([]);
  const [revision, setRevision] = useState(0); const reload = useCallback(() => setRevision(v => v + 1), []);
  const [loading, setLoading] = useState(true); const [error, setError] = useState(''); const [notice, setNotice] = useState(''); const [busy, setBusy] = useState(false); const busyRef = useRef(false);
  const [editor, setEditor] = useState<{ kind: Resource; row?: PromotionRecord; initial?: Data }>(); const [copy, setCopy] = useState<PromotionRecord>();
  const [search, setSearch] = useState(''); const [status, setStatus] = useState(''); const [platform, setPlatform] = useState(''); const [page, setPage] = useState(1); const [archived, setArchived] = useState(false);
  const [caseIds, setCaseIds] = useState<string[]>([]); const [materialFilter, setMaterialFilter] = useState(''); const [focus, setFocus] = useState('all'); const [instruction, setInstruction] = useState(''); const [brand, setBrand] = useState<BrandSelection | null>(null);
  const [projectMode, setProjectMode] = useState('overview'); const projectForm = useRef<HTMLElement>(null);
  const [projectPath, setProjectPath] = useState(''); const [projectDirection, setProjectDirection] = useState('');
  const [incoming, setIncoming] = useState<{ handoff: Handoff; messages: { id: number; content: string; created_at: string }[] }>();
  useEffect(() => {
    let alive = true;
    Promise.all([Promise.all(resources.map(async kind => [kind, await api.all<PromotionRecord>(kind)] as const)), api.all<Task>('ai/tasks'), api.report(), api.destinations(), api.handoffs()])
      .then(([rows, results, stats, targets, transfers]) => { if (alive) { setLibrary(Object.fromEntries(rows) as Library); setTasks(results); setReport(stats); setDestinations(targets); setHandoffs(transfers); } })
      .catch(e => { if (alive) setError(promotionError(e)); }).finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [api, revision]);
  const hasActive = tasks.some(activeTask);
  useEffect(() => {
    if (!hasActive) return;
    let alive = true; let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const items = await api.all<Task>('ai/tasks'); if (!alive) return;
        const completed = items.some(t => !activeTask(t) && taskRef.current.some(old => old.id === t.id && activeTask(old)));
        setTasks(items); if (completed) reload(); if (!items.some(activeTask)) return;
      } catch (e) { if (alive) setError(promotionError(e)); }
      if (alive) timer = setTimeout(() => void poll(), 3000);
    }
    timer = setTimeout(() => void poll(), 3000); return () => { alive = false; clearTimeout(timer); };
  }, [api, hasActive, reload]);
  async function action(fn: () => Promise<void>) {
    if (busyRef.current) return;
    busyRef.current = true; setBusy(true); setError(''); setNotice('');
    try { await fn(); reload(); } catch (e) { setError(promotionError(e)); } finally { busyRef.current = false; setBusy(false); }
  }
  async function start(value: Data) {
    await action(async () => { const task = await api.start(value); setTasks(old => [task, ...old.filter(t => t.id !== task.id)]); setNotice('生成任务已提交，结果将保存在下方生成记录中。'); });
  }
  function switchTab(next: Resource) { const p = new URLSearchParams(params); p.set('tab', next); setParams(p, { replace: true }); setPage(1); setStatus(''); setSearch(''); setPlatform(''); setMaterialFilter(''); }
  function taskInput(kind: string, extra: Data = {}) { return { kind, instruction, brand_reference: brand?.reference || null, ...extra }; }
  const selected = library[tab].filter(row => row.archived === archived && (!search || row.title.toLowerCase().includes(search.toLowerCase())) && (!status || row.status === status) && (!platform || row.platform === platform) && (tab !== 'cases' || !materialFilter || materialType(row) === materialFilter));
  const currentPage = Math.max(1, Math.min(page, Math.ceil(selected.length / 12))); const visible = selected.slice((currentPage - 1) * 12, currentPage * 12);
  const usableSelection = caseIds.length > 0 && caseIds.every(id => library.cases.some(c => c.id === id && c.status === 'confirmed' && !c.archived));
  const topicById = Object.fromEntries(library.topics.map(t => [t.id, t]));
  const caseById = Object.fromEntries(library.cases.map(c => [c.id, c]));
  return <div className="promotion-page app-scroll-page"><div className="promotion-container">
    <header className="promotion-header"><div><span className="promotion-eyebrow"><SoundOutlined aria-hidden /> PROJECT STORIES</span><h1>项目宣传助手</h1><p className="promotion-muted">把真实能力讲清楚，让合适的人看见。</p></div><div className="promotion-header-side">{resolveApplicationPresentation(params).showApplicationHeader && <Link to="/apps">应用中心</Link>}<div className="promotion-summary"><strong>{library.cases.filter(c => c.status === 'confirmed' && !c.archived).length}</strong><span>已确认素材</span><strong>{library.channels.filter(c => c.status === 'published' && !c.archived).length}</strong><span>已发布内容</span></div></div></header>
    <nav className="promotion-nav" aria-label="宣传工作流程">{navigation.map((n, i) => <button key={n.id} type="button" aria-current={tab === n.id ? 'page' : undefined} onClick={() => switchTab(n.id)}><n.icon aria-hidden /><span>{String(i + 1).padStart(2, '0')} · {n.name}</span></button>)}</nav>
    {error && <Alert type="error" role="alert" message={error} action={<Button onClick={() => { setError(''); reload(); }}>重新加载</Button>} />}{notice && <Alert type="success" role="status" message={notice} closable onClose={() => setNotice('')} />}
    {loading ? <div className="promotion-loading"><Spin /><p>正在载入宣传工作区…</p></div> : <>
      <section className="promotion-intro"><div><span className="promotion-eyebrow">{tab === 'cases' ? 'STORY BANK' : tab === 'topics' ? 'EDITORIAL DESK' : tab === 'channels' ? 'PUBLISHING BOARD' : 'LEARN & ITERATE'}</span><h2>{tab === 'cases' ? '先整理项目事实，再决定怎样讲' : tab === 'topics' ? '组合真实素材，找到值得讲的选题' : tab === 'channels' ? '让准备好的内容真正发出去' : '从真实反馈里，找到下一期内容'}</h2><p className="promotion-muted">{tab === 'cases' ? '从项目定位、人群、场景、功能、流程、技术、交付与演进等维度积累素材。核对事实后再用于创作。' : tab === 'topics' ? '选题决定面向谁、讲什么观点；可引用多份素材。确认后分别创建公众号、小红书、抖音与朋友圈的渠道任务。' : tab === 'channels' ? '各渠道独立保存版本、安排日期和登记发布。发布操作由你完成。' : '登记观察当天的累计数据，匿名摘录咨询问题。未知数据与未知来源可以留空。'}</p></div><Button type="primary" icon={<PlusOutlined aria-hidden />} onClick={() => setEditor({ kind: tab })}>{tab === 'cases' ? '新增素材' : tab === 'topics' ? '新增选题' : tab === 'channels' ? '新增渠道任务' : '记录反馈'}</Button></section>
      {tab === 'cases' && <section ref={projectForm} className="promotion-card" aria-label="从项目生成素材"><h2>填入项目路径，让 AI 发现可展示的能力</h2>
        <p className="promotion-muted">填写后端运行机器上的 Git 项目目录（需有提交记录）。默认先梳理整个项目的主要模块、能力、适用对象与核心流程，保留广度，概要介绍。确定值得展开的方向后，再深入实现与使用细节。</p>
        <Field label="项目绝对路径">{id => <Input id={id} placeholder="例如 D:\\workspace\\my-project" maxLength={2000} value={projectPath} onChange={e => setProjectPath(e.target.value)} />}</Field>
        <Field label="探索模式">{id => <Choice id={id} value={projectMode} options={{ overview: '全面概览 · 覆盖主要模块，简述能力', deep: '指定方向深挖 · 展开实现与流程' }} onChange={setProjectMode} />}</Field>
        <Field label="探索侧重">{id => <><select id={id} value={focus} aria-describedby={`${id}-description`} onChange={e => setFocus(e.target.value)}>
          <optgroup label="综合视角">{Object.entries(broadExplorationFocuses).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</optgroup>
          <optgroup label="素材分类">{Object.entries(materialTypes).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</optgroup>
        </select><span id={`${id}-description`} className="promotion-muted" aria-live="polite">{explorationFocusDescriptions[focus]}</span></>}</Field>
        <p className="promotion-muted">分类是预设的资料整理维度，AI 按项目实际内容归类。{materialTypes[focus] ? `当前仅生成「${materialTypes[focus]}」素材；资料不足会说明，不用其他分类补齐。` : '当前为综合视角，可生成多种素材分类；资料不足会说明，不强行凑齐分类。'}</p>
        <Field label={projectMode === 'deep' ? '深入方向（必填）' : '探索方向（可选）'}>{id => <Input.TextArea id={id} rows={2} maxLength={30000} placeholder={projectMode === 'deep' ? '例如：深入任务调度模块，说明从提交任务到失败恢复的流程与实现方式' : '例如：介绍时偏向普通用户，仍覆盖项目的主要模块，不展开技术细节'} value={projectDirection} onChange={e => setProjectDirection(e.target.value)} />}</Field>
        <p className="promotion-muted">{projectMode === 'overview' ? '介绍侧重不缩小模块覆盖范围。先形成完整的主要模块清单，再在所选分类范围内按领域归纳素材；资料缺口会明确标注。' : '仅深入指定方向及必要依赖，重新核对当前源码，不重复展开整个项目。'}</p>
        <BrandReferencePicker root={root} config={brandConfig} value={brand} onChange={setBrand} />
        <Button type="primary" loading={busy} disabled={!projectPath.trim() || (projectMode === 'deep' && !projectDirection.trim())} onClick={() => void start(taskInput('project', { project_path: projectPath.trim(), instruction: projectDirection, exploration_focus: focus, exploration_mode: projectMode }))}>探索项目并生成素材</Button>
        <p className="promotion-muted">进度和结果保存在下方生成记录中，可随时取消。生成后加入素材库，核对并确认再用于创作。</p>
      </section>}
      {(tab === 'cases' || tab === 'topics' || tab === 'feedback') && <details className="promotion-card" open={tab === 'topics'}><summary>{tab === 'cases' ? '用开发记录整理素材草稿' : tab === 'topics' ? '从素材策划选题' : '结合反馈策划下一轮内容'}</summary>
        {tab !== 'cases' && <MaterialPicker label="选用已确认素材" materials={library.cases} value={caseIds} onChange={setCaseIds} />}
        <Field label={tab === 'cases' ? '开发记录或资料原文' : '本次方向与补充要求（可选）'}>{id => <Input.TextArea id={id} rows={4} maxLength={30000} value={instruction} onChange={e => setInstruction(e.target.value)} />}</Field>
        <BrandReferencePicker root={root} config={brandConfig} value={brand} onChange={setBrand} />
        <Button loading={busy} disabled={tab === 'cases' ? !instruction.trim() : !usableSelection} onClick={() => void start(taskInput(tab === 'cases' ? 'case' : tab === 'topics' ? 'topics' : 'review', tab === 'cases' ? {} : { case_ids: caseIds }))}>{tab === 'cases' ? '整理为素材草稿' : tab === 'topics' ? '生成选题建议' : '生成复盘与新选题'}</Button>
      </details>}
      {tab === 'feedback' && report && <section aria-label="效果汇总"><p className="promotion-muted">{report.note}</p>{report.publications.length ? <><h3>按渠道汇总</h3><Metrics groups={report.groups.platforms} channel /><h3>按关联素材汇总</h3><Metrics groups={report.groups.cases} /></> : <Empty description="还没有已发布内容，暂无效果依据。先登记发布，再记录反馈。" />}<p className="promotion-muted">未知来源反馈 {report.unknown_source_count} 条 · 不参与渠道或素材归因</p></section>}
      <div className="promotion-filters"><Field label="搜索名称">{id => <Input id={id} value={search} onChange={e => { setSearch(e.target.value); setPage(1); }} />}</Field><Field label="显示记录">{id => <Choice id={id} value={archived ? 'archived' : 'active'} options={{ active: '使用中', archived: '已归档' }} onChange={v => { setArchived(v === 'archived'); setPage(1); }} />}</Field><Field label="状态筛选">{id => <Choice id={id} value={status} empty="全部状态" options={tab === 'channels' ? Object.fromEntries(['draft', 'ready', 'published', 'paused'].map(k => [k, statuses[k]])) : tab === 'feedback' ? { recorded: '已记录' } : { draft: '待审核', confirmed: '已确认' }} onChange={v => { setStatus(v); setPage(1); }} />}</Field>{tab === 'cases' && <Field label="素材类型筛选">{id => <Choice id={id} value={materialFilter} empty="全部类型" options={materialTypes} onChange={v => { setMaterialFilter(v); setPage(1); }} />}</Field>}{tab === 'channels' && <Field label="渠道筛选">{id => <Choice id={id} value={platform} empty="所有渠道" options={platforms} onChange={v => { setPlatform(v); setPage(1); }} />}</Field>}</div>
      {tab === 'channels' && <div className="promotion-stage-counts">{['draft', 'ready', 'published', 'paused'].map(s => <button type="button" key={s} aria-pressed={status === s} onClick={() => { setStatus(status === s ? '' : s); setPage(1); }}>{statuses[s]} <strong>{library.channels.filter(c => !c.archived && c.status === s).length}</strong></button>)}</div>}
      {!selected.length && <Empty description={search || status ? '没有匹配的记录' : '从新增一条记录开始，也可以先用 AI 整理草稿。'} />}
      <div className="promotion-grid">{visible.map(row => <article className="promotion-card" key={row.id}><div className="promotion-card-meta"><Tag>{tab !== 'channels' && row.status === 'draft' ? '待审核草稿' : statuses[row.status]}</Tag>{tab === 'cases' && <span>{materialTypes[materialType(row)]}{materialType(row) === 'case' ? row.data.case_type === 'customer' ? ' · 真实客户' : ' · 演示' : ''}</span>}{tab === 'channels' && <span>{platforms[row.platform || '']}</span>}{tab === 'topics' && <span>{directions[string(row.data.direction)]}</span>}</div><h3>{row.title}</h3>
        {tab === 'cases' && <><p>{string(row.data.summary) || string(row.data.problem) || '补充摘要与事实资料，让素材更容易复用。'}</p><p className="promotion-muted">{string(row.data.audience) || '尚未填写目标读者'}</p><details><summary>查看素材与事实</summary>{Object.entries(row.data).filter(([key, val]) => key !== 'assets' && (key !== 'evidence' || !row.source_snapshot?.evidence) && typeof val === 'string' && val && !['case_type', 'category', 'material_type'].includes(key)).map(([key, val]) => <p className="promotion-prose" key={key}><strong>{caseFields[key] || key}：</strong>{string(val)}</p>)}{((row.data.assets || []) as Data[]).map((a, i) => <p key={i}><a href={string(a.url)} target="_blank" rel="noreferrer">{string(a.label)}</a> · {string(a.note)}</p>)}</details></>}
        {tab === 'topics' && <><p className="promotion-muted">来源：{sourceIds(row).map(id => caseById[id]?.title || '来源不可用').join('、') || '—'}</p><p>{string(row.data.angle)}</p>{row.data.thesis ? <p><strong>核心观点：</strong>{string(row.data.thesis)}</p> : null}{row.data.outline ? <details><summary>内容结构</summary><p className="promotion-prose">{string(row.data.outline)}</p></details> : null}<p className="promotion-muted">读者：{string(row.data.audience) || '待补充'}</p><div className="promotion-channel-links">{Object.entries(platforms).map(([p, label]) => { const existing = library.channels.find(c => c.topic_id === row.id && c.platform === p); return <Button key={p} disabled={busy || row.archived || row.status !== 'confirmed'} onClick={() => existing ? setCopy(existing) : void action(async () => { const c = await api.create('channels', { title: row.title, topic_id: row.id, platform: p }); setCopy(c); })}>{existing ? `打开${label}` : `准备${label}`}</Button>; })}</div></>}
        {tab === 'channels' && <><p className="promotion-muted">选题：{topicById[row.topic_id || '']?.title || '—'}</p><p>计划：{string(row.data.planned_date) || '未安排'}</p>{row.data.published_at ? <p>发布：{new Date(string(row.data.published_at)).toLocaleString()}</p> : null}{row.data.publication_url ? <p><a href={string(row.data.publication_url)} target="_blank" rel="noreferrer">查看已发布内容</a></p> : null}<p className="promotion-muted">{row.latest_version ? `最新版本 v${row.latest_version.number}` : '尚未准备文案'} · {row.confirmed_version_id ? '已有确认版本' : '待确认文案'}</p></>}
        {tab === 'feedback' && <><p className="promotion-muted">{row.data.observed_on as string} · {row.channel_id ? library.channels.find(c => c.id === row.channel_id)?.title : '未知来源'}</p><p className="promotion-prose">{string(row.data.questions) || '暂无咨询问题'}</p><p>阅读／播放 {row.data.views == null ? '未记录' : string(row.data.views)} · 私信 {row.data.inquiries == null ? '未记录' : string(row.data.inquiries)}</p></>}
        <div className="promotion-actions">{tab === 'cases' && !row.archived && row.source_snapshot?.origin?.path && <Button onClick={() => { setProjectPath(row.source_snapshot!.origin!.path!); setProjectMode('deep'); setFocus(materialType(row)); setProjectDirection(`深入方向：${row.title}\n已有概览线索（需重新核对）：${string(row.data.summary) || string(row.data.problem)}\n请仅追踪此方向的相关实现、使用流程与限制。`); setNotice('已填入项目路径和深入方向，核对后点击探索项目并生成素材。'); projectForm.current?.scrollIntoView?.({ block: 'start' }); }}>深入此方向</Button>}{tab === 'cases' && row.status === 'confirmed'  && !row.archived && <Button onClick={() => { setCaseIds([row.id]); switchTab('topics'); }}>用此素材策划</Button>}{tab === 'channels' && !row.archived && <><Button type="primary" onClick={() => setCopy(row)}>编辑文案</Button><Button disabled={busy} onClick={() => void start(taskInput('copy', { channel_id: row.id }))}>生成新草稿</Button>{row.status === 'published' && <Button onClick={() => setEditor({ kind: 'feedback', initial: { channel_id: row.id, title: `${row.title} · 反馈` } })}>记录反馈</Button>}</>}<Button onClick={() => setEditor({ kind: tab, row })}>{tab === 'channels' ? '安排／登记发布' : '编辑与审核'}</Button><Button type="text" disabled={busy} onClick={() => void action(async () => { await api.update(tab, row, { archived: !row.archived }); })}>{row.archived ? '恢复' : '归档'}</Button></div>
      </article>)}</div><Pagination current={currentPage} total={selected.length} pageSize={12} showSizeChanger={false} hideOnSinglePage onChange={setPage} />
      {tab === 'channels' && <details className="promotion-card"><summary>创作偏好与品牌资料</summary><Field label="渠道生成补充要求">{id => <Input.TextArea id={id} rows={3} value={instruction} onChange={e => setInstruction(e.target.value)} />}</Field><BrandReferencePicker root={root} config={brandConfig} value={brand} onChange={setBrand} /></details>}
      <section className="promotion-task-section"><h2>生成记录 <span className="promotion-muted">{tasks.length}</span></h2>{!tasks.length && <p className="promotion-muted">生成结果先保存在这里。加入草稿后，可以编辑、核对并确认。</p>}{tasks.map(task => <TaskRecord task={task} label={tasksLabels[task.kind]} key={task.id}>
        {task.kind === 'project' && <p>{task.request.exploration_mode === 'deep' ? '指定方向深挖' : '全面概览'} · {explorationFocuses[string(task.request.exploration_focus) || 'all'] || '综合介绍'} · 项目：{string(task.request.project_path)}</p>}
        {activeTask(task) && <div className="promotion-actions"><p role="status">{task.stage || '等待开始'}</p><Button disabled={busy} onClick={() => void action(async () => { const cancelled = await api.cancel(task.id); setTasks(old => old.map(t => t.id === task.id ? cancelled : t)); })}>取消生成</Button></div>}
        {task.status === 'cancelled' && <p>已取消，可重新生成。</p>}
        {task.error && task.status !== 'cancelled' && <Alert type="error" message={task.error} />}
        <TaskActivity task={task} />
        {task.status === 'succeeded' && <>{task.kind === 'project' ? <ProjectResult result={task.result} /> : <pre className="promotion-prose">{taskText(task.result, caseById)}</pre>}<Button disabled={task.applied || busy} onClick={() => void action(async () => { await api.apply(task.id); setNotice(task.kind === 'copy' ? '已加入文案版本，请在发布看板审核。' : '已加入待审核草稿，请编辑核对后确认。'); })}>{task.applied ? '已加入草稿' : '加入可编辑草稿'}</Button></>}{!activeTask(task) && <Button disabled={busy} onClick={() => void start(task.request)}>重新生成</Button>}
      </TaskRecord>)}</section>
      {!!handoffs.length && <section><h2>创作交接记录</h2>{handoffs.map(h => <article className="promotion-card" key={h.id}><div className="promotion-actions"><a href={h.url}>打开{destinations.find(d => d.id === h.target_application_id)?.name || '创作应用'}</a><Button disabled={busy} onClick={() => void action(async () => setIncoming({ handoff: h, messages: await api.results(h.id) }))}>查看可回存结果</Button></div></article>)}</section>}
      {incoming && <section className="promotion-card"><h3>选择要回存的回复</h3>{!incoming.messages.length && <p>尚无已完成的助手回复。请打开创作应用完成生成后重试。</p>}{incoming.messages.map(m => <details key={m.id}><summary>{new Date(m.created_at).toLocaleString()} · 查看回复</summary><pre className="promotion-prose">{m.content}</pre><Button disabled={busy} onClick={() => void action(async () => { await api.importResult(incoming.handoff.id, m.id); setNotice('已回存为新版本，请到发布看板核对与编辑。'); setIncoming(undefined); })}>回存为新版本</Button></details>)}<Button onClick={() => setIncoming(undefined)}>关闭结果</Button></section>}
    </>}
    {editor && <RecordEditor key={`${editor.kind}:${editor.row?.id || 'new'}`} {...editor} library={library} api={api} onClose={() => setEditor(undefined)} onSaved={reload} />}
    {copy && <VersionEditor key={copy.id} row={copy} api={api} destinations={destinations} onClose={() => setCopy(undefined)} onSaved={reload} />}
  </div></div>;
}

function ProjectResult({ result }: { result: Data }) {
  const cases = (Array.isArray(result.cases) ? result.cases : []) as { title: string; data: Data; source_snapshot: SourceSnapshot }[];
  return <><p className="promotion-prose">{string(result.analysis)}</p>{cases.map((item, index) => <article className="promotion-card" key={index}><h3>{item.title}</h3><Tag>待审核 · {materialTypes[string(item.data.material_type) || 'case']}</Tag>
    {Object.entries(caseFields).filter(([key]) => item.data[key] && (key !== 'evidence' || !item.source_snapshot?.evidence)).map(([key, label]) => <p className="promotion-prose" key={key}><strong>{label}：</strong>{string(item.data[key])}</p>)}
  </article>)}</>;
}

function taskText(value: Data, sources: Record<string, PromotionRecord> = {}): string {
  const labels: Record<string, string> = { material_type: '素材类型', summary: '素材摘要', facts: '事实资料', thesis: '核心观点', outline: '内容结构', direction: '介绍角度', title: '标题', analysis: '分析建议', audience: '目标读者', angle: '切入点', body: '正文', cover: '封面', pages: '逐页文字', script: '脚本', materials: '素材', shots: '拍摄清单', checks: '待核实', problem: '问题', solution: '方案', steps: '过程', implemented: '已实现', evidence: '证据', conditions: '条件', extensions: '扩展方向' };
  return Object.entries(value).filter(([k]) => !['source_snapshot', 'evidence'].includes(k) && (k === 'case_ids' || (!k.endsWith('_id') && !k.endsWith('_ids')))).map(([k, v]) => k === 'case_ids' && Array.isArray(v) ? `引用素材：${v.map(id => sources[string(id)]?.title || '来源不可用').join('、')}` : k === 'material_type' ? `素材类型：${materialTypes[string(v)] || string(v)}` : k === 'direction' ? `介绍角度：${directions[string(v)] || string(v)}` : Array.isArray(v) ? v.map(item => typeof item === 'object' && item ? taskText(item as Data, sources) : string(item)).join('\n\n') : v && typeof v === 'object' ? taskText(v as Data, sources) : v ? `${labels[k] || k}：${string(v)}` : '').filter(Boolean).join('\n\n');
}

export default function ProjectPromotionPage() {
  const { applicationId } = useParams<{ applicationId: string }>(); const organizationId = useOrganizationStore(s => s.currentOrganizationId); const userId = useAuthStore(s => s.user?.id);
  if (!organizationId || !applicationId || !userId) return <Empty description="请选择组织并登录后使用。" />;
  const root = tenantApiRoot(organizationId);
  return <ProjectPromotionWorkspace key={`${organizationId}:${applicationId}:${userId}`} root={root} base={`${root}/applications/${applicationId}/project-promotion`} />;
}
