import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Button, Empty, Input, Pagination, Spin, Tag } from 'antd';
import { AppstoreOutlined, BulbOutlined, PlusOutlined, SoundOutlined } from '@ant-design/icons';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { tenantApiRoot } from '@/services/tenantContext';
import { openApplicationWindowWhenReady, resolveApplicationPresentation } from '@/lib/applicationPresentation';
import BrandReferencePicker from '@/components/BrandReferencePicker';
import type { BrandSelection } from '@/services/brandLibrary';
import { promotionApi, promotionError, activeTask, platforms, channelApplications, statuses, directions, materialTypes, explorationCategoriesLabel, explorationFocusDescriptions, materialType, sourceIds, resources, string, type PromotionRecord, type Resource, type Task, type Data, type Destination, type Handoff } from '@/services/projectPromotion';
import { Choice, Field, MaterialPicker, RecordEditor, caseFields, type Library } from './promotion/Editors';
import './ProjectPromotionPage.css';
import TaskActivity, { TaskRecord } from './promotion/TaskActivity';
import type { SourceSnapshot } from '@/services/projectPromotion';

const navigation = [
  { id: 'cases', name: '项目素材库', icon: AppstoreOutlined }, { id: 'topics', name: '选题与创作', icon: BulbOutlined },
] as const;
const tasksLabels: Record<string, string> = { project: '探索项目', case: '整理素材', topics: '策划选题' };
const initialLibrary = (): Library => ({ cases: [], topics: [] });
const brandConfig = { enabled: true, default_modules: ['positioning', 'voice'] as ('positioning' | 'voice')[], fields: {} };

export function ProjectPromotionWorkspace({ base, root }: { base: string; root: string }) {
  const api = useMemo(() => promotionApi(base), [base]); const [params, setParams] = useSearchParams();
  const tab = (resources.includes(params.get('tab') as Resource) ? params.get('tab') : 'cases') as Resource;
  const [library, setLibrary] = useState<Library>(initialLibrary); const [tasks, setTasks] = useState<Task[]>([]); const taskRef = useRef(tasks); taskRef.current = tasks;
  const [destinations, setDestinations] = useState<Destination[]>([]); const [handoffs, setHandoffs] = useState<Handoff[]>([]);
  const [revision, setRevision] = useState(0); const reload = useCallback(() => setRevision(v => v + 1), []);
  const [loading, setLoading] = useState(true); const [error, setError] = useState(''); const [notice, setNotice] = useState(''); const [busy, setBusy] = useState(false); const busyRef = useRef(false);
  const [editor, setEditor] = useState<{ kind: Resource; row?: PromotionRecord; initial?: Data }>();
  const [preparing, setPreparing] = useState<{ topicId: string; platform: string }>();
  const [channelError, setChannelError] = useState<{ topicId: string; message: string }>();
  const [search, setSearch] = useState(''); const [status, setStatus] = useState(''); const [page, setPage] = useState(1); const [archived, setArchived] = useState(false);
  const [caseIds, setCaseIds] = useState<string[]>([]); const [materialFilter, setMaterialFilter] = useState(''); const [categories, setCategories] = useState<string[]>(['overview']); const [instruction, setInstruction] = useState(''); const [brand, setBrand] = useState<BrandSelection | null>(null);
  const [materialInstruction, setMaterialInstruction] = useState('');
  const [topicOptions, setTopicOptions] = useState({ direction: '', audience: '', platform: '', count: '' });
  const [projectMode, setProjectMode] = useState('overview'); const projectForm = useRef<HTMLElement>(null);
  const [projectPath, setProjectPath] = useState(''); const [projectDirection, setProjectDirection] = useState('');
  useEffect(() => {
    let alive = true;
    Promise.all([Promise.all(resources.map(async kind => [kind, await api.all<PromotionRecord>(kind)] as const)), api.all<Task>('ai/tasks'), api.destinations(), api.handoffs()])
      .then(([rows, results, targets, transfers]) => { if (alive) { setLibrary(Object.fromEntries(rows) as Library); setTasks(results.filter(t => t.kind in tasksLabels)); setDestinations(targets); setHandoffs(transfers); } })
      .catch(e => { if (alive) setError(promotionError(e)); }).finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [api, revision]);
  const hasActive = tasks.some(activeTask);
  useEffect(() => {
    if (!hasActive) return;
    let alive = true; let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const items = (await api.all<Task>('ai/tasks')).filter(t => t.kind in tasksLabels); if (!alive) return;
        const completed = items.some(t => !activeTask(t) && taskRef.current.some(old => old.id === t.id && activeTask(old)));
        setTasks(items); if (completed) reload(); if (!items.some(activeTask)) return;
      } catch (e) { if (alive) setError(promotionError(e)); }
      if (alive) timer = setTimeout(() => void poll(), 3000);
    }
    timer = setTimeout(() => void poll(), 3000); return () => { alive = false; clearTimeout(timer); };
  }, [api, hasActive, reload]);
  async function action(fn: () => Promise<void>, onError?: (error: unknown) => void) {
    if (busyRef.current) return;
    busyRef.current = true; setBusy(true); setError(''); setNotice('');
    try { await fn(); reload(); } catch (e) { if (onError) onError(e); else setError(promotionError(e)); } finally { busyRef.current = false; setBusy(false); }
  }
  async function prepareChannel(topic: PromotionRecord, platform: string) {
    if (busyRef.current) return;
    setChannelError(undefined);
    const target = channelApplications[platform];
    if (!destinations.some(d => d.slug === target.slug)) {
      setChannelError({ topicId: topic.id, message: `当前没有可运行的「${target.name}」应用，请在应用中心安装或联系管理员开通。` });
      return;
    }
    setPreparing({ topicId: topic.id, platform });
    await action(async () => {
      await openApplicationWindowWhenReady(async () => {
        const handoff = await api.prepare(topic, platform);
        return handoff.url;
      });
    }, e => setChannelError({ topicId: topic.id, message: promotionError(e) }));
    setPreparing(undefined);
  }
  async function start(value: Data) {
    const input = value.kind === 'project' || value.kind === 'case' ? { ...value, brand_reference: null } : value;
    await action(async () => { const task = await api.start(input); setTasks(old => [task, ...old.filter(t => t.id !== task.id)]); setNotice('生成任务已提交，结果将保存在下方生成记录中。'); });
  }
  function switchTab(next: Resource) { const p = new URLSearchParams(params); p.set('tab', next); setParams(p, { replace: true }); setPage(1); setStatus(''); setSearch(''); setMaterialFilter(''); }
  function taskInput(kind: string, extra: Data = {}) {
    const options = Object.fromEntries(Object.entries(topicOptions).filter(([, value]) => value).map(([key, value]) => [key, key === 'count' ? Number(value) : value]));
    return { kind, instruction: kind === 'case' ? materialInstruction : instruction,
      brand_reference: kind === 'case' || kind === 'project' ? null : brand?.reference || null,
      ...(kind === 'topics' && Object.keys(options).length ? { topic_options: options } : {}), ...extra };
  }
  const selected = library[tab].filter(row => row.archived === archived && (!search || row.title.toLowerCase().includes(search.toLowerCase())) && (!status || row.status === status) && (tab !== 'cases' || !materialFilter || materialType(row) === materialFilter));
  const currentPage = Math.max(1, Math.min(page, Math.ceil(selected.length / 12))); const visible = selected.slice((currentPage - 1) * 12, currentPage * 12);
  const usableSelection = caseIds.length > 0 && caseIds.every(id => library.cases.some(c => c.id === id && c.status === 'confirmed' && !c.archived));
  const caseById = Object.fromEntries(library.cases.map(c => [c.id, c]));
  return <div className="promotion-page app-scroll-page"><div className="promotion-container">
    <header className="promotion-header"><div><span className="promotion-eyebrow"><SoundOutlined aria-hidden /> PROJECT STORIES</span><h1>项目宣传助手</h1><p className="promotion-muted">把真实能力讲清楚，让合适的人看见。</p></div><div className="promotion-header-side">{resolveApplicationPresentation(params).showApplicationHeader && <Link to="/apps">应用中心</Link>}<div className="promotion-summary"><strong>{library.cases.filter(c => c.status === 'confirmed' && !c.archived).length}</strong><span>已确认素材</span><strong>{library.topics.filter(t => t.status === 'confirmed' && !t.archived).length}</strong><span>已确认选题</span></div></div></header>
    <nav className="promotion-nav" aria-label="宣传工作流程">{navigation.map((n, i) => <button key={n.id} type="button" aria-current={tab === n.id ? 'page' : undefined} onClick={() => switchTab(n.id)}><n.icon aria-hidden /><span>{String(i + 1).padStart(2, '0')} · {n.name}</span></button>)}</nav>
    {error && <Alert type="error" role="alert" message={error} action={<Button onClick={() => { setError(''); reload(); }}>重新加载</Button>} />}{notice && <Alert type="success" role="status" message={notice} closable onClose={() => setNotice('')} />}
    {loading ? <div className="promotion-loading"><Spin /><p>正在载入宣传工作区…</p></div> : <>
      <section className="promotion-intro"><div><span className="promotion-eyebrow">{tab === 'cases' ? 'STORY BANK' : 'EDITORIAL DESK'}</span><h2>{tab === 'cases' ? '先整理项目事实，再决定怎样讲' : '组合真实素材，找到值得讲的选题'}</h2><p className="promotion-muted">{tab === 'cases' ? '从项目定位、人群、场景、功能、流程、技术、交付与演进等维度积累素材。核对事实后再用于创作。' : '选题决定面向谁、讲什么观点；可引用多份素材。确认后带入对应应用，完成公众号、图文或短视频创作。'}</p></div><Button type="primary" icon={<PlusOutlined aria-hidden />} onClick={() => setEditor({ kind: tab })}>{tab === 'cases' ? '新增素材' : '新增选题'}</Button></section>
      {tab === 'cases' && <section ref={projectForm} className="promotion-card" aria-label="从项目生成素材"><h2>填入项目路径，让 AI 发现可展示的能力</h2>
        <p className="promotion-muted">填写后端运行机器上的 Git 项目目录（需有提交记录）。默认先梳理整个项目的主要模块、能力、适用对象与核心流程，保留广度，概要介绍。确定值得展开的方向后，再深入实现与使用细节。</p>
        <Field label="项目绝对路径">{id => <Input id={id} placeholder="例如 D:\\workspace\\my-project" maxLength={2000} value={projectPath} onChange={e => setProjectPath(e.target.value)} />}</Field>
        <Field label="探索模式">{id => <Choice id={id} value={projectMode} options={{ overview: '全面概览 · 覆盖主要模块，简述能力', deep: '指定方向深挖 · 展开实现与流程' }} onChange={setProjectMode} />}</Field>
        {projectMode === 'overview' && <fieldset className="promotion-material-picker" aria-describedby="promotion-categories-help"><legend>素材分类</legend>
          <p id="promotion-categories-help" className="promotion-muted">可多选，至少选择一类。仅生成所选分类的素材；资料不足会说明，不强行凑齐。</p>
          <div className="promotion-material-options">{Object.entries(materialTypes).map(([key, label]) => <label className="promotion-material-option" key={key}>
            <input type="checkbox" value={key} aria-label={label} checked={categories.includes(key)} onChange={e => setCategories(old => Object.keys(materialTypes).filter(type => type === key ? e.target.checked : old.includes(type)))} />
            <span>{label}<small>{explorationFocusDescriptions[key]}</small></span>
          </label>)}</div>
          {!categories.length && <p role="status" className="promotion-muted">请选择至少一种素材分类。</p>}
        </fieldset>}
        <Field label={projectMode === 'deep' ? '深入方向（必填）' : '探索方向（可选）'}>{id => <Input.TextArea id={id} rows={2} maxLength={30000} placeholder={projectMode === 'deep' ? '例如：深入任务调度模块，说明从提交任务到失败恢复的流程与实现方式' : '例如：介绍时偏向普通用户，仍覆盖项目的主要模块，不展开技术细节'} value={projectDirection} onChange={e => setProjectDirection(e.target.value)} />}</Field>
        <p className="promotion-muted">{projectMode === 'overview' ? '素材分类不缩小模块覆盖范围。先形成完整的主要模块清单，再在所选分类范围内按领域归纳素材；资料缺口会明确标注。' : '仅深入指定方向及必要依赖，重新核对当前源码，按实际内容归类素材。'}</p>
        <Button type="primary" loading={busy} disabled={!projectPath.trim() || (projectMode === 'deep' ? !projectDirection.trim() : !categories.length)} onClick={() => void start(taskInput('project', { project_path: projectPath.trim(), instruction: projectDirection, ...(projectMode === 'overview' ? { material_types: categories } : {}), exploration_mode: projectMode }))}>探索项目并生成素材</Button>
        <p className="promotion-muted">进度和结果保存在下方生成记录中，可随时取消。生成后加入素材库，核对并确认再用于创作。</p>
      </section>}
      <details className="promotion-card" open={tab === 'topics'}><summary>{tab === 'cases' ? '用开发记录整理素材草稿' : '从素材策划选题'}</summary>
        {tab !== 'cases' && <MaterialPicker label="选用已确认素材" materials={library.cases} value={caseIds} onChange={setCaseIds} />}
        {tab !== 'cases' && <div role="group" aria-label="选题生成选项">
          <p className="promotion-muted">按需选择介绍角度、读者和渠道；留空时由 AI 根据素材判断。数量为上限，资料不足时不凑数。</p>
          <div className="promotion-form-grid">
            <Field label="介绍角度（可选）">{id => <Choice id={id} value={topicOptions.direction} empty="根据素材推荐" options={directions} onChange={direction => setTopicOptions(old => ({ ...old, direction }))} />}</Field>
            <Field label="目标读者（可选）">{id => <Choice id={id} value={topicOptions.audience} empty="根据素材推荐" options={{ '初次了解项目的人': '初次了解项目的人', '实际使用者': '实际使用者', '业务负责人': '业务负责人', '开发者与技术团队': '开发者与技术团队', '潜在合作伙伴': '潜在合作伙伴' }} onChange={audience => setTopicOptions(old => ({ ...old, audience }))} />}</Field>
            <Field label="发布渠道（可选）">{id => <Choice id={id} value={topicOptions.platform} empty="暂不限定渠道" options={platforms} onChange={platform => setTopicOptions(old => ({ ...old, platform }))} />}</Field>
            <Field label="选题数量">{id => <Choice id={id} value={topicOptions.count} empty="自动（1–8 个）" options={{ 1: '最多 1 个', 3: '最多 3 个', 5: '最多 5 个', 8: '最多 8 个', 12: '最多 12 个' }} onChange={count => setTopicOptions(old => ({ ...old, count }))} />}</Field>
          </div>
        </div>}
        <Field label={tab === 'cases' ? '开发记录或资料原文' : '本次方向与补充要求（可选）'}>{id => <Input.TextArea id={id} rows={4} maxLength={30000} value={tab === 'cases' ? materialInstruction : instruction} onChange={e => tab === 'cases' ? setMaterialInstruction(e.target.value) : setInstruction(e.target.value)} />}</Field>
        {tab !== 'cases' && <BrandReferencePicker root={root} config={brandConfig} value={brand} onChange={setBrand} />}
        <Button loading={busy} disabled={tab === 'cases' ? !materialInstruction.trim() : !usableSelection} onClick={() => void start(taskInput(tab === 'cases' ? 'case' : 'topics', tab === 'cases' ? {} : { case_ids: caseIds }))}>{tab === 'cases' ? '整理为素材草稿' : '生成选题建议'}</Button>
      </details>
      <div className="promotion-filters"><Field label="搜索名称">{id => <Input id={id} value={search} onChange={e => { setSearch(e.target.value); setPage(1); }} />}</Field><Field label="显示记录">{id => <Choice id={id} value={archived ? 'archived' : 'active'} options={{ active: '使用中', archived: '已归档' }} onChange={v => { setArchived(v === 'archived'); setPage(1); }} />}</Field><Field label="状态筛选">{id => <Choice id={id} value={status} empty="全部状态" options={{ draft: '待审核', confirmed: '已确认' }} onChange={v => { setStatus(v); setPage(1); }} />}</Field>{tab === 'cases' && <Field label="素材类型筛选">{id => <Choice id={id} value={materialFilter} empty="全部类型" options={materialTypes} onChange={v => { setMaterialFilter(v); setPage(1); }} />}</Field>}</div>
      {!selected.length && <Empty description={search || status ? '没有匹配的记录' : '从新增一条记录开始，也可以先用 AI 整理草稿。'} />}
      <div className="promotion-grid">{visible.map(row => <article className="promotion-card" key={row.id}><div className="promotion-card-meta"><Tag>{row.status === 'draft' ? '待审核草稿' : statuses[row.status]}</Tag>{tab === 'cases' && <span>{materialTypes[materialType(row)]}{materialType(row) === 'case' ? row.data.case_type === 'customer' ? ' · 真实客户' : ' · 演示' : ''}</span>}{tab === 'topics' && <span>{directions[string(row.data.direction)]}</span>}</div><h3>{row.title}</h3>
        {tab === 'cases' && <><p>{string(row.data.summary) || string(row.data.problem) || '补充摘要与事实资料，让素材更容易复用。'}</p><p className="promotion-muted">{string(row.data.audience) || '尚未填写目标读者'}</p><details><summary>查看素材与事实</summary>{Object.entries(row.data).filter(([key, val]) => key !== 'assets' && (key !== 'evidence' || !row.source_snapshot?.evidence) && typeof val === 'string' && val && !['case_type', 'category', 'material_type'].includes(key)).map(([key, val]) => <p className="promotion-prose" key={key}><strong>{caseFields[key] || key}：</strong>{string(val)}</p>)}{((row.data.assets || []) as Data[]).map((a, i) => <p key={i}><a href={string(a.url)} target="_blank" rel="noreferrer">{string(a.label)}</a> · {string(a.note)}</p>)}</details></>}
        {tab === 'topics' && <><p className="promotion-muted">来源：{sourceIds(row).map(id => caseById[id]?.title || '来源不可用').join('、') || '—'}</p><p>{string(row.data.angle)}</p>{row.data.thesis ? <p><strong>核心观点：</strong>{string(row.data.thesis)}</p> : null}{row.data.outline ? <details><summary>内容结构</summary><p className="promotion-prose">{string(row.data.outline)}</p></details> : null}<p className="promotion-muted">读者：{string(row.data.audience) || '待补充'}</p>
          <div className="promotion-channel-links">{Object.entries(platforms).map(([p, label]) => {
            const existing = handoffs.some(h => h.topic_id === row.id && h.platform === p);
            return <Button key={p} title={`在新窗口打开${channelApplications[p].name}`} loading={preparing?.topicId === row.id && preparing.platform === p} disabled={busy || row.archived || row.status !== 'confirmed'} onClick={() => void prepareChannel(row, p)}>{existing ? `打开${label}` : `准备${label}`}</Button>;
          })}</div>
          <p className="promotion-muted">{row.archived ? '请先恢复选题，再进入创作应用。' : row.status !== 'confirmed' ? '请先通过“编辑与审核”确认选题，再进入创作应用。' : '带入选题与素材，进入对应应用创作；公众号使用爆款写作，小红书和朋友圈使用图文文案，抖音使用短视频文案。'}</p>
          {channelError?.topicId === row.id && <Alert type="error" role="alert" message={channelError.message} />}
        </>}
        <div className="promotion-actions">{tab === 'cases' && !row.archived && row.source_snapshot?.origin?.path && <Button onClick={() => { setProjectPath(row.source_snapshot!.origin!.path!); setProjectMode('deep'); setProjectDirection(`深入方向：${row.title}\n已有概览线索（需重新核对）：${string(row.data.summary) || string(row.data.problem)}\n请仅追踪此方向的相关实现、使用流程与限制。`); setNotice('已填入项目路径和深入方向，核对后点击探索项目并生成素材。'); projectForm.current?.scrollIntoView?.({ block: 'start' }); }}>深入此方向</Button>}{tab === 'cases' && row.status === 'confirmed'  && !row.archived && <Button onClick={() => { setCaseIds([row.id]); switchTab('topics'); }}>用此素材策划</Button>}<Button onClick={() => setEditor({ kind: tab, row })}>编辑与审核</Button><Button type="text" disabled={busy} onClick={() => void action(async () => { await api.update(tab, row, { archived: !row.archived }); })}>{row.archived ? '恢复' : '归档'}</Button></div>
      </article>)}</div><Pagination current={currentPage} total={selected.length} pageSize={12} showSizeChanger={false} hideOnSinglePage onChange={setPage} />
      <section className="promotion-task-section"><h2>生成记录 <span className="promotion-muted">{tasks.length}</span></h2>{!tasks.length && <p className="promotion-muted">生成结果先保存在这里。加入草稿后，可以编辑、核对并确认。</p>}{tasks.map(task => <TaskRecord task={task} label={tasksLabels[task.kind]} key={task.id}>
        {task.kind === 'project' && <p>{task.request.exploration_mode === 'deep' ? '指定方向深挖' : '全面概览'}{task.request.exploration_mode !== 'deep' && ` · ${explorationCategoriesLabel(task.request)}`} · 项目：{string(task.request.project_path)}</p>}
        {activeTask(task) && <div className="promotion-actions"><p role="status">{task.stage || '等待开始'}</p><Button disabled={busy} onClick={() => void action(async () => { const cancelled = await api.cancel(task.id); setTasks(old => old.map(t => t.id === task.id ? cancelled : t)); })}>取消生成</Button></div>}
        {task.status === 'cancelled' && <p>已取消，可重新生成。</p>}
        {task.error && task.status !== 'cancelled' && <Alert type="error" message={task.error} />}
        <TaskActivity task={task} />
        {task.status === 'succeeded' && <>{task.kind === 'project' ? <ProjectResult result={task.result} /> : <pre className="promotion-prose">{taskText(task.result, caseById)}</pre>}<Button disabled={task.applied || busy} onClick={() => void action(async () => { await api.apply(task.id); setNotice('已加入待审核草稿，请编辑核对后确认。'); })}>{task.applied ? '已加入草稿' : '加入可编辑草稿'}</Button></>}{!activeTask(task) && <Button disabled={busy} onClick={() => void start(task.request)}>重新生成</Button>}
      </TaskRecord>)}</section>
    </>}
    {editor && <RecordEditor key={`${editor.kind}:${editor.row?.id || 'new'}`} {...editor} library={library} api={api} onClose={() => setEditor(undefined)} onSaved={reload} />}
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
