import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Button, Empty, Input, InputNumber, Modal, Pagination, Select, Spin, Tag } from 'antd';
import { ArrowLeftOutlined, CalendarOutlined, HomeOutlined, EditOutlined, TeamOutlined, LineChartOutlined, AppstoreOutlined, SettingOutlined, PlusOutlined } from '@ant-design/icons';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { tenantApiRoot } from '@/services/tenantContext';
import { resolveApplicationPresentation } from '@/lib/applicationPresentation';
import { activeTask, dayInZone, emptyLibrary, rentalApi, rentalError, resources, string, type Data, type Event, type Library, type Overview, type Preferences, type RentalRecord, type Report, type Resource, type Task } from '@/services/rentalGrowth';
import { RecordEditor, CopyEditor, type EditorState } from './rental/Editors';
import { Creator, LeadDesk, ReportPanel, TaskHistory } from './rental/Panels';
import { meta, options, platformLabels, statusLabels, typeLabels } from './rental/config';
import './RentalGrowthPage.css';

type Tab = 'today' | 'properties' | 'create' | 'clients' | 'calendar' | 'review';
const navigation = [
  { id: 'today', label: '今日', icon: AppstoreOutlined }, { id: 'properties', label: '房源', icon: HomeOutlined },
  { id: 'create', label: '创作', icon: EditOutlined }, { id: 'clients', label: '客户', icon: TeamOutlined },
  { id: 'calendar', label: '日历', icon: CalendarOutlined }, { id: 'review', label: '复盘', icon: LineChartOutlined },
] as const;
const initialPreferences = { timezone: 'Asia/Shanghai', voice: '自然、具体的中介介绍，不夸张承诺。', platform: 'xiaohongshu' };

function LibraryList({ kind, rows, busy, onEdit, onArchive, onCreate, onCopy, onLead, onMetrics }: { kind: Resource; rows: RentalRecord[]; busy: boolean; onEdit: (editor: EditorState) => void; onArchive: (kind: Resource, row: RentalRecord) => void; onCreate: (row: RentalRecord, kind?: Resource) => void; onCopy: (row: RentalRecord) => void; onLead: (row: RentalRecord) => void; onMetrics: (row: RentalRecord) => void }) {
  const [query, setQuery] = useState(''); const [status, setStatus] = useState(''); const [archive, setArchive] = useState('active'); const [page, setPage] = useState(1);
  const selected = rows.filter(r => (archive === 'all' || r.archived === (archive === 'archived')) && (!status || r.status === status) && `${r.title} ${JSON.stringify(r.data)}`.toLowerCase().includes(query.toLowerCase()));
  const current = Math.min(page, Math.max(1, Math.ceil(selected.length / 12)));
  return <section className="rental-library"><div className="rental-section-heading"><h2>{meta[kind].label}{kind === 'contents' ? '与选题库' : '管理'}</h2><Button icon={<PlusOutlined aria-hidden />} onClick={() => onEdit({ kind })}>新增{meta[kind].label}</Button></div>
    {kind === 'personas' && <p className="rental-muted">已内置常用租客画像，可直接用于选题和文案，也可编辑或归档。预算、区域与入住日期按你的业务补充；画像不代表客户本人已确认的需求。</p>}
    <div className="rental-filters"><div className="rental-field"><label htmlFor={`search-${kind}`}>搜索</label><Input id={`search-${kind}`} allowClear value={query} onChange={e => { setQuery(e.target.value); setPage(1); }} placeholder="名称、位置或备注" /></div><div className="rental-field"><label htmlFor={`status-${kind}`}>状态</label><Select id={`status-${kind}`} allowClear value={status || undefined} options={meta[kind].statuses.map(value => ({ value, label: statusLabels[value] }))} onChange={value => { setStatus(value || ''); setPage(1); }} placeholder="全部状态" /></div><div className="rental-field"><label htmlFor={`archive-${kind}`}>记录范围</label><Select id={`archive-${kind}`} value={archive} options={options({ active: '未归档', archived: '已归档', all: '全部记录' })} onChange={value => { setArchive(value); setPage(1); }} /></div></div>
    {!selected.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={`暂无${meta[kind].label}，可以新增或调整筛选。`} />}
    <div className="rental-grid">{selected.slice((current - 1) * 12, current * 12).map(row => <article className="rental-card rental-record-card" key={row.id}>
      <div className="rental-card-title"><h3>{row.title}</h3><Tag>{row.archived ? '已归档' : statusLabels[row.status]}</Tag></div>
      {kind === 'properties' && <><div className="rental-price">{row.data.rent == null ? '租金待补充' : <>{String(row.data.rent)} <small>元／月</small></>}</div><p>{[row.data.city, row.data.district, row.data.layout, row.data.location].filter(Boolean).join(' · ') || '位置与户型待完善'}</p><p className="rental-prose">{string(row.data.strengths) || '补充真实卖点，帮助租客判断。'}</p>{!!row.data.drawbacks && <p className="rental-muted">注意：{string(row.data.drawbacks)}</p>}</>}
      {(kind === 'leads' || kind === 'personas') && <><p>{[row.data.city, ...(Array.isArray(row.data.districts) ? row.data.districts : []), row.data.layout].filter(Boolean).join(' · ') || '区域与户型待确认'}</p><p>预算：{row.data.budget_min == null && row.data.budget_max == null ? '待确认' : `${row.data.budget_min ?? '不限'} ～ ${row.data.budget_max ?? '不限'} 元／月`}</p><p className="rental-prose">{string(row.data.needs)}</p>{!!row.duplicates?.length && <Tag color="orange">联系方式可能重复</Tag>}</>}
      {kind === 'personas' && !!row.data.concerns && <p className="rental-prose"><strong>关注点：</strong>{string(row.data.concerns)}</p>}
      {kind === 'contents' && <><p>{platformLabels[string(row.data.platform)]} · {typeLabels[string(row.data.content_type)]}</p><p>{row.latest_version ? `已保存 ${row.latest_version.number} 个版本` : '选题待创作'}</p><p className="rental-prose">{string(row.data.angle)}</p></>}
      {kind === 'publications' && <><p>计划：{string(row.data.scheduled_date) || '未安排'}</p><p>发布：{row.data.published_at ? new Date(String(row.data.published_at)).toLocaleString('zh-CN') : '尚未发布'}</p>{!!row.data.url && <a href={string(row.data.url)} target="_blank" rel="noreferrer">打开作品</a>}</>}
      {(kind === 'followups' || kind === 'viewings') && <><p>{string(row.data.due_date) || (row.data.scheduled_at ? new Date(String(row.data.scheduled_at)).toLocaleString('zh-CN') : '')}</p><p className="rental-prose">{[row.data.summary, row.data.feedback, row.data.next_step].filter(Boolean).join('\n')}</p></>}
      {!!row.changes?.length && <Alert type="warning" message="需要调整" description={row.changes.join('；')} />}
      <div className="rental-actions">
        {kind === 'properties' && !row.archived && row.status === 'available' && <Button type="primary" onClick={() => onCreate(row)}>用这套房创作</Button>}
        {kind === 'personas' && !row.archived && <Button type="primary" onClick={() => onCreate(row, kind)}>用这个画像创作</Button>}
        {kind === 'contents' && !row.archived && <><Button type="primary" onClick={() => row.latest_version ? onCopy(row) : onCreate(row)}>{row.latest_version ? '编辑文案' : '开始创作'}</Button>{row.latest_version && <Button onClick={() => onCreate(row)}>改写／转换平台</Button>}</>}
        {kind === 'leads' && <Button type="primary" onClick={() => onLead(row)}>咨询与匹配</Button>}
        {kind === 'publications' && row.status === 'published' && <Button onClick={() => onMetrics(row)}>记录效果</Button>}
        <Button onClick={() => onEdit({ kind, row })}>编辑{kind === 'contents' ? '资料' : ''}</Button><Button type="text" disabled={busy} onClick={() => onArchive(kind, row)}>{row.archived ? '恢复' : '归档'}</Button>
      </div>
    </article>)}</div><Pagination current={current} total={selected.length} pageSize={12} hideOnSinglePage showSizeChanger={false} onChange={setPage} />
  </section>;
}

function EventList({ events, onOpen }: { events: Event[]; onOpen: (event: Event) => void }) {
  return <div className="rental-event-list">{events.map(event => <article key={`${event.kind}:${event.id}`}><div><span className="rental-muted">{event.date} · {event.kind === 'publication' ? '发文' : event.kind === 'content' ? '选题' : event.kind === 'viewings' ? '带看' : '跟进'}</span><h3>{event.title}</h3>{event.lead_title && <p>{event.lead_title}</p>}{event.record.data.next_step ? <p>{String(event.record.data.next_step)}</p> : null}{event.changes.length > 0 && <p className="rental-warning">需要调整：{event.changes.join('；')}</p>}</div><div className="rental-actions">{event.overdue && <Tag color="orange">逾期</Tag>}<Tag>{statusLabels[event.status]}</Tag><Button onClick={() => onOpen(event)}>{event.actionable ? '处理' : '核对资料'}</Button></div></article>)}</div>;
}

function CalendarPanel({ overview, onOpen }: { overview: Overview; onOpen: (event: Event) => void }) {
  const [mode, setMode] = useState('week'); const [start, setStart] = useState(overview.today);
  const days = Array.from({ length: 7 }, (_, i) => { const date = new Date(`${start}T12:00:00Z`); date.setUTCDate(date.getUTCDate() + i); return date.toISOString().slice(0, 10); });
  return <section><div className="rental-section-heading"><div><span className="rental-eyebrow">OPERATIONS CALENDAR</span><h2>安排发布，也安排下一次联系</h2></div></div><div className="rental-filters"><div className="rental-field"><label htmlFor="calendar-mode">视图</label><Select id="calendar-mode" value={mode} options={options({ week: '七天视图', list: '全部事项' })} onChange={setMode} /></div><div className="rental-field"><label htmlFor="calendar-start">起始日期</label><Input id="calendar-start" type="date" value={start} onChange={e => { if (e.target.value) setStart(e.target.value); }} /></div><Button onClick={() => setStart(overview.today)}>回到今天</Button></div>
    {mode === 'week' ? <div className="rental-week">{days.map(day => <section key={day} className={day === overview.today ? 'is-today' : ''}><h3>{day.slice(5)}</h3><EventList events={overview.events.filter(e => e.date === day)} onOpen={onOpen} />{!overview.events.some(e => e.date === day) && <p className="rental-muted">暂无安排</p>}</section>)}</div> : <EventList events={overview.events} onOpen={onOpen} />}
    <p className="rental-muted">提醒仅在应用内显示。复制文案不会自动发布；完成带看也不会自动成交。</p>
  </section>;
}

export function RentalGrowthWorkspace({ base, showHeader = true }: { base: string; showHeader?: boolean }) {
  const api = useMemo(() => rentalApi(base), [base]); const navigate = useNavigate();
  const [tab, setTab] = useState<Tab>('today'); const [library, setLibrary] = useState<Library>(emptyLibrary);
  const [prefs, setPrefs] = useState<Preferences>(initialPreferences); const [tasks, setTasks] = useState<Task[]>([]);
  const [overview, setOverview] = useState<Overview>({ today: dayInZone('Asia/Shanghai'), events: [] });
  const [dashboard, setDashboard] = useState<Overview | null>(null); const [report, setReport] = useState<Report | null>(null);
  const [loading, setLoading] = useState(true); const [busy, setBusy] = useState(false); const busyRef = useRef(false);
  const [error, setError] = useState(''); const [notice, setNotice] = useState(''); const [revision, setRevision] = useState(0);
  const [editor, setEditor] = useState<EditorState | null>(null); const [copy, setCopy] = useState<RentalRecord | null>(null);
  const [leadId, setLeadId] = useState(''); const [creator, setCreator] = useState<Data>({}); const [creatorKey, setCreatorKey] = useState(0);
  const pageRef = useRef<HTMLDivElement>(null);
  const generateButtonRef = useRef<HTMLButtonElement>(null);
  const pendingCreatorScroll = useRef(false);
  useEffect(() => {
    if (tab !== 'create' || !pendingCreatorScroll.current) return;
    const page = pageRef.current;
    const button = generateButtonRef.current;
    if (!page || !button) return;
    pendingCreatorScroll.current = false;
    const target = button.getBoundingClientRect();
    const viewport = page.getBoundingClientRect();
    button.focus({ preventScroll: true });
    page.scrollTo({
      top: Math.max(0, page.scrollTop + target.top - viewport.top - page.clientTop - (page.clientHeight - target.height) / 2),
      behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth',
    });
  }, [tab, creatorKey]);
  const [metrics, setMetrics] = useState<RentalRecord | null>(null); const [metricData, setMetricData] = useState<Data>({});
  const [settings, setSettings] = useState<Preferences | null>(null); const [clientKind, setClientKind] = useState<Resource>('leads'); const [propertyKind, setPropertyKind] = useState<Resource>('properties');
  const [range, setRange] = useState<Data>({}); const requestRef = useRef<{ hash: string; key: string } | null>(null);
  const reload = useCallback(() => setRevision(v => v + 1), []);
  useEffect(() => {
    let alive = true; setError('');
    Promise.all([Promise.all(resources.map(async kind => [kind, await api.all<RentalRecord>(kind)] as const)), api.settings(), api.all<Task>('ai/tasks'), api.overview('calendar'), api.overview('dashboard')]).then(([rows, preferences, taskRows, cal, today]) => {
      if (!alive) return;
      setLibrary(Object.fromEntries(rows) as Library); setPrefs(preferences); setTasks(taskRows); setOverview(cal); setDashboard(today);
    }).catch(e => { if (alive) setError(rentalError(e)); }).finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [api, revision]);
  useEffect(() => { let alive = true; api.report(range).then(value => { if (alive) setReport(value); }).catch(e => { if (alive) setError(rentalError(e)); }); return () => { alive = false; }; }, [api, range, revision]);
  const taskRef = useRef(tasks);
  taskRef.current = tasks;
  const hasActive = tasks.some(activeTask);
  useEffect(() => {
    if (!hasActive) return;
    let alive = true; let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try { const rows = await api.all<Task>('ai/tasks'); if (!alive) return; const completed = rows.some(t => !activeTask(t) && taskRef.current.some(old => old.id === t.id && activeTask(old))); setTasks(rows); if (completed) reload(); if (!rows.some(activeTask)) return; }
      catch (e) { if (alive) setError(rentalError(e)); }
      if (alive) timer = setTimeout(() => void poll(), 2500);
    }
    timer = setTimeout(() => void poll(), 2500);
    return () => { alive = false; clearTimeout(timer); };
  }, [api, hasActive, reload]);
  useEffect(() => { const timer = setInterval(() => { if (dayInZone(prefs.timezone) !== overview.today) reload(); }, 30000); return () => clearInterval(timer); }, [prefs.timezone, overview.today, reload]);
  async function action(fn: () => Promise<void>) {
    if (busyRef.current) return;
    busyRef.current = true; setBusy(true); setError(''); setNotice('');
    try { await fn(); reload(); } catch (e) { setError(rentalError(e)); } finally { busyRef.current = false; setBusy(false); }
  }
  async function startTask(value: Data) {
    await action(async () => {
      const hash = JSON.stringify(value);
      if (requestRef.current?.hash !== hash) requestRef.current = { hash, key: crypto.randomUUID() };
      const task = await api.start({ ...value, request_key: requestRef.current!.key });
      requestRef.current = null; setTasks(old => [task, ...old.filter(t => t.id !== task.id)]); setNotice('任务已提交，结果会保存在生成记录中。');
    });
  }
  function openEditor(value: EditorState) {
    setEditor(value.kind === 'leads' && !value.row ? { ...value, data: { consulted_on: overview.today, ...value.data } } : value.kind === 'followups' && !value.row ? { ...value, data: { due_date: overview.today, ...value.data } } : value);
  }
  function createFrom(row: RentalRecord, kind?: Resource) { pendingCreatorScroll.current = true; setCreator(kind === 'personas' ? { persona_id: row.id } : row.data.platform ? { ...row.data, content_id: row.id } : { property_ids: [row.id], content_type: 'property' }); setCreatorKey(v => v + 1); setTab('create'); }
  function openEvent(event: Event) { if (event.kind === 'content') createFrom(event.record); else openEditor({ kind: event.kind === 'publication' ? 'publications' : event.kind as Resource, row: event.record }); }
  const sharedList = { busy, onEdit: openEditor, onArchive: (kind: Resource, row: RentalRecord) => void action(async () => { await api.update(kind, row, { archived: !row.archived }); }), onCreate: createFrom, onCopy: setCopy, onLead: (row: RentalRecord) => { setLeadId(row.id); setTab('clients'); }, onMetrics: (row: RentalRecord) => { setMetrics(row); setMetricData({}); } };
  const taskProps = { library, busy, onTask: startTask, onEdit: openEditor, onOpenCopy: setCopy, onCancel: (id: string) => void action(async () => { await api.cancel(id); }), onApply: (id: string) => void action(async () => { await api.apply(id); setNotice('七天选题已加入创作与日历。'); }) };
  const lead = library.leads.find(row => row.id === leadId);
  return <div ref={pageRef} className="rental-page app-scroll-page"><div className="rental-container">
    <header className="rental-header"><div className="rental-brand"><div className="rental-brand-icon"><HomeOutlined aria-hidden /></div><div><span className="rental-eyebrow">RENTAL GROWTH</span><h1>租房获客助手</h1></div></div><div className="rental-actions">{showHeader && <Button type="text" icon={<ArrowLeftOutlined aria-hidden />} onClick={() => navigate('/apps')}>应用中心</Button>}<Button icon={<SettingOutlined aria-hidden />} onClick={() => setSettings({ ...prefs })}>设置</Button></div></header>
    <nav className="rental-nav" aria-label="租房助手栏目">{navigation.map(item => <button key={item.id} type="button" aria-current={tab === item.id ? 'page' : undefined} onClick={() => { setTab(item.id); setError(''); }}><item.icon aria-hidden /><span>{item.label}</span></button>)}</nav>
    {error && <Alert type="error" role="alert" message={error} action={<Button onClick={reload}>重新加载</Button>} />}{notice && <Alert type="success" message={notice} closable onClose={() => setNotice('')} />}
    {loading ? <div role="status" className="rental-loading"><Spin /><p>正在加载你的运营工作台…</p></div> : <>
      {tab === 'today' && <section><div className="rental-hero"><span className="rental-eyebrow">YOUR DAILY WORKSPACE · {overview.today}</span><h2>从一套好房，到一次有效咨询。</h2><p>安排好今天的内容、客户和带看。</p><div className="rental-actions"><Button type="primary" icon={<PlusOutlined aria-hidden />} onClick={() => openEditor({ kind: 'properties' })}>新增房源</Button><Button onClick={() => { setCreator({}); setCreatorKey(v => v + 1); setTab('create'); }}>生成内容</Button><Button onClick={() => openEditor({ kind: 'leads' })}>登记咨询</Button><Button onClick={() => openEditor({ kind: 'viewings' })}>预约带看</Button></div></div>
        {!dashboard?.property_count && <div className="rental-card"><Empty description="先录入第一套真实房源，再为它找到适合的租客。" /></div>}
        <div className="rental-today-grid">{[['今天发什么', ['publication', 'content']], ['今天联系谁', ['followups']], ['今天带谁看房', ['viewings']]].map(([label, kinds]) => { const events = dashboard?.events.filter(e => (kinds as string[]).includes(e.kind) && e.actionable) || []; return <section className="rental-card" key={String(label)}><h3>{label} <span className="rental-count">{events.length}</span></h3><EventList events={events} onOpen={openEvent} />{!events.length && <p className="rental-muted">暂无待处理事项</p>}</section>; })}</div>
        <section className="rental-card"><h3>需要核对的房源与内容</h3>{dashboard?.attention?.map(row => <div className="rental-attention" key={row.id}><span><strong>{row.title}</strong> · {row.status === 'paused' ? '暂停推广' : ''} {row.gaps.length ? `待补充：${row.gaps.join('、')}` : ''}</span><Button onClick={() => openEditor({ kind: 'properties', row })}>完善资料</Button></div>)}<EventList events={overview.events.filter(e => e.active && !e.actionable)} onOpen={openEvent} />{!dashboard?.attention?.length && !overview.events.some(e => e.active && !e.actionable) && <p className="rental-muted">暂无需要核对的事项。</p>}</section>
      </section>}
      {tab === 'properties' && <><div className="rental-subnav"><Button type={propertyKind === 'properties' ? 'primary' : 'default'} onClick={() => setPropertyKind('properties')}>我的房源</Button><Button type={propertyKind === 'personas' ? 'primary' : 'default'} onClick={() => setPropertyKind('personas')}>目标租客画像</Button></div><LibraryList key={propertyKind} kind={propertyKind} rows={library[propertyKind]} {...sharedList} /></>}
      {tab === 'create' && <><Creator key={creatorKey} library={library} preferences={prefs} initial={creator} busy={busy} onTask={startTask} generateButtonRef={generateButtonRef} /><TaskHistory tasks={tasks.filter(t => ['copy', 'topics'].includes(t.kind))} {...taskProps} /><LibraryList kind="contents" rows={library.contents} {...sharedList} /><LibraryList kind="publications" rows={library.publications} {...sharedList} /></>}
      {tab === 'clients' && <><div className="rental-subnav">{(['leads', 'followups', 'viewings'] as const).map(kind => <Button key={kind} type={clientKind === kind ? 'primary' : 'default'} onClick={() => { setClientKind(kind); setLeadId(''); }}>{meta[kind].label}</Button>)}</div>{lead && clientKind === 'leads' ? <><Button onClick={() => setLeadId('')}>返回客户列表</Button><LeadDesk key={lead.id} lead={lead} api={api} tasks={tasks} {...taskProps} /></> : <LibraryList key={clientKind} kind={clientKind} rows={library[clientKind]} {...sharedList} />}</>}
      {tab === 'calendar' && <CalendarPanel overview={overview} onOpen={openEvent} />}
      {tab === 'review' && <><ReportPanel report={report} library={library} busy={busy} onTask={startTask} onRange={setRange} /><TaskHistory tasks={tasks.filter(t => t.kind === 'review')} {...taskProps} /></>}
    </>}
    {editor && <RecordEditor key={`${editor.kind}:${editor.row?.id || 'new'}`} editor={editor} api={api} library={library} preferences={prefs} onClose={() => setEditor(null)} onSaved={row => { setEditor(null); if (row.duplicates?.length) setNotice(`已保存；联系方式可能与 ${row.duplicates.map(r => r.title).join('、')} 重复。`); reload(); }} />}
    {copy && <CopyEditor row={copy} api={api} onClose={() => setCopy(null)} onSaved={reload} onPublish={version => { setCopy(null); openEditor({ kind: 'publications', initial: { title: copy.title, status: 'planned', version_id: version.id }, data: { scheduled_date: overview.today } }); }} />}
    <Modal open={!!metrics} title="记录作品效果" rootClassName="rental-modal" onCancel={() => setMetrics(null)} okText="保存指标" confirmLoading={busy} onOk={() => void action(async () => { if (metrics) await api.metrics(metrics.id, metricData); setMetrics(null); })}><p>记录此刻的累计数，留空表示未记录。历史记录会保留。</p><div className="rental-form-grid">{Object.entries({ views: '浏览／播放', likes: '点赞', saves: '收藏', comments: '评论' }).map(([key, label]) => <div className="rental-field" key={key}><label htmlFor={`metric-${key}`}>{label}</label><InputNumber id={`metric-${key}`} min={0} precision={0} value={typeof metricData[key] === 'number' ? metricData[key] as number : null} onChange={value => setMetricData(old => ({ ...old, [key]: value }))} /></div>)}</div>{error && <Alert type="error" message={error} />}</Modal>
    <Modal open={!!settings} title="个人偏好" rootClassName="rental-modal" onCancel={() => setSettings(null)} okText="保存设置" confirmLoading={busy} onOk={() => void action(async () => { if (settings) setPrefs(await api.saveSettings(settings)); setSettings(null); })}>{settings && <><div className="rental-field"><label htmlFor="settings-zone">时区</label><Input id="settings-zone" value={settings.timezone} onChange={e => setSettings({ ...settings, timezone: e.target.value })} /></div><div className="rental-field"><label htmlFor="settings-platform">默认平台</label><Select id="settings-platform" value={settings.platform} options={options(platformLabels).filter(o => o.value !== 'unknown')} onChange={platform => setSettings({ ...settings, platform })} /></div><div className="rental-field"><label htmlFor="settings-voice">账号语气</label><Input.TextArea id="settings-voice" rows={5} value={settings.voice} onChange={e => setSettings({ ...settings, voice: e.target.value })} /></div><p className="rental-muted">当前为个人私有空间。发布和回复由你完成，待办只在应用内提醒。</p></>}{error && <Alert type="error" message={error} />}</Modal>
  </div></div>;
}

export default function RentalGrowthPage() {
  const { applicationId } = useParams<{ applicationId: string }>(); const [params] = useSearchParams();
  const organizationId = useOrganizationStore(state => state.currentOrganizationId); const userId = useAuthStore(state => state.user?.id);
  if (!organizationId || !applicationId || !userId) return <Empty description="请选择组织并登录后使用。" />;
  return <RentalGrowthWorkspace key={`${organizationId}:${applicationId}:${userId}`} base={`${tenantApiRoot(organizationId)}/applications/${applicationId}/rental-growth-assistant`} showHeader={resolveApplicationPresentation(params).showApplicationHeader} />;
}
