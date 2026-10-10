import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { Alert, Button, Checkbox, Empty, Input, InputNumber, Modal, Pagination, Progress, Select, Spin, Tabs, Tag } from 'antd';
import { ArrowLeft, FolderOpen, HardDrive, RefreshCw, Search, Trash2 } from 'lucide-react';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { tenantApiRoot } from '@/services/tenantContext';
import { resolveApplicationPresentation } from '@/lib/applicationPresentation';
import { driveError, formatBytes } from '@/services/myDrive';
import { cleanerActive, diskCleanerApi, type CleanerDirectories, type CleanerHost, type CleanerListing, type CleanerMode, type CleanerPreview, type CleanerTask } from '@/services/diskCleaner';
import './DiskCleanerPage.css';

const modes = { analysis: '空间分析', large: '大文件清理', cache: '临时缓存' };
const states: Record<string, string> = { queued: '等待执行', running: '正在处理', completed: '已完成', cancelled: '已停止', failed: '失败', interrupted: '已中断', deleted: '已删除', skipped: '已跳过', unknown: '结果未知', deleting: '正在删除', pending: '待处理' };
const empty: CleanerListing = { count: 0, results: [] };

export function DiskCleanerWorkspace({ base, showHeader = true }: { base: string; showHeader?: boolean }) {
  const client = useMemo(() => diskCleanerApi(base), [base]);
  const [host, setHost] = useState<CleanerHost>();
  const [history, setHistory] = useState<CleanerTask[]>([]);
  const [task, setTask] = useState<CleanerTask>();
  const [mode, setMode] = useState<CleanerMode>('analysis');
  const [root, setRoot] = useState('');
  const [minimum, setMinimum] = useState(100);
  const [parent, setParent] = useState('');
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState('-size');
  const [listing, setListing] = useState<CleanerListing>(empty);
  const [selected, setSelected] = useState<Record<string, number>>({});
  const [preview, setPreview] = useState<CleanerPreview>();
  const [previewPage, setPreviewPage] = useState(1);
  const [previewRows, setPreviewRows] = useState<CleanerListing>(empty);
  const [directories, setDirectories] = useState<CleanerDirectories>();
  const [error, setError] = useState('');
  const [dialogError, setDialogError] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [rowsLoading, setRowsLoading] = useState(false);
  const [revision, setRevision] = useState(0);
  const [rowRevision, setRowRevision] = useState(0);
  const active = cleanerActive(task);
  const taskId = task?.id;

  useEffect(() => { client.resetScanKey(); }, [client, mode, root, minimum]);

  const chooseTask = useCallback((next?: CleanerTask) => {
    setTask(next); setPage(1); setParent(next?.parameters.root || ''); setSelected({}); setPreview(undefined); setListing(empty);
    setRowRevision(value => value + 1);
    if (next) { setMode(next.parameters.mode); setRoot(next.parameters.root); setMinimum(next.parameters.minimum_bytes / 1024 ** 2); }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError(''); setHost(undefined); setHistory([]); chooseTask(undefined);
    Promise.all([client.host(controller.signal), client.tasks(controller.signal)]).then(([value, tasks]) => {
      if (controller.signal.aborted) return;
      setHost(value); setHistory(tasks.results);
      if (tasks.results[0]) chooseTask(tasks.results[0]);
      else setRoot(value.volumes[0]?.path || '');
    }).catch(e => { if (!controller.signal.aborted) setError(driveError(e)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [client, revision, chooseTask]);

  useEffect(() => {
    if (!taskId || !active) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const [next, freshHost] = await Promise.all([client.task(taskId, controller.signal), client.host(controller.signal)]);
        if (controller.signal.aborted) return;
        setTask(next); setRowRevision(n => n + 1);
        setHost(freshHost);
      } catch (e) { if (!controller.signal.aborted) setError(driveError(e)); }
      if (!controller.signal.aborted) timer = setTimeout(() => void poll(), 2000);
    };
    timer = setTimeout(() => void poll(), 2000);
    return () => { controller.abort(); clearTimeout(timer); };
  }, [client, taskId, active]);

  useEffect(() => {
    if (!taskId) return;
    const controller = new AbortController();
    setRowsLoading(true);
    client.entries(taskId, { page, sort, parent }, controller.signal).then(value => {
      if (!controller.signal.aborted) setListing(value);
    }).catch(e => { if (!controller.signal.aborted) setError(driveError(e)); })
      .finally(() => { if (!controller.signal.aborted) setRowsLoading(false); });
    return () => controller.abort();
  }, [client, taskId, page, sort, parent, rowRevision]);

  useEffect(() => {
    if (!preview) return;
    const controller = new AbortController();
    setPreviewRows(empty);
    client.previewEntries(preview.id, previewPage, controller.signal).then(value => {
      if (!controller.signal.aborted) setPreviewRows(value);
    }).catch(e => { if (!controller.signal.aborted) setDialogError(driveError(e)); });
    return () => controller.abort();
  }, [client, preview, previewPage]);

  async function run(action: () => Promise<void>, dialog = false) {
    setBusy(true); setError(''); setDialogError('');
    try { await action(); } catch (e) { (dialog ? setDialogError : setError)(driveError(e)); } finally { setBusy(false); }
  }
  function adopt(next: CleanerTask) {
    chooseTask(next); setHistory(items => [next, ...items.filter(item => item.id !== next.id)].slice(0, 50));
  }
  function switchMode(next: CleanerMode) {
    const previous = history.find(item => item.parameters.mode === next);
    chooseTask(previous); setMode(next); setError('');
    if (!previous) setRoot(next === 'cache' ? host?.cache_roots[0] || '' : host?.volumes[0]?.path || '');
  }
  const count = Object.keys(selected).length;
  const bytes = Object.values(selected).reduce((sum, size) => sum + size, 0);
  const canSelect = task?.kind === 'scan' && task.state === 'completed' && task.parameters.mode !== 'analysis';

  return <section className="disk-cleaner-page app-scroll-page">
    <div className="disk-cleaner-content">
      {showHeader && <header className="disk-cleaner-header"><div><Link to="/apps" aria-label="返回应用中心"><ArrowLeft size={18} aria-hidden="true" /> 应用中心</Link><h1><HardDrive aria-hidden="true" /> 磁盘清理大师</h1><p>看清空间去向，确认后再清理。</p></div><Button icon={<RefreshCw size={16} aria-hidden="true" />} onClick={() => setRevision(n => n + 1)} disabled={busy}>刷新</Button></header>}
      {error && <Alert type="error" showIcon message={error} action={<Button onClick={() => setRevision(n => n + 1)}>重试加载</Button>} />}
      {loading ? <div className="disk-cleaner-empty"><Spin tip="读取主机信息"><div /></Spin></div> : host && <>
        <div className="disk-cleaner-host"><strong>{host.name}</strong><span>操作对象：后端主机 · 仅平台管理员</span><Tag color={host.worker_online ? 'green' : 'default'}>{host.worker_online ? '清理服务在线' : '清理服务未连接'}</Tag></div>
        {!host.supported ? <Alert type="info" message="首版仅支持 Windows 后端主机。" /> : <>
          {!host.worker_online && <Alert type="warning" showIcon message="清理服务未连接，新任务将排队等待。" description="请在后端主机启动磁盘清理 worker；桌面版会随应用启动。" />}
          <div className="disk-cleaner-volumes">{host.volumes.map(volume => <article className="disk-cleaner-panel" key={volume.path}><div className="disk-cleaner-volume-title"><HardDrive size={20} aria-hidden="true" /><strong>{volume.path}</strong><Button onClick={() => { switchMode('analysis'); setRoot(volume.path); }}>选择磁盘</Button></div><p>可用 <strong>{formatBytes(volume.free)}</strong> / {formatBytes(volume.total)}</p><Progress percent={volume.total ? Math.round(volume.used / volume.total * 100) : 0} aria-label={`${volume.path} 已用比例`} /><small>已用 {formatBytes(volume.used)}</small></article>)}</div>
          <Tabs activeKey={mode} onChange={key => switchMode(key as CleanerMode)} items={Object.entries(modes).map(([key, label]) => ({ key, label }))} />
          <section className="disk-cleaner-panel" aria-label="扫描设置">
            <div className="disk-cleaner-filters"><div className="disk-cleaner-field"><label htmlFor="cleaner-root">{mode === 'cache' ? '预设临时目录' : '扫描目录（后端主机路径）'}</label>{mode === 'cache' ? <Select id="cleaner-root" value={root || undefined} onChange={setRoot} options={host.cache_roots.map(path => ({ value: path, label: path }))} placeholder="无可用临时目录" /> : <div className="disk-cleaner-path-input"><Input id="cleaner-root" value={root} onChange={event => setRoot(event.target.value)} placeholder="例如 D:\素材\待整理" /><Button onClick={() => void run(async () => setDirectories(await client.directories(root)))} disabled={!root || busy}>浏览</Button></div>}</div>
              {mode === 'large' && <div className="disk-cleaner-field"><label htmlFor="cleaner-minimum">最小文件（MiB）</label><InputNumber id="cleaner-minimum" min={1} max={1048576} value={minimum} onChange={value => setMinimum(value || 100)} /></div>}
              <Button type="primary" icon={<Search size={16} aria-hidden="true" />} loading={busy && !preview} disabled={!root || active} onClick={() => void run(async () => adopt(await client.scan({ mode, root, minimum_bytes: Math.round(minimum * 1024 ** 2) })))}>开始扫描</Button>
            </div><p className="disk-cleaner-note">{mode === 'analysis' ? '整盘扫描仅用于分析。系统目录和应用存储受保护，统计仅包含可访问的扫描范围。' : mode === 'cache' ? '仅列出超过 7 天未修改的临时文件；被占用、受保护或已变化的文件将跳过。' : '请选择非盘符根目录。大文件不一定是无用文件，请逐项确认用途。'}</p>
          </section>
          {history.length > 0 && <div className="disk-cleaner-field"><label htmlFor="cleaner-history">最近任务（最多 50 条）</label><Select id="cleaner-history" value={task?.id} placeholder="选择任务" onChange={id => void run(async () => chooseTask(await client.task(id)))} options={history.map(item => ({ value: item.id, label: `${new Date(item.created_at).toLocaleString()} · ${item.kind === 'cleanup' ? '清理' : modes[item.parameters.mode]} · ${item.parameters.root}` }))} /></div>}
          {task ? <section className="disk-cleaner-panel" aria-label="扫描与清理结果">
            <div className="disk-cleaner-task-title"><h2>{task.kind === 'cleanup' ? '清理结果' : '扫描结果'}</h2><Tag>{states[task.state] || task.state}</Tag>{active && <Button onClick={() => void run(async () => setTask(await client.cancel(task.id)))} disabled={busy || task.cancel_requested}>{task.cancel_requested ? '正在停止' : '停止任务'}</Button>}</div>
            <p className="disk-cleaner-path">{task.parameters.root}</p>
            <p role="status">已处理 {task.processed.toLocaleString()} 个文件 · {formatBytes(task.total_bytes)} · 跳过 {task.skipped.toLocaleString()} 项</p>
            {task.message && <Alert type={task.state === 'failed' ? 'error' : 'warning'} showIcon message={task.message} />}
            {task.kind === 'cleanup' && <div className="disk-cleaner-outcome"><p>已删除文件大小 <strong>{formatBytes(task.deleted_bytes)}</strong></p><p>删除 {task.summary.deleted || 0} · 跳过 {task.summary.skipped || 0} · 失败 {task.summary.failed || 0} · 未知 {task.summary.unknown || 0}</p>{Object.entries(task.free_after).filter(([path]) => path in task.free_before).map(([path, free]) => { const delta = free - task.free_before[path]; return <p key={path}>{path} 可用空间变化：{delta < 0 ? '减少 ' : '增加 '}{formatBytes(Math.abs(delta))}</p>; })}<small>空间变化也会受到其他程序、压缩文件和磁盘分配方式影响。</small></div>}
            <div className="disk-cleaner-result-controls">{task.parameters.mode === 'analysis' && <div className="disk-cleaner-path"><Button disabled={parent === task.parameters.root} onClick={() => { setParent(task.parameters.root); setPage(1); }}>返回扫描根目录</Button><span>当前：{parent}</span></div>}<div className="disk-cleaner-field"><label htmlFor="cleaner-sort">结果排序</label><Select id="cleaner-sort" value={sort} onChange={value => { setSort(value); setPage(1); }} disabled={task.kind === 'cleanup'} options={[{ value: '-size', label: '大小从大到小' }, { value: 'size', label: '大小从小到大' }, { value: 'path', label: '路径' }, { value: '-modified_at', label: '最近修改' }]} /></div></div>
            <Spin spinning={rowsLoading}><div className="disk-cleaner-list">{listing.results.length ? listing.results.map(entry => <article className="disk-cleaner-entry" key={entry.id}>
              {canSelect && <Checkbox aria-label={`选择 ${entry.path}`} checked={entry.id in selected} disabled={!entry.cleanable || (count >= 1000 && !(entry.id in selected))} onChange={event => setSelected(items => { const next = { ...items }; if (event.target.checked) next[entry.id] = entry.size; else delete next[entry.id]; return next; })} />}
              <div className="disk-cleaner-entry-info">{entry.kind === 'directory' ? <Button type="link" icon={<FolderOpen size={16} aria-hidden="true" />} onClick={() => { setParent(entry.path); setPage(1); }}>{entry.path}</Button> : <strong>{entry.path}</strong>}{entry.modified_at && <small>修改于 {new Date(entry.modified_at).toLocaleString()}</small>}{entry.reason && <span>{entry.reason}</span>}</div><div className="disk-cleaner-entry-size">{formatBytes(entry.size)}{entry.state && <Tag color={entry.state === 'deleted' ? 'green' : 'default'}>{states[entry.state] || entry.state}</Tag>}</div>
            </article>) : <Empty description={active ? '正在扫描，结果将自动更新' : '此范围内没有结果'} />}</div></Spin>
            <Pagination current={page} pageSize={50} total={listing.count} onChange={setPage} showSizeChanger={false} simple hideOnSinglePage />
          </section> : <div className="disk-cleaner-empty"><Empty description="选择范围并开始扫描，文件不会自动删除。" /></div>}
          {canSelect && <div className="disk-cleaner-selection"><span>已选 {count} 项 · {formatBytes(bytes)}<small>每次最多 1000 项</small></span><Button disabled={!count || busy} onClick={() => setSelected({})}>清空选择</Button><Button type="primary" icon={<Trash2 size={16} aria-hidden="true" />} disabled={!count || busy} onClick={() => void run(async () => { setPreviewPage(1); setPreview(await client.preview(task!.id, Object.keys(selected))); })}>预览清理</Button></div>}
        </>}
      </>}
    </div>
    <Modal open={!!directories} title="选择后端主机目录" onCancel={() => setDirectories(undefined)} onOk={() => { if (directories) setRoot(directories.path); setDirectories(undefined); }} okText="选择此目录" cancelText="取消" className="disk-cleaner-modal">
      {directories && <><p className="disk-cleaner-path">{directories.path}</p><Button disabled={directories.parent === directories.path || busy} onClick={() => void run(async () => setDirectories(await client.directories(directories.parent)))}>上一级</Button>{directories.truncated && <Alert type="warning" message="当前目录条目过多，列表已截断；可直接输入完整路径。" />}<div className="disk-cleaner-directory-list">{directories.directories.map(directory => <Button key={directory.path} type="text" icon={<FolderOpen size={16} aria-hidden="true" />} disabled={busy} onClick={() => void run(async () => setDirectories(await client.directories(directory.path)))}>{directory.name}</Button>)}</div>{error && <Alert type="error" message={error} />}</>}
    </Modal>
    <Modal open={!!preview} title="确认永久删除这些文件？" onCancel={() => { if (!busy) { setPreview(undefined); setDialogError(''); } }} onOk={() => void run(async () => { if (preview) adopt(await client.cleanup(preview.token)); }, true)} okText="永久删除" cancelText="返回检查" confirmLoading={busy} okButtonProps={{ danger: true, disabled: !previewRows.results.length }} cancelButtonProps={{ disabled: busy }} closable={!busy} maskClosable={!busy} className="disk-cleaner-modal">
      {preview && <><Alert type="warning" showIcon message="永久删除无法撤销，不会移入回收站。" /><p>目标主机：<strong>{preview.host_name}</strong></p><p className="disk-cleaner-path">目录：{preview.root}</p><p>共 {preview.count} 个文件 · {formatBytes(preview.total_bytes)}</p><p>确认凭据有效至 {new Date(preview.expires_at).toLocaleTimeString()}</p>{dialogError && <Alert type="error" message={dialogError} />}<div className="disk-cleaner-preview-list">{previewRows.results.map(entry => <div key={entry.id}><span>{entry.path}</span><strong>{formatBytes(entry.size)}</strong></div>)}</div><Pagination current={previewPage} pageSize={50} total={previewRows.count} onChange={setPreviewPage} simple showSizeChanger={false} hideOnSinglePage /><p className="disk-cleaner-note">文件发生变化、被占用或受到保护时将跳过，并显示原因。</p></>}
    </Modal>
  </section>;
}

export default function DiskCleanerPage() {
  const { applicationId } = useParams<{ applicationId: string }>();
  const [params] = useSearchParams();
  const organizationId = useOrganizationStore(state => state.currentOrganizationId);
  const userId = useAuthStore(state => state.user?.id);
  if (!organizationId || !applicationId || !userId) return <Empty description="请登录并选择组织。" />;
  return <DiskCleanerWorkspace key={`${organizationId}:${applicationId}:${userId}`} base={`${tenantApiRoot(organizationId)}/applications/${applicationId}/disk-cleaner`} showHeader={resolveApplicationPresentation(params).showApplicationHeader} />;
}
