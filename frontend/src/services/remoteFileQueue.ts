import { encodeFileChunk, fileGet, fileKey, filePost, fileRequest, FileRequestError, launchDownload, MAX_FILE_SIZE,
  type FileTransfer } from './remoteFiles';

export interface TransferTask {
  key: string; direction: 'upload' | 'download'; name: string; path: string; size: number; offset: number;
  status: 'queued' | 'running' | 'reconnecting' | 'completed' | 'failed' | 'cancelling' | 'cancelled';
  detail: string; remote?: FileTransfer; file?: File; cancel?: boolean; frame?: HTMLIFrameElement; started?: boolean; recovered?: boolean;
}
const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

/** Page-independent, bounded workers; File.slice reads at most one chunk per upload. */
export class RemoteFileQueue {
  private tasks: TransferTask[] = [];
  private listeners = new Set<() => void>();
  private active = new Set<string>();
  private controller = new AbortController();
  private snapshot: TransferTask[] = [];
  constructor(readonly device: string) {}
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; };
  getSnapshot = () => this.snapshot;
  async discover() {
    const result = await fileGet<{ transfers: FileTransfer[] }>(this.device, 'transfers/', this.controller.signal);
    if (this.controller.signal.aborted || this.tasks.some(task => this.active.has(task.key) && !task.remote)) return;
    for (const item of result.transfers) if (!this.tasks.some(task => task.remote?.id === item.id)) {
      this.tasks.push({ ...item, key: fileKey(), status: 'failed', remote: item, started: true, recovered: true,
        detail: '电脑端有未完成任务。可在原网页继续，或取消后重新选择文件；刷新网页不会自动恢复上传。' });
    }
    this.emit();
  }
  private emit() { this.snapshot = this.tasks.map(task => ({ ...task })); this.listeners.forEach(listener => listener()); }
  add(direction: 'upload' | 'download', path: string, name: string, size: number, file?: File) {
    if (size > MAX_FILE_SIZE) throw new Error('单文件不能超过 2 GiB。');
    if (this.tasks.length >= 200) throw new Error('任务列表已满，请先清除已结束任务。');
    this.tasks.push({ key: fileKey(), direction, path, name, size, offset: 0, status: 'queued', detail: '', file });
    this.emit(); this.pump();
  }
  clearFinished() {
    this.tasks.filter(t => ['completed', 'cancelled'].includes(t.status)).forEach(t => t.frame?.remove());
    this.tasks = this.tasks.filter(t => !['completed', 'cancelled'].includes(t.status)); this.emit();
  }
  cancel(key: string) {
    const task = this.tasks.find(t => t.key === key);
    if (!task || task.status === 'cancelled') return;
    task.cancel = true; task.frame?.remove();
    task.status = task.started || this.active.has(key) ? 'cancelling' : 'cancelled';
    if (task.status === 'cancelled') task.file = undefined;
    if (!this.active.has(key) && task.status === 'cancelling') void this.run(task);
    this.emit();
  }
  retry(key: string) {
    const task = this.tasks.find(t => t.key === key);
    if (!task || task.status !== 'failed') return;
    task.status = 'queued'; task.detail = ''; this.emit(); this.pump();
  }
  dispose() { this.controller.abort(); this.tasks.forEach(t => t.frame?.remove()); this.tasks = []; this.emit(); }
  private pump() {
    if (this.controller.signal.aborted) return;
    for (const direction of ['upload', 'download']) {
      let count = this.tasks.filter(t => t.direction === direction && this.active.has(t.key)).length;
      for (const task of this.tasks) if (count < 2 && task.direction === direction && task.status === 'queued' && !this.active.has(task.key)) {
        count++; void this.run(task);
      }
    }
  }
  private async connected<T>(task: TransferTask, action: () => Promise<T>): Promise<T> {
    const deadline = Date.now() + 60000;
    for (;;) {
      if (this.controller.signal.aborted) throw new Error('登录会话已结束。');
      try { const result = await action(); task.status = task.cancel ? 'cancelling' : 'running'; task.detail = ''; this.emit(); return result; }
      catch (error) {
        const transient = !(error instanceof FileRequestError) || [429, 502, 503, 504].includes(error.status);
        if (!transient || Date.now() >= deadline || this.controller.signal.aborted) throw error;
        task.status = task.cancel ? 'cancelling' : 'reconnecting'; task.detail = '正在等待电脑连接或传输名额…'; this.emit();
        await sleep(1500);
      }
    }
  }
  private async run(task: TransferTask) {
    this.active.add(task.key); task.started = true; task.status = task.cancel ? 'cancelling' : 'running'; this.emit();
    const signal = this.controller.signal;
    const post = <T,>(suffix: string, body: unknown, key = fileKey()) => this.connected(task, () => filePost<T>(this.device, suffix, body, key, signal));
    try {
      if (!task.remote) {
        if (task.direction === 'upload') task.remote = await post<FileTransfer>('uploads/', { path: task.path, name: task.name, size: task.size }, task.key);
        else {
          const result = await this.connected(task, () => fileRequest<FileTransfer & { download_url: string }>(
            `/remote/devices/${this.device}/downloads/`, { path: task.path }, task.key, signal));
          task.remote = result;
          if (!task.cancel) task.frame = launchDownload(result.download_url);
        }
      } else if (!task.cancel) {
        task.remote = await this.connected(task, () => fileGet<FileTransfer>(this.device, `transfers/${task.remote!.id}/`, signal));
        if (task.direction === 'download' && task.remote.state !== 'completed') {
          const result = await this.connected(task, () => fileRequest<FileTransfer & { download_url: string }>(
            `/remote/devices/${this.device}/downloads/`, { path: task.path }, task.key, signal));
          task.frame?.remove(); task.frame = launchDownload(result.download_url);
        }
      }
      task.size = task.remote.size;
      while (!task.cancel && task.remote.state !== 'completed') {
        if (['failed', 'cancelled'].includes(task.remote.state)) throw new Error(task.remote.detail || '电脑端任务已失效，请重新选择文件。');
        task.offset = task.remote.offset; this.emit();
        if (task.direction === 'download') {
          await sleep(1000);
          task.remote = await this.connected(task, () => fileGet<FileTransfer>(this.device, `transfers/${task.remote!.id}/`, signal));
        } else if (task.offset < task.size) {
          const body = await encodeFileChunk(task.file!, task.offset);
          task.remote = await post<FileTransfer>(`uploads/${task.remote.id}/chunk/`, body);
        } else task.remote = await post<FileTransfer>(`uploads/${task.remote.id}/complete/`, {});
      }
      if (task.cancel) {
        try { await post(`transfers/${task.remote.id}/cancel/`, {}); }
        catch (error) { if (!(error instanceof FileRequestError) || ![404, 410].includes(error.status)) throw error; }
        task.status = 'cancelled';
      } else { task.status = 'completed'; task.name = task.remote.name; task.offset = task.remote.offset; }
      task.file = undefined;
    } catch (error) {
      if (task.cancel && error instanceof FileRequestError && [404, 410].includes(error.status)) {
        task.status = 'cancelled'; task.detail = ''; task.file = undefined;
      } else {
        task.status = 'failed'; task.detail = error instanceof Error ? error.message : '传输失败，请重试。';
      }
    } finally {
      this.active.delete(task.key); this.emit(); this.pump();
    }
  }
}
