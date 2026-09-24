import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { Alert, Breadcrumb, Button, Empty, Input, Modal, Pagination, Progress, Segmented, Select, Space, Spin, Table, Upload, message } from 'antd';
import { ArrowDownUp, ArrowLeft, Cloud, File, FileText, Folder, FolderOpen, FolderPlus, HardDrive, Image, LockKeyhole, Music2, RefreshCw, Trash2, UploadCloud, Video } from 'lucide-react';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { tenantApiRoot } from '@/services/tenantContext';
import { resolveApplicationPresentation } from '@/lib/applicationPresentation';
import { driveError, formatBytes, myDriveApi, type DriveAction, type DriveClient, type DriveEntry, type DriveListing, type PreviewKind } from '@/services/myDrive';
import { DriveTransfers, type DriveTransfer } from '@/services/driveTransfers';
import './MyDrivePage.css';

const statuses = { queued: '等待上传', checking: '校验原文件', uploading: '上传中', paused: '已暂停', error: '上传失败', completed: '已完成', cancelling: '等待清理', cancelled: '已取消' };
const blankListing: DriveListing = { count: 0, results: [], breadcrumbs: [], capacity: { used: 0, reserved: 0, limit: 0, max_file_size: 0 } };
const fileTypes = [
  { value: 'all', label: '全部类型', icon: FolderOpen },
  { value: 'folder', label: '文件夹', icon: Folder },
  { value: 'image', label: '图片', icon: Image },
  { value: 'video', label: '视频', icon: Video },
  { value: 'audio', label: '音频', icon: Music2 },
  { value: 'other', label: '其他文件', icon: FileText },
];

function FileIcon({ entry }: { entry: DriveEntry }) {
  const kind = entry.kind === 'folder' ? 'folder' : entry.media_type.split('/')[0];
  const Icon = kind === 'folder' ? Folder : kind === 'image' ? Image : kind === 'video' ? Video : kind === 'audio' ? Music2 : File;
  return <span className={`drive-entry-icon drive-entry-icon--${['folder', 'image', 'video', 'audio'].includes(kind) ? kind : 'file'}`}><Icon size={21} aria-hidden="true" /></span>;
}

function Preview({ entry, client, close, download }: { entry: DriveEntry; client: DriveClient; close: () => void; download: () => void }) {
  const [content, setContent] = useState<{ url: string; kind: PreviewKind; text?: string }>();
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const media = useRef<HTMLVideoElement & HTMLAudioElement>(null);
  const position = useRef(0);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    setError('');
    void client.access(entry.id, 'preview').then(async (value) => {
      let text: string | undefined;
      if (value.kind === 'text') {
        const response = await fetch(value.url, { signal: controller.signal, referrerPolicy: 'no-referrer' });
        if (!response.ok) throw new Error('预览已过期或文件不可用，请重试。');
        text = await response.text();
      }
      if (!controller.signal.aborted) {
        position.current = media.current?.currentTime || 0;
        setContent({ ...value, text });
        timer = setTimeout(() => setRevision((n) => n + 1), Math.max(1000, (value.expires_in - 60) * 1000));
      }
    }).catch((e) => { if (!controller.signal.aborted) setError(driveError(e)); });
    return () => { controller.abort(); clearTimeout(timer); };
  }, [client, entry.id, revision]);
  const failure = () => setError('浏览器无法预览此文件或访问已过期，可重试或下载后打开。');
  return <Modal open title={entry.name} onCancel={close} width={900} footer={<Space><Button onClick={() => setRevision((n) => n + 1)}>重新加载</Button><Button type="primary" onClick={download}>下载文件</Button></Space>}>
    {error ? <Alert type="warning" message={error} /> : !content ? <Spin /> : <div className="drive-preview">
      {content.kind === 'image' && <img src={content.url} alt={entry.name} onError={failure} referrerPolicy="no-referrer" />}
      {content.kind === 'video' && <video ref={media} src={content.url} controls preload="metadata" onError={failure} onLoadedMetadata={() => { if (media.current) media.current.currentTime = position.current; }} />}
      {content.kind === 'audio' && <audio ref={media} src={content.url} controls preload="metadata" onError={failure} onLoadedMetadata={() => { if (media.current) media.current.currentTime = position.current; }} />}
      {content.kind === 'text' && <><p>纯文本预览 · 最多显示前 1 MiB</p><pre>{content.text}</pre></>}
    </div>}
  </Modal>;
}

export function MyDriveWorkspace({ base, showHeader = true }: { base: string; showHeader?: boolean }) {
  const client = useMemo(() => myDriveApi(base), [base]);
  const [scope, setScope] = useState('files');
  const [parent, setParent] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [type, setType] = useState('all');
  const [sort, setSort] = useState('-updated_at');
  const [page, setPage] = useState(1);
  const [revision, setRevision] = useState(0);
  const [listing, setListing] = useState(blankListing);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [selected, setSelected] = useState<string[]>([]);
  const [tasks, setTasks] = useState<DriveTransfer[]>([]);
  const [transferError, setTransferError] = useState('');
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<DriveEntry>();
  const [edit, setEdit] = useState<{ kind: 'folder' | 'rename' | 'move'; ids: string[] }>();
  const [name, setName] = useState('');
  const [destination, setDestination] = useState<string | null>(null);
  const [destPage, setDestPage] = useState(1);
  const [destListing, setDestListing] = useState(blankListing);
  const [destLoading, setDestLoading] = useState(false);
  const [editError, setEditError] = useState('');
  const [confirm, setConfirm] = useState<{ action: 'trash' | 'purge'; ids: string[] }>();
  const manager = useRef<DriveTransfers>();
  const resumeInput = useRef<HTMLInputElement>(null);
  const resumeId = useRef('');
  const refresh = useCallback(() => { setRevision((n) => n + 1); setSelected([]); }, []);
  useEffect(() => {
    const transfers = new DriveTransfers(client, setTasks, refresh);
    manager.current = transfers;
    void transfers.load().catch((e) => setTransferError(driveError(e)));
    return () => transfers.dispose();
  }, [client, refresh]);
  useEffect(() => {
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (manager.current?.tasks.some((task) => ['queued', 'checking', 'uploading'].includes(task.status))) { event.preventDefault(); event.returnValue = ''; }
    };
    window.addEventListener('beforeunload', beforeUnload);
    return () => window.removeEventListener('beforeunload', beforeUnload);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError('');
    const timer = setTimeout(() => {
      void client.list({ scope: scope === 'trash' ? 'trash' : 'files', parent, search, type, sort, page }, controller.signal)
        .then((value) => { if (!controller.signal.aborted) { setListing(value); if (!value.results.length && page > 1) setPage(page - 1); } })
        .catch((e) => { if (!controller.signal.aborted) setError(driveError(e)); })
        .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    }, search ? 250 : 0);
    return () => { controller.abort(); clearTimeout(timer); };
  }, [client, scope, parent, search, type, sort, page, revision]);
  useEffect(() => {
    if (edit?.kind !== 'move') return;
    const controller = new AbortController();
    setDestLoading(true); setEditError('');
    void client.list({ parent: destination, type: 'folder', page: destPage, sort: 'name' }, controller.signal)
      .then((value) => { if (!controller.signal.aborted) setDestListing(value); })
      .catch((e) => { if (!controller.signal.aborted) setEditError(driveError(e)); })
      .finally(() => { if (!controller.signal.aborted) setDestLoading(false); });
    return () => controller.abort();
  }, [client, edit, destination, destPage]);
  const navigate = (id: string | null) => { setParent(id); setPage(1); setSearch(''); setSelected([]); };
  const changeScope = (value: string) => { setScope(value); setPage(1); setSelected([]); setSearch(''); setType('all'); };
  const download = async (entry: DriveEntry) => {
    try {
      const value = await client.access(entry.id, 'download');
      const link = document.createElement('a'); link.href = value.url; link.download = entry.name; link.referrerPolicy = 'no-referrer';
      document.body.appendChild(link); link.click(); link.remove();
    } catch (e) { void message.error(driveError(e)); }
  };
  const act = async (action: DriveAction, ids: string[], extra?: { name?: string; parent?: string | null }) => {
    await client.action(action, ids, extra); refresh();
  };
  const openEdit = (kind: 'folder' | 'rename' | 'move', ids: string[], initialName = '') => { setEdit({ kind, ids }); setName(initialName); setDestination(null); setDestPage(1); setEditError(''); };
  const saveEdit = async () => {
    if (!edit) return;
    setBusy(true); setEditError('');
    try {
      if (edit.kind === 'folder') { await client.folder(name, parent); refresh(); }
      else await act(edit.kind, edit.ids, edit.kind === 'rename' ? { name } : { parent: destination });
      setEdit(undefined);
    } catch (e) { setEditError(driveError(e)); }
    finally { setBusy(false); }
  };
  const addFiles = async (file: File) => {
    try {
      if (listing.capacity.max_file_size && file.size > listing.capacity.max_file_size) throw new Error(`单文件上限为 ${formatBytes(listing.capacity.max_file_size)}`);
      await manager.current?.add(file, parent); refresh();
    } catch (e) { setTransferError(`${file.name}：${driveError(e)}`); }
  };
  const resume = (task: DriveTransfer) => {
    if (!task.file) { resumeId.current = task.upload.id; resumeInput.current?.click(); return; }
    try { manager.current?.resume(task.upload.id); } catch (e) { setTransferError(driveError(e)); }
  };
  const fileAction = (entry: DriveEntry) => entry.kind === 'folder' ? navigate(entry.id) : setPreview(entry);
  const capacity = listing.capacity;
  return <section className="drive-workspace" aria-label="我的网盘">
    <aside className="drive-sidebar">
      {showHeader && <Link className="drive-back" to="/apps"><ArrowLeft size={14} aria-hidden="true" />返回应用</Link>}
      <header><div className="drive-app-icon"><Cloud aria-hidden="true" size={25} /></div><h1>我的网盘</h1></header>
      <p>属于你的文件与素材空间</p>
      <Segmented aria-label="网盘导航" vertical block value={scope} onChange={(value) => changeScope(String(value))} options={[{ label: '全部文件', value: 'files', icon: <FolderOpen size={18} aria-hidden="true" /> }, { label: '传输列表', value: 'transfers', icon: <ArrowDownUp size={18} aria-hidden="true" /> }, { label: '回收站', value: 'trash', icon: <Trash2 size={18} aria-hidden="true" /> }]} />
      <div className="drive-capacity"><strong><HardDrive size={16} aria-hidden="true" />存储空间</strong><span><b>{formatBytes(capacity.used)}</b> / {formatBytes(capacity.limit)}</span><Progress strokeColor="var(--color-primary)" percent={capacity.limit ? Math.min(100, Math.round((capacity.used + capacity.reserved) / capacity.limit * 100)) : 0} showInfo={false} /><small>上传预留 {formatBytes(capacity.reserved)}<br />回收站中的文件也占用容量</small></div>
      <div className="drive-private-note"><LockKeyhole size={13} aria-hidden="true" />私人空间 · 文件仅自己可见</div>
    </aside>
    <main className="drive-main">
      <header className="drive-title"><div><span className="drive-eyebrow">{scope === 'files' ? '你的云端素材库' : scope === 'trash' ? '找回需要的文件' : '每一份文件，有迹可循'}</span><h2>{scope === 'files' ? '全部文件' : scope === 'trash' ? '回收站' : '传输列表'}</h2><p>{scope === 'trash' ? '文件会保留至你永久删除，删除清理完成后释放空间。' : scope === 'transfers' ? '刷新页面后，重新选择原文件即可续传。离开页面会暂停传输。' : '收好每一份灵感，让文件与素材井井有条。'}</p></div><Button icon={<RefreshCw size={15} aria-hidden="true" />} onClick={() => { refresh(); void manager.current?.load().catch((e) => setTransferError(driveError(e))); }}>刷新</Button></header>
      {transferError && <Alert type="error" closable onClose={() => setTransferError('')} message={transferError} />}
      {scope !== 'transfers' && tasks.some((task) => ['queued', 'checking', 'uploading', 'error'].includes(task.status)) && <Alert type="info" message={`${tasks.filter((task) => ['queued', 'checking', 'uploading'].includes(task.status)).length} 个文件正在传输${tasks.some((task) => task.status === 'error') ? '，部分任务需要处理' : ''}`} action={<Button onClick={() => changeScope('transfers')}>查看传输</Button>} />}
      {scope === 'transfers' ? <>
        <input type="file" ref={resumeInput} hidden aria-label="重新选择原文件" onChange={(event) => { const file = event.target.files?.[0]; if (file) { try { manager.current?.resume(resumeId.current, file); } catch (e) { setTransferError(driveError(e)); } } event.target.value = ''; }} />
        {!tasks.length ? <div className="drive-empty-panel"><span className="drive-empty-icon"><ArrowDownUp size={30} aria-hidden="true" /></span><h3>还没有传输任务</h3><p>上传进度与续传操作都会显示在这里</p><Button onClick={() => changeScope('files')}>前往上传文件</Button></div> : <ul className="drive-transfers">{tasks.map((task) => <li key={task.upload.id}>
          <div className="drive-transfer-title"><strong>{task.upload.name}</strong><span>{statuses[task.status]}</span></div>
          <Progress percent={task.upload.size ? Math.floor(task.upload.offset / task.upload.size * 100) : task.status === 'completed' ? 100 : 0} status={task.status === 'error' ? 'exception' : task.status === 'completed' ? 'success' : 'normal'} />
          <p>{formatBytes(task.upload.offset)} / {formatBytes(task.upload.size)}{task.speed > 0 && ` · ${formatBytes(task.speed)}/s`}</p>
          {task.error && <p role="alert">{task.error}</p>}
          <Space>{['queued', 'checking', 'uploading'].includes(task.status) && <Button onClick={() => manager.current?.pause(task.upload.id)}>暂停</Button>}{['paused', 'error'].includes(task.status) && <Button onClick={() => resume(task)}>{task.file ? '继续 / 重试' : '选择原文件续传'}</Button>}{!['completed', 'cancelled', 'cancelling'].includes(task.status) && <Button onClick={() => void manager.current?.cancel(task.upload.id)}>取消上传</Button>}</Space>
        </li>)}</ul>}
      </> : <>
        {scope === 'files' && <>
          <Breadcrumb items={[{ title: <button onClick={() => navigate(null)}>全部文件</button> }, ...listing.breadcrumbs.map((crumb) => ({ title: <button onClick={() => navigate(crumb.id)}>{crumb.name}</button> }))]} />
          <div className="drive-upload"><Upload.Dragger multiple showUploadList={false} beforeUpload={(file) => { void addFiles(file); return false; }}><span className="drive-upload-icon"><UploadCloud size={28} aria-hidden="true" /></span><div className="drive-upload-copy"><strong>把灵感与素材，放在这里</strong><span>点击或拖拽文件上传 · 单文件上限 {formatBytes(capacity.max_file_size)}</span></div><span className="drive-upload-cta">上传文件</span><span className="drive-upload-hint">支持大文件 · 断点续传</span></Upload.Dragger></div>
          <div className="drive-file-types" role="group" aria-label="文件分类">{fileTypes.map(({ value, label, icon: Icon }) => <button key={value} type="button" aria-pressed={type === value} className={type === value ? 'is-active' : ''} onClick={() => { setType(value); setPage(1); setSelected([]); }}><Icon size={19} aria-hidden="true" /><span>{label}</span></button>)}</div>
        </>}
        <div className="drive-toolbar">
          <Input.Search placeholder="搜索整个网盘的文件名" aria-label="搜索文件" allowClear value={search} onChange={(event) => { setSearch(event.target.value); setPage(1); setSelected([]); }} />
          {scope === 'trash' && <Select aria-label="文件类型" value={type} onChange={(value) => { setType(value); setPage(1); setSelected([]); }} options={fileTypes.map(({ value, label }) => ({ value, label }))} />}
          <Select aria-label="文件排序" value={sort} onChange={(value) => { setSort(value); setPage(1); }} options={[{ value: '-updated_at', label: '最近更新' }, { value: 'name', label: '名称升序' }, { value: '-size', label: '大小降序' }]} />
          {scope === 'files' && <Button icon={<FolderPlus size={16} />} onClick={() => openEdit('folder', [])}>新建文件夹</Button>}
        </div>
        <div className="drive-list-heading"><h3>{search ? '搜索结果' : scope === 'trash' ? '已删除文件' : parent ? listing.breadcrumbs[listing.breadcrumbs.length - 1]?.name || '当前文件夹' : '文件列表'}<span>{loading ? '加载中…' : `${listing.count} 项`}</span></h3><span>{search ? '搜索范围：整个网盘' : '选择文件可批量管理'}</span></div>
        {selected.length > 0 && <Space className="drive-selection-bar" wrap><span>已选 {selected.length} 项</span>{scope === 'files' ? <><Button onClick={() => openEdit('move', selected)}>批量移动</Button><Button danger onClick={() => setConfirm({ action: 'trash', ids: selected })}>移入回收站</Button></> : <><Button onClick={() => void act('restore', selected).catch((e) => message.error(driveError(e)))}>恢复</Button><Button danger onClick={() => setConfirm({ action: 'purge', ids: selected })}>永久删除</Button></>}</Space>}
        {error ? <Alert type="error" message={error} action={<Button onClick={refresh}>重试</Button>} /> : <Table<DriveEntry> className="drive-table" rowKey="id" loading={loading} dataSource={listing.results} pagination={false} rowSelection={{ selectedRowKeys: selected, onChange: (keys) => setSelected(keys.map(String)) }} locale={{ emptyText: <Empty description={search ? '没有找到匹配的文件' : scope === 'trash' ? '回收站是空的' : '上传文件或创建文件夹，开始整理素材'} /> }} columns={[
          { title: '名称', dataIndex: 'name', render: (_, entry) => <button className="drive-file-name" disabled={scope === 'trash'} onClick={() => fileAction(entry)}><FileIcon entry={entry} /><span>{entry.name}</span></button> },
          { title: '大小', width: 110, responsive: ['md'], render: (_, entry) => entry.kind === 'folder' ? '—' : formatBytes(entry.size) },
          { title: '更新时间', width: 155, responsive: ['lg'], render: (_, entry) => new Date(entry.updated_at).toLocaleString('zh-CN') },
          { title: '操作', width: 210, render: (_, entry) => <Space wrap size={0}>{scope === 'trash' ? <><Button type="link" onClick={() => void act('restore', [entry.id]).catch((e) => message.error(driveError(e)))}>恢复</Button><Button type="link" danger onClick={() => setConfirm({ action: 'purge', ids: [entry.id] })}>永久删除</Button></> : <>{entry.kind === 'file' && <Button type="link" onClick={() => void download(entry)}>下载</Button>}<Button type="link" onClick={() => openEdit('rename', [entry.id], entry.name)}>重命名</Button><Button type="link" onClick={() => openEdit('move', [entry.id])}>移动</Button><Button type="link" danger onClick={() => setConfirm({ action: 'trash', ids: [entry.id] })}>删除</Button></>}</Space> },
        ]} />}
        <Pagination current={page} total={listing.count} pageSize={50} showSizeChanger={false} onChange={(value) => { setPage(value); setSelected([]); }} hideOnSinglePage />
      </>}
    </main>
    <Modal open={!!edit} title={edit?.kind === 'folder' ? '新建文件夹' : edit?.kind === 'rename' ? '重命名' : '移动到文件夹'} onCancel={() => !busy && setEdit(undefined)} onOk={() => void saveEdit()} confirmLoading={busy} okButtonProps={{ disabled: edit?.kind === 'move' ? destLoading || !!editError : !name.trim() }}>
      {editError && <Alert message={editError} type="error" />}
      {edit?.kind === 'move' ? <div className="drive-destinations"><Breadcrumb items={[{ title: <button onClick={() => { setDestination(null); setDestPage(1); }}>根目录</button> }, ...destListing.breadcrumbs.map((crumb) => ({ title: <button onClick={() => { setDestination(crumb.id); setDestPage(1); }}>{crumb.name}</button> }))]} /><p>将所选内容移动到当前文件夹</p>{destLoading ? <Spin /> : destListing.results.map((item) => <Button key={item.id} block disabled={edit.ids.includes(item.id)} onClick={() => { setDestination(item.id); setDestPage(1); }}>{item.name}</Button>)}<Pagination current={destPage} total={destListing.count} pageSize={50} showSizeChanger={false} onChange={setDestPage} hideOnSinglePage /></div> : <><label htmlFor="drive-name">名称</label><Input id="drive-name" maxLength={240} value={name} onChange={(event) => setName(event.target.value)} onPressEnter={() => !busy && !!name.trim() && void saveEdit()} /></>}
    </Modal>
    <Modal open={!!confirm} title={confirm?.action === 'purge' ? '永久删除所选文件？' : '移入回收站？'} onCancel={() => !busy && setConfirm(undefined)} confirmLoading={busy} okButtonProps={{ danger: true }} onOk={() => { if (!confirm) return; setBusy(true); void act(confirm.action, confirm.ids).then(() => setConfirm(undefined)).catch((e) => message.error(driveError(e))).finally(() => setBusy(false)); }}><p>{confirm?.action === 'purge' ? '此操作无法恢复。系统会在后台清理文件，完成后释放空间。' : '文件夹及其中的文件将一起移入回收站，可以随时恢复。'}</p></Modal>
    {preview && <Preview key={preview.id} entry={preview} client={client} close={() => setPreview(undefined)} download={() => void download(preview)} />}
  </section>;
}

export default function MyDrivePage() {
  const { applicationId } = useParams<{ applicationId: string }>();
  const [params] = useSearchParams();
  const organizationId = useOrganizationStore((state) => state.currentOrganizationId);
  const userId = useAuthStore((state) => state.user?.id);
  if (!organizationId || !applicationId || !userId) return <Empty description="请选择组织并登录后使用。" />;
  return <MyDriveWorkspace key={`${organizationId}:${applicationId}:${userId}`} base={`${tenantApiRoot(organizationId)}/applications/${applicationId}/my-drive`} showHeader={resolveApplicationPresentation(params).showApplicationHeader} />;
}
