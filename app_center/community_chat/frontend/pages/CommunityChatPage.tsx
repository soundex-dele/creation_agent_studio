import { useCallback, useEffect, useRef, useState } from 'react';
import { Alert, Avatar, Badge, Button, Empty, Input, Spin, message } from 'antd';
import { ArrowDownOutlined, ArrowLeftOutlined, CloseOutlined, CommentOutlined, FileAddOutlined, GlobalOutlined, PlusOutlined, SendOutlined, TeamOutlined, UserOutlined } from '@ant-design/icons';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { resolveApplicationPresentation } from '@/lib/applicationPresentation';
import { chat, connectChat, createDraft, errorText, formatSize, isDenied, MAX_BYTES, mergeMessageChanges, mergeMessages, sendDraft, type ChatMessage, type ChatRoom, type ChatUser, type Draft } from '../services/chat';
import ChatMessageRow from './ChatMessageRow';
import { GroupDrawer, NewChatDialog } from './RoomDialogs';
import './CommunityChatPage.css';

function ChatPane({ room, me, tick, drafts, onSend, onRetry, onConfirmed, onBack, onRefresh, onDenied, onManage }: {
  room: ChatRoom; me: ChatUser; tick: number; onBack: () => void; onRefresh: () => void; onDenied: () => void; onManage: () => void;
  drafts: Draft[]; onSend: (draft: Draft) => void; onRetry: (draft: Draft) => void;
  onConfirmed: (roomId: string, keys: string[]) => void;
}) {
  const [items, setItems] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(true);
  const [olderLoading, setOlderLoading] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [error, setError] = useState('');
  const [text, setText] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [newBelow, setNewBelow] = useState(false);
  const viewport = useRef<HTMLDivElement>(null);
  const messageFlow = useRef<HTMLDivElement>(null);
  const picker = useRef<HTMLInputElement>(null);
  const revision = useRef<number | null>(null);
  const current = useRef<ChatMessage[]>([]);
  const nearBottom = useRef(true);
  const alive = useRef(true);
  const readId = useRef(room.last_read_id);
  const syncing = useRef(false);
  const again = useRef(false);
  const composing = useRef(false);
  const scrollToEnd = useRef(false);
  const callbacks = useRef({ onRefresh, onDenied });
  callbacks.current = { onRefresh, onDenied };

  const readLatest = useCallback(() => {
    if (!nearBottom.current || document.visibilityState === 'hidden') return;
    const id = current.current[current.current.length - 1]?.id || 0;
    if (id <= readId.current) return;
    const previous = readId.current;
    readId.current = id;
    void chat.read(room.id, id).then(() => callbacks.current.onRefresh()).catch(() => { readId.current = previous; });
  }, [room.id]);

  const accept = useCallback((incoming: ChatMessage[], initial = false) => {
    const oldLast = current.current[current.current.length - 1]?.id || 0;
    const next = initial ? mergeMessages(current.current, incoming) : mergeMessageChanges(current.current, incoming);
    current.current = next;
    setItems(next);
    onConfirmed(room.id, next.filter(item => item.author.id === me.id).map(item => item.request_key));
    if (initial || nearBottom.current) scrollToEnd.current = true;
    else if (incoming.some(item => item.id > oldLast)) setNewBelow(true);
    readLatest();
  }, [readLatest, onConfirmed, room.id, me.id]);

  const sync = useCallback(async () => {
    if (syncing.current) { again.current = true; return; }
    syncing.current = true;
    try {
      do {
        again.current = false;
        const initial = revision.current === null;
        const result = await chat.messages(room.id, initial ? {} : { after_revision: revision.current! });
        if (!alive.current) return;
        revision.current = result.revision;
        if (initial) setHasMore(result.has_more);
        accept(result.messages, initial);
        setError(''); setLoading(false);
        if (!initial && result.has_more) again.current = true;
      } while (again.current && alive.current);
    } catch (err) {
      if (alive.current) {
        if (isDenied(err)) callbacks.current.onDenied();
        else setError(errorText(err));
        setLoading(false);
      }
    } finally { syncing.current = false; }
  }, [room.id, accept]);

  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; };
  }, []);
  useEffect(() => { void sync(); }, [tick, sync]);
  useEffect(() => {
    if (scrollToEnd.current && viewport.current) {
      viewport.current.scrollTop = viewport.current.scrollHeight;
      scrollToEnd.current = false;
      setNewBelow(false);
    }
  }, [items, drafts]);
  useEffect(() => {
    const visible = () => readLatest();
    document.addEventListener('visibilitychange', visible);
    return () => document.removeEventListener('visibilitychange', visible);
  }, [readLatest]);
  useEffect(() => {
    const observer = new ResizeObserver(() => {
      if (nearBottom.current && viewport.current) viewport.current.scrollTop = viewport.current.scrollHeight;
    });
    if (messageFlow.current) observer.observe(messageFlow.current);
    if (viewport.current) observer.observe(viewport.current);
    return () => observer.disconnect();
  }, []);

  const older = async () => {
    if (!items.length || olderLoading) return;
    setOlderLoading(true);
    const node = viewport.current;
    const height = node?.scrollHeight || 0;
    const top = node?.scrollTop || 0;
    try {
      const result = await chat.messages(room.id, { before: items[0].id });
      if (!alive.current) return;
      const next = mergeMessages(current.current, result.messages);
      nearBottom.current = false;
      current.current = next; setItems(next); setHasMore(result.has_more);
      requestAnimationFrame(() => { if (node && alive.current) node.scrollTop = top + node.scrollHeight - height; });
    } catch (err) { message.error(errorText(err)); }
    finally { if (alive.current) setOlderLoading(false); }
  };

  const addFiles = (incoming: File[]) => {
    setFiles(previous => {
      const next = [...previous, ...incoming];
      if (next.length > 9 || next.some(f => !f.size || f.size > MAX_BYTES) || next.reduce((n, f) => n + f.size, 0) > MAX_BYTES) {
        message.error('最多 9 个非空附件，单文件及总大小均不超过 100MB。');
        return previous;
      }
      return next;
    });
  };
  const submit = () => {
    try {
      const draft = createDraft(room.id, text, files);
      setText(''); setFiles([]);
      nearBottom.current = true; scrollToEnd.current = true;
      onSend(draft);
    } catch (err) { message.error(errorText(err)); }
  };
  const withdraw = async (id: number) => {
    try { accept([await chat.withdraw(room.id, id)]); callbacks.current.onRefresh(); }
    catch (err) { message.error(errorText(err)); }
  };
  const bottom = () => {
    if (viewport.current) viewport.current.scrollTop = viewport.current.scrollHeight;
    nearBottom.current = true; setNewBelow(false); readLatest();
  };
  const visibleItems = mergeMessages(items, drafts.flatMap(draft => draft.sent ? [draft.sent] : []));
  const rows = [
    ...visibleItems.map(item => ({ key: `${item.author.id}:${item.request_key}`, item, draft: undefined as Draft | undefined })),
    ...drafts.filter(draft => !visibleItems.some(item => item.author.id === me.id && item.request_key === draft.key))
      .map(draft => ({ key: `${me.id}:${draft.key}`, item: undefined as ChatMessage | undefined, draft })),
  ];
  return <section className="community-chat-pane" aria-label={room.name}
    onDragOver={event => { if (event.dataTransfer.types.includes('Files')) event.preventDefault(); }}
    onDrop={event => { event.preventDefault(); addFiles(Array.from(event.dataTransfer.files)); }}>
    <header className="community-room-header">
      <Button className="community-mobile-back" type="text" icon={<ArrowLeftOutlined />} aria-label="返回会话列表" onClick={onBack} />
      <div className="community-room-heading"><h2>{room.name}</h2><small>{room.kind === 'lobby' ? '全站公共空间 · 所有登录用户可见' : room.kind === 'group' ? `${room.member_count} 位成员 · 新成员可查看全部历史` : '仅你和对方可见'}</small></div>
      {room.kind === 'group' && <Button icon={<TeamOutlined />} onClick={onManage}>成员</Button>}
    </header>
    {error && <Alert type="error" message={error} action={<Button size="small" onClick={() => void sync()}>重试</Button>} />}
    <div className="community-message-list" ref={viewport} aria-label="聊天记录" onScroll={() => {
      const node = viewport.current;
      if (node) nearBottom.current = node.scrollHeight - node.scrollTop - node.clientHeight < 64;
      if (nearBottom.current) { setNewBelow(false); readLatest(); }
    }}>
      <div ref={messageFlow}>{loading ? <div className="community-centered"><Spin tip="加载消息" /></div> : <>
        <div className="community-history-action">{hasMore ? <Button type="text" loading={olderLoading} onClick={() => void older()}>加载更早的消息</Button> : <small>聊天记录起点</small>}</div>
        {!rows.length && <Empty description="还没有消息，打个招呼吧" image={Empty.PRESENTED_IMAGE_SIMPLE} />}
        {rows.map(row => <ChatMessageRow key={row.key} item={row.item} draft={row.draft} me={me} onRetry={onRetry} onWithdraw={withdraw} />)}
      </>}</div>
    </div>
    {newBelow && <Button className="community-new-messages" icon={<ArrowDownOutlined />} onClick={bottom}>有新消息，回到底部</Button>}
    <div className="community-composer">
      {!!files.length && <div className="community-selected-files">{files.map((file, index) => <div className="community-selected-file" key={index}>
        <span>{file.name}<small>{formatSize(file.size)}</small></span><Button type="text" aria-label={`移除 ${file.name}`} icon={<CloseOutlined />} onClick={() => setFiles(previous => previous.filter((_, i) => i !== index))} />
      </div>)}</div>}
      <label className="community-sr-only" htmlFor="community-message-input">消息内容</label>
      <Input.TextArea id="community-message-input" value={text} maxLength={10000} autoSize={{ minRows: 2, maxRows: 5 }} placeholder="写下消息，也可以粘贴图片…"
        onChange={event => setText(event.target.value)} onCompositionStart={() => { composing.current = true; }} onCompositionEnd={() => { composing.current = false; }}
        onPaste={event => { const images = Array.from(event.clipboardData.files).filter(f => f.type.startsWith('image/')); if (images.length) { event.preventDefault(); addFiles(images); } }}
        onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing && !composing.current && window.matchMedia('(min-width: 768px)').matches) { event.preventDefault(); if (text.trim() || files.length) submit(); } }} />
      <div className="community-composer-actions">
        <input ref={picker} type="file" multiple className="community-sr-only" tabIndex={-1} aria-label="选择附件" onChange={event => { addFiles(Array.from(event.target.files || [])); event.target.value = ''; }} />
        <Button type="text" icon={<FileAddOutlined />} onClick={() => picker.current?.click()}>图片 / 文件</Button>
        <small>最多 9 个附件 · 总计 100MB</small>
        <Button type="primary" icon={<SendOutlined />} disabled={(!text.trim() && !files.length) || loading} onClick={submit}>发送</Button>
      </div>
    </div>
  </section>;
}

export default function CommunityChatPage() {
  const [rooms, setRooms] = useState<ChatRoom[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [me, setMe] = useState<ChatUser>({ id: 0, username: '', nickname: '我', avatar: '' });
  const [kind, setKind] = useState<'direct' | 'group' | null>(null);
  const [manage, setManage] = useState(false);
  const [status, setStatus] = useState('连接中');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState('');
  const [tick, setTick] = useState(0);
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const activeDrafts = useRef(new Set<string>());
  const alive = useRef(true);
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { showApplicationHeader } = resolveApplicationPresentation(params);
  const refreshRef = useRef<() => void>(() => undefined);
  const refresh = useCallback(() => refreshRef.current(), []);
  const confirmDrafts = useCallback((roomId: string, keys: string[]) => {
    const confirmed = new Set(keys);
    setDrafts(previous => {
      const remaining = previous.filter(draft => draft.room !== roomId || !confirmed.has(draft.key));
      return remaining.length === previous.length ? previous : remaining;
    });
  }, []);
  const runDraft = async (draft: Draft) => {
    if (activeDrafts.current.has(draft.key)) return;
    activeDrafts.current.add(draft.key);
    draft.status = 'sending'; draft.error = undefined;
    setDrafts(previous => previous.some(d => d.key === draft.key) ? [...previous] : [...previous, draft]);
    try {
      const sent = await sendDraft(draft, percent => {
        draft.progress = percent;
        if (alive.current) setDrafts(previous => [...previous]);
      });
      if (alive.current) {
        draft.sent = sent;
        setDrafts(previous => [...previous]);
        refresh();
      }
    } catch (err) {
      draft.status = 'failed'; draft.error = errorText(err);
      if (alive.current) setDrafts(previous => [...previous]);
    } finally { activeDrafts.current.delete(draft.key); }
  };
  useEffect(() => {
    alive.current = true;
    let active = true;
    let busy = false;
    let queued = false;
    let identityLoaded = false;
    let debounce: ReturnType<typeof setTimeout> | undefined;
    const load = async () => {
      if (busy) { queued = true; return; }
      busy = true;
      try {
        do {
          queued = false;
          const [result, identity] = await Promise.all([chat.rooms(), identityLoaded ? Promise.resolve(null) : chat.users()]);
          if (!active) return;
          if (identity) { setMe(identity.me); identityLoaded = true; }
          setRooms(result); setError(''); setLoading(false); setTick(value => value + 1);
          setSelected(previous => previous && !result.some(r => r.id === previous) ? null : previous);
        } while (queued && active);
      } catch (err) { if (active) { setError(errorText(err)); setLoading(false); } }
      finally { busy = false; }
    };
    refreshRef.current = () => {
      // Coalesce bursts without postponing refresh forever in a busy lobby.
      if (debounce !== undefined) return;
      debounce = setTimeout(() => { debounce = undefined; void load(); }, 120);
    };
    void load();
    const disconnect = connectChat(refreshRef.current, value => { if (active) setStatus(value); });
    return () => { active = false; alive.current = false; disconnect(); clearTimeout(debounce); refreshRef.current = () => undefined; };
  }, []);
  const room = rooms.find(r => r.id === selected);
  const denied = () => { setSelected(null); setManage(false); refresh(); message.info('此会话已关闭或你已不在会话中。'); };
  return <div className={`community-page ${room ? 'community-page--selected' : ''}`}>
    {showApplicationHeader && <header className="community-app-header"><Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate(params.get('entry') === 'home' ? '/' : '/apps')}>返回</Button><CommentOutlined aria-hidden="true" /><h1>社区聊天</h1><span>让交流发生</span></header>}
    <div className="community-workspace">
      <aside className="community-sidebar" aria-label="会话列表">
        <div className="community-sidebar-heading"><div><h2>消息</h2><span className="community-connection" role="status">{status}</span></div><Badge count={rooms.reduce((n, r) => n + r.unread, 0)} color="var(--color-primary)" /></div>
        <div className="community-create-actions"><Button icon={<PlusOutlined />} onClick={() => setKind('direct')}>发起私聊</Button><Button icon={<TeamOutlined />} onClick={() => setKind('group')}>创建群聊</Button></div>
        <label className="community-sr-only" htmlFor="community-search">筛选会话</label><Input id="community-search" placeholder="筛选会话" allowClear value={query} onChange={event => setQuery(event.target.value)} />
        {error && <Alert type="error" message={error} action={<Button size="small" onClick={refresh}>重试</Button>} />}
        <nav className="community-room-list" aria-label="选择会话">
          {loading ? <div className="community-centered"><Spin /></div> : rooms.filter(r => r.name.toLocaleLowerCase().includes(query.toLocaleLowerCase())).sort((a, b) => Number(b.kind === 'lobby') - Number(a.kind === 'lobby')).map(item => <button key={item.id} className={`community-room ${item.id === selected ? 'community-room--active' : ''}`} aria-current={item.id === selected ? 'true' : undefined} onClick={() => { setSelected(item.id); setManage(false); }}>
            <Avatar icon={item.kind === 'lobby' ? <GlobalOutlined /> : item.kind === 'group' ? <TeamOutlined /> : <UserOutlined />} />
            <span className="community-room-label"><strong>{item.name}</strong><small>{item.preview}</small></span><Badge count={item.unread} overflowCount={99} />
          </button>)}
          {!loading && !rooms.some(r => r.name.toLocaleLowerCase().includes(query.toLocaleLowerCase())) && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有匹配的会话" />}
        </nav>
        <p className="community-sidebar-note">全站用户 · 真实交流<br />图片与文件，只向会话成员开放</p>
      </aside>
      {room ? <ChatPane key={room.id} room={room} me={me} tick={tick} drafts={drafts.filter(d => d.room === room.id)} onSend={draft => void runDraft(draft)} onRetry={draft => void runDraft(draft)} onConfirmed={confirmDrafts} onBack={() => setSelected(null)} onRefresh={refresh} onDenied={denied} onManage={() => setManage(true)} /> : <section className="community-welcome"><div className="community-welcome-icon"><CommentOutlined aria-hidden="true" /></div><h2>从一句问候开始</h2><p>在公共大厅分享近况，或与伙伴开启一段对话。</p><Button type="primary" onClick={() => setSelected(rooms.find(r => r.kind === 'lobby')?.id || null)} disabled={!rooms.length}>进入公共大厅</Button></section>}
    </div>
    <NewChatDialog kind={kind} onClose={() => setKind(null)} onCreated={created => { setRooms(previous => [created, ...previous.filter(r => r.id !== created.id)]); setSelected(created.id); refresh(); }} />
    <GroupDrawer room={manage && room?.kind === 'group' ? room : null} me={me.id} onClose={() => setManage(false)} onChange={refresh} />
  </div>;
}
