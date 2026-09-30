import { useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Button, Checkbox, Empty, Input, Modal, Pagination, Popconfirm, Select, Spin, Tabs, Tag } from 'antd';
import { ArrowLeftOutlined, BulbOutlined, CalendarOutlined, CheckSquareOutlined, EditOutlined, FileTextOutlined, LockOutlined, PlusOutlined, PushpinOutlined, ReloadOutlined, SearchOutlined, FilterOutlined } from '@ant-design/icons';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { resolveApplicationPresentation } from '@/lib/applicationPresentation';
import { tenantApiRoot } from '@/services/tenantContext';
import { entryError, ideasTodosApi, localDate, type Entry, type EntryKind, type Idea, type Memo, type Priority, type Todo, type TodoStatus } from '@/services/ideasTodos';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import { useAuthStore } from '@/stores/useAuthStore';
import './IdeasTodosPage.css';

const priorities = [{ value: 3, label: '高优先级' }, { value: 2, label: '中优先级' }, { value: 1, label: '低优先级' }];
const statuses = [
  { value: 'pending', label: '未完成' }, { value: 'all', label: '全部' },
  { value: 'completed', label: '已完成' }, { value: 'today', label: '今日到期' }, { value: 'overdue', label: '已逾期' },
];
interface Filters { search: string; tag: string; status: TodoStatus; priority?: Priority; page: number }
const initialFilters = (): Filters => ({ search: '', tag: '', status: 'pending', page: 1 });
const entryLabels: Record<EntryKind, string> = { ideas: '想法', todos: '待办', memos: '备忘' };
const entryPresentation = {
  ideas: { title: '让灵感有个落脚点', description: '随手记录，用标签串起思路，把值得继续的想法置顶。', empty: '还没有想法，记下第一份灵感吧', icon: BulbOutlined },
  todos: { title: '把要做的事，一件件完成', description: '安排优先级与截止日期，给每一件小事一个明确的下一步。', empty: '暂无未完成待办，添加一件准备做的事吧', icon: CheckSquareOutlined },
  memos: { title: '重要的信息，随时找得到', description: '留存会议记录、常用信息和生活琐事，需要时轻松找回。', empty: '还没有备忘，记下需要留存的信息吧', icon: FileTextOutlined },
};
interface Editor { kind: EntryKind; entry?: Entry }

function EntryEditor({ editor, service, onClose, onSaved }: {
  editor: Editor; service: ReturnType<typeof ideasTodosApi>; onClose: () => void; onSaved: () => void;
}) {
  const isIdea = editor.kind === 'ideas';
  const isTodo = editor.kind === 'todos';
  const idea = isIdea ? editor.entry as Idea | undefined : undefined;
  const todo = isTodo ? editor.entry as Todo | undefined : undefined;
  const memo = editor.kind === 'memos' ? editor.entry as Memo | undefined : undefined;
  const [title, setTitle] = useState(editor.entry?.title || '');
  const [body, setBody] = useState(idea?.body || memo?.body || todo?.description || '');
  const [tags, setTags] = useState(idea?.tags || []);
  const [priority, setPriority] = useState<Priority>(todo?.priority || 2);
  const [dueDate, setDueDate] = useState(todo?.due_date || '');
  const [saving, setSaving] = useState(false);
  const savingRef = useRef(false);
  const [error, setError] = useState('');
  const [titleError, setTitleError] = useState('');
  const label = entryLabels[editor.kind];

  const save = async () => {
    if (savingRef.current) return;
    if (!title.trim()) { setTitleError('请输入标题。'); return; }
    setTitleError(''); setError(''); setSaving(true); savingRef.current = true;
    try {
      if (isIdea) {
        const input = { title: title.trim(), body, tags, is_pinned: idea?.is_pinned || false };
        if (idea) await service.updateIdea(idea.id, input);
        else await service.createIdea(input);
      } else if (isTodo) {
        const input = { title: title.trim(), description: body, priority, due_date: dueDate || null };
        if (todo) await service.updateTodo(todo.id, input);
        else await service.createTodo(input);
      } else {
        const input = { title: title.trim(), body, is_pinned: memo?.is_pinned || false };
        if (memo) await service.updateMemo(memo.id, input);
        else await service.createMemo(input);
      }
      onSaved();
    } catch (failure) { setError(entryError(failure)); }
    finally { savingRef.current = false; setSaving(false); }
  };

  return (
    <Modal open rootClassName="ideas-todos-editor" title={`${editor.entry ? '编辑' : '新增'}${label}`} onCancel={onClose}
      closable={!saving} maskClosable={false} keyboard={!saving}
      footer={[
        <Button key="cancel" onClick={onClose} disabled={saving}>取消</Button>,
        <Button key="save" type="primary" htmlType="submit" form="ideas-todos-editor" loading={saving}>保存</Button>,
      ]}>
      <form id="ideas-todos-editor" className="ideas-todos-form" onSubmit={(event) => { event.preventDefault(); void save(); }}>
        <p className="ideas-todos-editor-hint">{isIdea ? '先记下来，不必一次想完整。' : isTodo ? '写下一个具体、可以开始的行动。' : '给重要信息留一个随时能找到的位置。'}</p>
        {error && <Alert type="error" showIcon message={error} role="alert" />}
        <div>
          <label htmlFor="entry-title">标题 <span aria-hidden="true">*</span></label>
          <Input id="entry-title" autoFocus maxLength={200} value={title} disabled={saving}
            aria-required="true" aria-invalid={!!titleError} aria-describedby={titleError ? 'entry-title-error' : undefined}
            status={titleError ? 'error' : undefined} placeholder={isIdea ? '记下一个新想法' : isTodo ? '准备做什么？' : '给备忘起个标题'}
            onChange={(event) => { setTitle(event.target.value); setTitleError(''); }} />
          {titleError && <div id="entry-title-error" className="ideas-todos-field-error" role="alert">{titleError}</div>}
        </div>
        <div>
          <label htmlFor="entry-body">{isTodo ? '说明' : '正文'}</label>
          <Input.TextArea id="entry-body" value={body} maxLength={20000} rows={6} disabled={saving}
            placeholder={isIdea ? '展开记录灵感、细节或思考…' : isTodo ? '补充需要注意的细节…' : '记下常用信息、会议记录或需要留存的内容…'} onChange={(event) => setBody(event.target.value)} />
        </div>
        {isIdea ? <div>
          <label htmlFor="entry-tags">标签</label>
          <Select id="entry-tags" mode="tags" value={tags} disabled={saving} maxCount={20}
            tokenSeparators={[',', '，']} placeholder="输入标签后按回车，最多 20 个" onChange={setTags} />
        </div> : isTodo ? <div className="ideas-todos-form-row">
          <div><label htmlFor="entry-priority">优先级</label><Select id="entry-priority" value={priority} options={priorities} onChange={setPriority} disabled={saving} /></div>
          <div><label htmlFor="entry-due-date">截止日期</label><Input id="entry-due-date" type="date" value={dueDate} onChange={(event) => setDueDate(event.target.value)} disabled={saving} /></div>
        </div> : null}
      </form>
    </Modal>
  );
}

export function IdeasTodosWorkspace({ base, showHeader = true }: { base: string; showHeader?: boolean }) {
  const navigate = useNavigate();
  const service = useMemo(() => ideasTodosApi(base), [base]);
  const [kind, setKind] = useState<EntryKind>('ideas');
  const [filters, setFilters] = useState<Record<EntryKind, Filters>>({ ideas: initialFilters(), todos: initialFilters(), memos: initialFilters() });
  const active = filters[kind];
  const [entries, setEntries] = useState<Entry[]>([]);
  const [count, setCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [actionError, setActionError] = useState('');
  const [busy, setBusy] = useState<string | null>(null);
  const mutationRef = useRef(false);
  const [revision, setRevision] = useState(0);
  const [editor, setEditor] = useState<Editor | null>(null);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [today, setToday] = useState(localDate);

  useEffect(() => {
    const refreshDate = () => setToday(localDate());
    const timer = window.setInterval(refreshDate, 30000);
    window.addEventListener('focus', refreshDate);
    return () => { window.clearInterval(timer); window.removeEventListener('focus', refreshDate); };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError(''); setEntries([]);
    const timer = window.setTimeout(async () => {
      try {
        const result = await service.list(kind, {
          page: active.page, search: active.search || undefined,
          ...(kind === 'ideas' ? { tag: active.tag || undefined } : kind === 'todos' ? { status: active.status, priority: active.priority, today } : {}),
        }, controller.signal);
        if (controller.signal.aborted) return;
        setEntries(result.results); setCount(result.count);
      } catch (failure) {
        if (controller.signal.aborted) return;
        // A deleted last row can invalidate a later page; return to the beginning.
        const status = (failure as { response?: { status?: number } })?.response?.status;
        if (status === 404 && active.page > 1) {
          setFilters((old) => ({ ...old, [kind]: { ...old[kind], page: 1 } }));
        } else setError(entryError(failure));
      } finally { if (!controller.signal.aborted) setLoading(false); }
    }, active.search || active.tag ? 250 : 0);
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [active, kind, revision, service, today]);

  const changeFilter = (patch: Partial<Filters>) => {
    setFilters((old) => ({ ...old, [kind]: { ...old[kind], page: 1, ...patch } }));
  };
  const mutate = async (id: string, operation: () => Promise<unknown>) => {
    if (mutationRef.current) return;
    mutationRef.current = true; setBusy(id); setActionError('');
    try { await operation(); setRevision((old) => old + 1); }
    catch (failure) { setActionError(entryError(failure)); }
    finally { mutationRef.current = false; setBusy(null); }
  };
  const label = entryLabels[kind];
  const filterCount = kind === 'ideas' ? Number(!!active.tag) : kind === 'todos' ? Number(active.status !== 'pending') + Number(!!active.priority) : 0;
  const filtered = !!active.search || filterCount > 0;
  const presentation = entryPresentation[kind];
  const EntryIcon = presentation.icon;

  return <div className="ideas-todos-page app-scroll-page">
    <div className="ideas-todos-content">
    <header className="ideas-todos-header">
      <div className="ideas-todos-header-copy">
        {showHeader && <Button className="ideas-todos-back" type="text" icon={<ArrowLeftOutlined aria-hidden />} onClick={() => navigate('/apps')}>返回应用</Button>}
        <div className="ideas-todos-brand"><span className="ideas-todos-app-icon"><BulbOutlined aria-hidden /></span><div><span className="ideas-todos-eyebrow">你的随身记录本</span><h1>随手记</h1></div></div>
        <p>留住一闪而过的灵感，让日常有条不紊。</p>
      </div>
      <div className="ideas-todos-header-actions"><span className="ideas-todos-private"><LockOutlined aria-hidden />这里的内容仅自己可见</span><Button className="ideas-todos-create" type="primary" size="large" icon={<PlusOutlined aria-hidden />} onClick={() => { setActionError(''); setEditor({ kind }); }}>新增{label}</Button></div>
    </header>
    <Tabs className="ideas-todos-tabs" activeKey={kind} onChange={(value) => { setKind(value as EntryKind); setEntries([]); setActionError(''); }} items={[
      { key: 'ideas', label: '想法', icon: <BulbOutlined aria-hidden /> },
      { key: 'todos', label: '待办', icon: <CheckSquareOutlined aria-hidden /> },
      { key: 'memos', label: '备忘', icon: <FileTextOutlined aria-hidden /> },
    ]} />
    <section aria-label={`${label}列表`}>
      <div className="ideas-todos-section-heading"><div><h2>{presentation.title}</h2><p>{presentation.description}</p></div><div className="ideas-todos-list-summary">
        <span>{loading ? `正在整理${label}…` : error ? '暂时无法读取记录' : `${filtered ? '筛选结果' : `我的${label}`} · ${count} 条`}</span>
        {filtered && <Button type="text" size="small" onClick={() => changeFilter(initialFilters())}>清除筛选</Button>}
      </div></div>
      <div className="ideas-todos-toolbar">
        <div className="ideas-todos-search-field"><label htmlFor="ideas-todos-search">搜索{label}</label><Input id="ideas-todos-search" className="ideas-todos-search" prefix={<SearchOutlined aria-hidden />} aria-label={`搜索${label}`} maxLength={200} allowClear
          placeholder={kind === 'todos' ? '搜索标题或说明' : '搜索标题或正文'} value={active.search} onChange={(event) => changeFilter({ search: event.target.value })} /></div>
        {kind !== 'memos' && <Button className="ideas-todos-filter-toggle" icon={<FilterOutlined aria-hidden />} type={filtersOpen || filterCount ? 'primary' : 'default'}
          aria-expanded={filtersOpen} aria-controls="ideas-todos-filters" onClick={() => setFiltersOpen(open => !open)}>筛选{filterCount > 0 ? ` · ${filterCount}` : ''}</Button>}
        <Button className="ideas-todos-refresh" icon={<ReloadOutlined aria-hidden />} aria-label="刷新列表" title="刷新列表" onClick={() => setRevision((old) => old + 1)} disabled={loading} />
        {kind !== 'memos' && <div id="ideas-todos-filters" className={`ideas-todos-filters${filtersOpen ? ' is-open' : ''}`}>
        {kind === 'ideas' ? <div className="ideas-todos-filter-field"><label htmlFor="ideas-filter-tag">标签</label><Input id="ideas-filter-tag" aria-label="筛选标签" placeholder="筛选标签关键词" maxLength={40} value={active.tag} allowClear onChange={(event) => changeFilter({ tag: event.target.value })} /></div> : kind === 'todos' ? <>
          <div className="ideas-todos-filter-field"><label htmlFor="todos-filter-status">完成状态</label><Select id="todos-filter-status" aria-label="待办状态" value={active.status} options={statuses} onChange={(status) => changeFilter({ status })} /></div>
          <div className="ideas-todos-filter-field"><label htmlFor="todos-filter-priority">优先级</label><Select id="todos-filter-priority" aria-label="筛选优先级" placeholder="全部优先级" allowClear value={active.priority} options={priorities} onChange={(priority) => changeFilter({ priority })} /></div>
        </> : null}
        </div>}
      </div>
      {actionError && <Alert type="error" showIcon message={actionError} role="alert" closable onClose={() => setActionError('')} />}
      {error ? <Alert type="error" showIcon message={error} role="alert" action={<Button onClick={() => setRevision((old) => old + 1)}>重试</Button>} /> : loading ?
        <div className="ideas-todos-loading" role="status" aria-label="正在加载"><Spin /><span>正在加载{label}…</span></div> : <>
          {entries.length === 0 ? <div className="ideas-todos-empty"><Empty image={<span className="ideas-todos-empty-icon">{filtered ? <SearchOutlined aria-hidden /> : <EntryIcon aria-hidden />}</span>} description={<><h3>{filtered ? '没有符合条件的记录' : presentation.empty}</h3><p>{filtered ? '试试其他关键词，或清除筛选重新查看。' : '从一条简单的记录开始，慢慢整理自己的节奏。'}</p></>}><Button icon={filtered ? <FilterOutlined aria-hidden /> : <PlusOutlined aria-hidden />} onClick={() => filtered ? changeFilter(initialFilters()) : setEditor({ kind })}>{filtered ? '重置筛选' : `记录一条${label}`}</Button></Empty></div> :
            <ul className={`ideas-todos-list ${kind !== 'todos' ? 'ideas-todos-grid' : ''}`}>
              {entries.map((entry) => {
                const idea = kind === 'ideas' ? entry as Idea : undefined;
                const todo = kind === 'todos' ? entry as Todo : undefined;
                const memo = kind === 'memos' ? entry as Memo : undefined;
                const note = idea || memo;
                return <li key={entry.id} className={`ideas-todos-card${todo ? ' is-todo' : ''}${note?.is_pinned ? ' is-pinned' : ''}${todo?.is_completed ? ' is-completed' : ''}`}>
                  <div className="ideas-todos-card-main">
                  {note && <div className="ideas-todos-card-kicker"><span><EntryIcon aria-hidden />{idea ? '灵感笔记' : '日常备忘'}</span>{note.is_pinned && <span className="ideas-todos-pin"><PushpinOutlined aria-hidden />已置顶</span>}</div>}
                  <div className="ideas-todos-card-title">
                    {todo && <Checkbox aria-label={`${todo.is_completed ? '恢复未完成' : '完成'}：${entry.title}`} checked={todo.is_completed} disabled={busy !== null}
                      onChange={() => void mutate(entry.id, () => service.updateTodo(entry.id, { is_completed: !todo.is_completed }))} />}
                    <h3>{entry.title}</h3>
                  </div>
                  {(note?.body || todo?.description) && <p className="ideas-todos-preview">{note?.body || todo?.description}</p>}
                  <div className="ideas-todos-meta">
                    {idea?.tags.map((tag) => <Tag key={tag}>{tag}</Tag>)}
                    {todo && <>
                      <Tag color={todo.priority === 3 ? 'red' : todo.priority === 2 ? 'blue' : undefined}>{priorities.find((item) => item.value === todo.priority)?.label}</Tag>
                      {todo.due_date && <Tag icon={<CalendarOutlined aria-hidden />} color={!todo.is_completed && todo.due_date < today ? 'red' : undefined}>
                        {todo.due_date}{!todo.is_completed && (todo.due_date < today ? ' · 已逾期' : todo.due_date === today ? ' · 今日到期' : '')}
                      </Tag>}
                      {todo.is_completed && <Tag>已完成</Tag>}
                    </>}
                  </div>
                  </div>
                  <div className="ideas-todos-card-footer">
                    <time dateTime={entry.updated_at}>更新于 {new Date(entry.updated_at).toLocaleDateString('zh-CN')}</time>
                    <div className="ideas-todos-actions">
                      {idea && <Button type="text" size="small" disabled={busy !== null} onClick={() => void mutate(entry.id, () => service.updateIdea(entry.id, { is_pinned: !idea.is_pinned }))}>{idea.is_pinned ? '取消置顶' : '置顶'}</Button>}
                      {memo && <Button type="text" size="small" disabled={busy !== null} onClick={() => void mutate(entry.id, () => service.updateMemo(entry.id, { is_pinned: !memo.is_pinned }))}>{memo.is_pinned ? '取消置顶' : '置顶'}</Button>}
                      <Button type="text" size="small" icon={<EditOutlined aria-hidden />} disabled={busy !== null} onClick={() => setEditor({ kind, entry })}>编辑</Button>
                      <Popconfirm title={`删除这条${label}？`} description="删除后无法恢复。" okText="删除" cancelText="取消" onConfirm={() => mutate(entry.id, () => service.remove(kind, entry.id))}>
                        <Button type="text" danger size="small" disabled={busy !== null} loading={busy === entry.id}>删除</Button>
                      </Popconfirm>
                    </div>
                  </div>
                </li>;
              })}
            </ul>}
          <Pagination current={active.page} total={count} pageSize={20} showSizeChanger={false} hideOnSinglePage
            showTotal={(total) => `共 ${total} 条`} onChange={(page) => changeFilter({ page })} />
        </>}
    </section>
    </div>
    {editor && <EntryEditor editor={editor} service={service} onClose={() => setEditor(null)} onSaved={() => {
      setEditor(null); setActionError(''); changeFilter({ page: 1 }); setRevision((old) => old + 1);
    }} />}
  </div>;
}

export default function IdeasTodosPage() {
  const { applicationId } = useParams<{ applicationId: string }>();
  const [searchParams] = useSearchParams();
  const organizationId = useOrganizationStore((state) => state.currentOrganizationId);
  const userId = useAuthStore((state) => state.user?.id);
  if (!organizationId || !applicationId || !userId) return <Empty description="请选择组织并登录后使用。" />;
  return <IdeasTodosWorkspace key={`${organizationId}:${applicationId}:${userId}`}
    base={`${tenantApiRoot(organizationId)}/applications/${applicationId}/ideas-todos`}
    showHeader={resolveApplicationPresentation(searchParams).showApplicationHeader} />;
}
