import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react';
import { Alert, Breadcrumb, Button, Empty, Input, List, Progress, Select, Space, Tag } from 'antd';
import { DownloadOutlined, FolderOutlined, ReloadOutlined, UploadOutlined } from '@ant-design/icons';
import { remoteFileQueue } from '@/stores/remoteFileQueues';
import { fileGet, filePost, fileRequest, type DirectoryPage, type FileCapability } from '@/services/remoteFiles';
import { remotePath } from '@/services/chatConnection';
import './RemoteFilesPage.css';

export const fileSize = (size: number) => size < 1024 ? `${size} B` : size < 1024 ** 2 ? `${(size / 1024).toFixed(1)} KiB`
  : size < 1024 ** 3 ? `${(size / 1024 ** 2).toFixed(1)} MiB` : `${(size / 1024 ** 3).toFixed(2)} GiB`;
const labels = { queued: '排队中', running: '传输中', reconnecting: '重连中', completed: '完成', failed: '失败', cancelling: '取消中', cancelled: '已取消' };

export default function RemoteFilesPage({ deviceId, online }: { deviceId: string; online: boolean }) {
  const queue = useMemo(() => remoteFileQueue(deviceId), [deviceId]);
  const tasks = useSyncExternalStore(queue.subscribe, queue.getSnapshot);
  const [capability, setCapability] = useState<FileCapability | null | undefined>();
  const [roots, setRoots] = useState<{ name: string; path: string }[]>([]);
  const [page, setPage] = useState<DirectoryPage>();
  const [path, setPath] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const input = useRef<HTMLInputElement>(null);
  const generation = useRef(0);
  const mounted = useRef(true);
  const enabled = online && capability?.supported && capability.enabled;
  const completed = tasks.filter(t => t.direction === 'upload' && t.status === 'completed').map(t => t.key).join(',');
  const currentPath = useRef('');
  const previousCompleted = useRef(completed);
  const showError = (failure: unknown) => setError(failure instanceof Error ? failure.message : '无法读取电脑文件。');
  const load = async (target: string, cursor = '') => {
    const request = ++generation.current;
    setBusy(true); setError('');
    try {
      const result = await filePost<DirectoryPage>(deviceId, 'list/', { path: target, cursor });
      if (!mounted.current || request !== generation.current) return;
      setPage(previous => cursor && previous?.path === result.path ? { ...result, entries: [...previous.entries, ...result.entries] } : result);
      setPath(result.path); currentPath.current = result.path;
    } catch (failure) { if (mounted.current && request === generation.current) showError(failure); }
    finally { if (mounted.current && request === generation.current) setBusy(false); }
  };
  const loadRef = useRef(load); loadRef.current = load;
  useEffect(() => { const requests = generation; mounted.current = true; return () => { mounted.current = false; requests.current++; }; }, []);
  useEffect(() => {
    if (!online) return;
    let disposed = false; let checking = false;
    const check = async () => {
      if (checking) return;
      checking = true;
      try {
        const context = await fileRequest<{ files?: FileCapability }>(remotePath({ deviceId }, '/remote-access/context/'));
        if (disposed) return;
        setCapability(context.files || null);
        if (context.files?.supported && context.files.enabled && !currentPath.current) {
          await queue.discover();
          const result = await fileGet<{ roots: { name: string; path: string }[]; home: string }>(deviceId, 'roots/');
          if (!disposed) { setRoots(result.roots); await loadRef.current(result.home); }
        }
      } catch (failure) { if (!disposed) { setCapability(undefined); showError(failure); } }
      finally { checking = false; }
    };
    void check(); const timer = setInterval(() => void check(), 5000);
    return () => { disposed = true; clearInterval(timer); };
  }, [deviceId, online, queue]);
  useEffect(() => {
    if (completed !== previousCompleted.current && enabled && currentPath.current) void loadRef.current(currentPath.current);
    previousCompleted.current = completed;
  }, [completed, enabled]);
  const breadcrumbs = useMemo(() => {
    const full = page?.path || '';
    const separator = full.includes('\\') ? '\\' : '/';
    const segments = full.split(separator).filter(Boolean);
    const prefix = full.startsWith('\\\\') ? '\\\\' : full.startsWith('/') ? '/' : '';
    const items = segments.map((name, index) => ({ name, path: prefix + segments.slice(0, index + 1).join(separator) + separator }));
    return prefix === '/' ? [{ name: '/', path: '/' }, ...items] : items;
  }, [page?.path]);
  return <div className="my-computer-content remote-files">
    <p>使用运行电脑服务的操作系统账号访问文件。单文件最大 2 GiB，同名上传自动改名。</p>
    {capability === null && <Alert type="info" showIcon message="此电脑尚不支持文件传输，请升级电脑端。" />}
    {capability && !capability.enabled && <Alert type="warning" showIcon message="文件传输未开启，请在电脑“设置 → 远程访问”中允许文件传输。" />}
    {!online && <Alert type="warning" message="电脑离线，传输任务会尝试重连。" />}
    {error && <Alert type="error" showIcon message={error} />}
    <Space wrap>
      <Select aria-label="选择磁盘" placeholder="选择磁盘" style={{ minWidth: 150 }} disabled={!enabled || busy}
        options={roots.map(root => ({ label: root.name, value: root.path }))} onChange={value => void load(value)} />
      <Button disabled={!enabled || !page?.parent || busy} onClick={() => void load(page!.parent)}>上一级</Button>
      <Button icon={<ReloadOutlined />} disabled={!enabled || !page || busy} onClick={() => void load(page!.path)}>刷新</Button>
      <Button icon={<UploadOutlined />} type="primary" disabled={!enabled || !page} onClick={() => input.current?.click()}>上传文件</Button>
      <input ref={input} type="file" multiple hidden aria-label="选择上传文件" onChange={event => {
        for (const file of Array.from(event.target.files || [])) {
          try { queue.add('upload', page!.path, file.name, file.size, file); } catch (failure) { showError(failure); }
        }
        event.target.value = '';
      }} />
    </Space>
    <form className="remote-files-path" onSubmit={event => { event.preventDefault(); if (enabled) void load(path); }}>
      <Input aria-label="电脑目录路径" value={path} onChange={event => setPath(event.target.value)} disabled={!enabled} placeholder="输入电脑上的绝对目录路径" />
      <Button htmlType="submit" disabled={!enabled || !path || busy}>跳转</Button>
    </form>
    <Breadcrumb items={breadcrumbs.map(crumb => ({ title: <Button type="link" disabled={!enabled || busy} onClick={() => void load(crumb.path)}>{crumb.name}</Button> }))} />
    <List loading={busy} dataSource={page?.entries || []} locale={{ emptyText: <Empty description={enabled ? '目录为空' : '连接后可浏览文件'} /> }} renderItem={entry => <List.Item>
      <div className="remote-files-entry">
        {entry.directory ? <Button type="text" icon={<FolderOutlined />} disabled={!enabled || busy} onClick={() => void load(entry.path)}>{entry.name}</Button> : <strong>{entry.name}</strong>}
        <small>{entry.directory ? '文件夹' : fileSize(entry.size || 0)} · {new Date(entry.modified_at * 1000).toLocaleString('zh-CN')}</small>
      </div>
      {!entry.directory && <Button icon={<DownloadOutlined />} disabled={!enabled} aria-label={`下载 ${entry.name}`} onClick={() => {
        try { queue.add('download', entry.path, entry.name, entry.size || 0); } catch (failure) { showError(failure); }
      }}>下载</Button>}
    </List.Item>} />
    {page?.next_cursor && <Button disabled={!enabled || busy} onClick={() => void load(page.path, page.next_cursor)}>加载更多文件</Button>}
    <section aria-label="传输任务">
      <Space wrap><h2>传输任务</h2><Button onClick={() => queue.clearFinished()}>清除已结束任务</Button></Space>
      <p>下载进度表示电脑端已发送给浏览器，是否已保存到本地请查看浏览器下载列表。上传中可切换页签；刷新或关闭网页会中断上传。</p>
      <List dataSource={tasks} locale={{ emptyText: '暂无传输任务' }} renderItem={task => <List.Item className="remote-files-task">
        <div><strong>{task.name}</strong> <Tag>{task.direction === 'upload' ? '上传' : '下载'} · {labels[task.status]}</Tag></div>
        <Progress percent={task.size ? Math.floor(task.offset * 100 / task.size) : task.status === 'completed' ? 100 : 0} status={task.status === 'failed' ? 'exception' : task.status === 'completed' ? 'success' : 'normal'} />
        <small>{task.direction === 'download' ? '已发送给浏览器' : '电脑已接收'} {fileSize(task.offset)} / {fileSize(task.size)}</small>
        {task.detail && <span role="status">{task.detail}</span>}
        <Space>{task.status === 'failed' && !task.recovered && <Button onClick={() => queue.retry(task.key)}>重试</Button>}
          {!['cancelled', 'cancelling'].includes(task.status) && (task.status !== 'completed' || task.direction === 'download') && <Button danger onClick={() => queue.cancel(task.key)}>取消{task.direction === 'download' ? '电脑端下载' : ''}</Button>}</Space>
      </List.Item>} />
    </section>
  </div>;
}
