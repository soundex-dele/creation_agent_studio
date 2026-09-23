import { useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Button, Checkbox, Empty, Input, Modal, Pagination, Popconfirm, Select, Spin, Tabs, Tag } from 'antd';
import { ArrowLeftOutlined, BulbOutlined, CheckSquareOutlined, PlusOutlined, PushpinOutlined, ReloadOutlined, SearchOutlined } from '@ant-design/icons';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { resolveApplicationPresentation } from '@/lib/applicationPresentation';
import { tenantApiRoot } from '@/services/tenantContext';
import { entryError, ideasTodosApi, localDate, type EntryKind, type Idea, type Priority, type Todo, type TodoStatus } from '@/services/ideasTodos';
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
interface Editor { kind: EntryKind; entry?: Idea | Todo }

function EntryEditor({ editor, service, onClose, onSaved }: {
  editor: Editor; service: ReturnType<typeof ideasTodosApi>; onClose: () => void; onSaved: () => void;
}) {
  const isIdea = editor.kind === 'ideas';
  const idea = isIdea ? editor.entry as Idea | undefined : undefined;
  const todo = !isIdea ? editor.entry as Todo | undefined : undefined;
  const [title, setTitle] = useState(editor.entry?.title || '');
  const [body, setBody] = useState(idea?.body || todo?.description || '');
  const [tags, setTags] = useState(idea?.tags || []);
  const [priority, setPriority] = useState<Priority>(todo?.priority || 2);
  const [dueDate, setDueDate] = useState(todo?.due_date || '');
  const [saving, setSaving] = useState(false);
  const savingRef = useRef(false);
  const [error, setError] = useState('');
  const [titleError, setTitleError] = useState('');
  const label = isIdea ? '想法' : '待办';

  const save = async () => {
    if (savingRef.current) return;
    if (!title.trim()) { setTitleError('请输入标题。'); return; }
    setTitleError(''); setError(''); setSaving(true); savingRef.current = true;
    try {
      if (isIdea) {
        const input = { title: title.trim(), body, tags, is_pinned: idea?.is_pinned || false };
        if (idea) await service.updateIdea(idea.id, input);
        else await service.createIdea(input);
      } else {
        const input = { title: title.trim(), description: body, priority, due_date: dueDate || null };
        if (todo) await service.updateTodo(todo.id, input);
        else await service.createTodo(input);
      }
      onSaved();
    } catch (failure) { setError(entryError(failure)); }
    finally { savingRef.current = false; setSaving(false); }
  };

  return (
    <Modal open title={`${editor.entry ? '编辑' : '新增'}${label}`} onCancel={onClose}
      closable={!saving} maskClosable={false} keyboard={!saving}
      footer={[
        <Button key="cancel" onClick={onClose} disabled={saving}>取消</Button>,
        <Button key="save" type="primary" htmlType="submit" form="ideas-todos-editor" loading={saving}>保存</Button>,
      ]}>
      <form id="ideas-todos-editor" className="ideas-todos-form" onSubmit={(event) => { event.preventDefault(); void save(); }}>
        {error && <Alert type="error" showIcon message={error} role="alert" />}
        <div>
          <label htmlFor="entry-title">标题 <span aria-hidden="true">*</span></label>
          <Input id="entry-title" autoFocus maxLength={200} value={title} disabled={saving}
            aria-required="true" aria-invalid={!!titleError} aria-describedby={titleError ? 'entry-title-error' : undefined}
            status={titleError ? 'error' : undefined} placeholder={isIdea ? '记下一个新想法' : '准备做什么？'}
            onChange={(event) => { setTitle(event.target.value); setTitleError(''); }} />
          {titleError && <div id="entry-title-error" className="ideas-todos-field-error" role="alert">{titleError}</div>}
        </div>
        <div>
          <label htmlFor="entry-body">{isIdea ? '正文' : '说明'}</label>
          <Input.TextArea id="entry-body" value={body} maxLength={20000} rows={6} disabled={saving}
            placeholder={isIdea ? '展开记录灵感、细节或思考…' : '补充需要注意的细节…'} onChange={(event) => setBody(event.target.value)} />
        </div>
        {isIdea ? <div>
          <label htmlFor="entry-tags">标签</label>
          <Select id="entry-tags" mode="tags" value={tags} disabled={saving} maxCount={20}
            tokenSeparators={[',', '，']} placeholder="输入标签后按回车，最多 20 个" onChange={setTags} />
        </div> : <div className="ideas-todos-form-row">
          <div><label htmlFor="entry-priority">优先级</label><Select id="entry-priority" value={priority} options={priorities} onChange={setPriority} disabled={saving} /></div>
          <div><label htmlFor="entry-due-date">截止日期</label><Input id="entry-due-date" type="date" value={dueDate} onChange={(event) => setDueDate(event.target.value)} disabled={saving} /></div>
        </div>}
      </form>
    </Modal>
  );
}

export function IdeasTodosWorkspace({ base, showHeader = true }: { base: string; showHeader?: boolean }) {
  const navigate = useNavigate();
  const service = useMemo(() => ideasTodosApi(base), [base]);
  const [kind, setKind] = useState<EntryKind>('ideas');
  const [filters, setFilters] = useState<Record<EntryKind, Filters>>({ ideas: initialFilters(), todos: initialFilters() });
  const active = filters[kind];
  const [entries, setEntries] = useState<Array<Idea | Todo>>([]);
  const [count, setCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [actionError, setActionError] = useState('');
  const [busy, setBusy] = useState<string | null>(null);
  const mutationRef = useRef(false);
  const [revision, setRevision] = useState(0);
  const [editor, setEditor] = useState<Editor | null>(null);
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
          ...(kind === 'ideas' ? { tag: active.tag || undefined } : { status: active.status, priority: active.priority, today }),
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
  const label = kind === 'ideas' ? '想法' : '待办';

  return <div className="ideas-todos-page">
    <header className="ideas-todos-header">
      <div>
        {showHeader && <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate('/apps')}>返回应用</Button>}
        <h1>想法<span className="ideas-todos-amp">&</span>待办</h1>
        <p>留住灵感，安排日常。这里的内容仅自己可见。</p>
      </div>
      <Button type="primary" size="large" icon={<PlusOutlined />} onClick={() => { setActionError(''); setEditor({ kind }); }}>新增{label}</Button>
    </header>
    <Tabs activeKey={kind} onChange={(value) => { setKind(value as EntryKind); setEntries([]); setActionError(''); }} items={[
      { key: 'ideas', label: '想法', icon: <BulbOutlined /> },
      { key: 'todos', label: '待办', icon: <CheckSquareOutlined /> },
    ]} />
    <section aria-label={`${label}列表`}>
      <div className="ideas-todos-toolbar">
        <Input prefix={<SearchOutlined aria-hidden />} aria-label={`搜索${label}`} maxLength={200} allowClear
          placeholder={kind === 'ideas' ? '搜索标题或正文' : '搜索标题或说明'} value={active.search} onChange={(event) => changeFilter({ search: event.target.value })} />
        {kind === 'ideas' ? <Input aria-label="筛选标签" placeholder="筛选标签关键词" maxLength={40} value={active.tag} allowClear onChange={(event) => changeFilter({ tag: event.target.value })} /> : <>
          <Select aria-label="待办状态" value={active.status} options={statuses} onChange={(status) => changeFilter({ status })} />
          <Select aria-label="筛选优先级" placeholder="全部优先级" allowClear value={active.priority} options={priorities} onChange={(priority) => changeFilter({ priority })} />
        </>}
        <Button icon={<ReloadOutlined />} aria-label="刷新列表" onClick={() => setRevision((old) => old + 1)} disabled={loading} />
      </div>
      {actionError && <Alert type="error" showIcon message={actionError} role="alert" closable onClose={() => setActionError('')} />}
      {error ? <Alert type="error" showIcon message={error} role="alert" action={<Button onClick={() => setRevision((old) => old + 1)}>重试</Button>} /> : loading ?
        <div className="ideas-todos-loading" role="status" aria-label="正在加载"><Spin /><span>正在加载{label}…</span></div> : <>
          {entries.length === 0 ? <Empty description={active.search || active.tag || (kind === 'todos' && (active.status !== 'pending' || active.priority)) ? '没有符合条件的记录' : kind === 'ideas' ? '还没有想法，记下第一份灵感吧' : '暂无未完成待办，添加一件准备做的事吧'} /> :
            <ul className={`ideas-todos-list ${kind === 'ideas' ? 'ideas-todos-grid' : ''}`}>
              {entries.map((entry) => {
                const idea = kind === 'ideas' ? entry as Idea : undefined;
                const todo = kind === 'todos' ? entry as Todo : undefined;
                return <li key={entry.id} className={`ideas-todos-card ${todo?.is_completed ? 'is-completed' : ''}`}>
                  <div className="ideas-todos-card-title">
                    {todo && <Checkbox aria-label={`${todo.is_completed ? '恢复未完成' : '完成'}：${entry.title}`} checked={todo.is_completed} disabled={busy !== null}
                      onChange={() => void mutate(entry.id, () => service.updateTodo(entry.id, { is_completed: !todo.is_completed }))} />}
                    <h2>{idea?.is_pinned && <PushpinOutlined aria-label="已置顶" />} {entry.title}</h2>
                  </div>
                  {(idea?.body || todo?.description) && <p className="ideas-todos-preview">{idea?.body || todo?.description}</p>}
                  <div className="ideas-todos-meta">
                    {idea?.tags.map((tag) => <Tag key={tag}>{tag}</Tag>)}
                    {todo && <>
                      <Tag color={todo.priority === 3 ? 'red' : todo.priority === 2 ? 'blue' : undefined}>{priorities.find((item) => item.value === todo.priority)?.label}</Tag>
                      {todo.due_date && <Tag color={!todo.is_completed && todo.due_date < today ? 'red' : undefined}>
                        {todo.due_date}{!todo.is_completed && (todo.due_date < today ? ' · 已逾期' : todo.due_date === today ? ' · 今日到期' : '')}
                      </Tag>}
                      {todo.is_completed && <Tag>已完成</Tag>}
                    </>}
                  </div>
                  <div className="ideas-todos-card-footer">
                    <time dateTime={entry.updated_at}>{new Date(entry.updated_at).toLocaleDateString()}</time>
                    <div className="ideas-todos-actions">
                      {idea && <Button type="text" size="small" disabled={busy !== null} onClick={() => void mutate(entry.id, () => service.updateIdea(entry.id, { is_pinned: !idea.is_pinned }))}>{idea.is_pinned ? '取消置顶' : '置顶'}</Button>}
                      <Button type="text" size="small" disabled={busy !== null} onClick={() => setEditor({ kind, entry })}>编辑</Button>
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
