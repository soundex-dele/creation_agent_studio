import { driveError, type DriveClient, type DriveUpload } from './myDrive';

export type TransferStatus = 'queued' | 'checking' | 'uploading' | 'paused' | 'error' | 'completed' | 'cancelling' | 'cancelled';
export interface DriveTransfer { upload: DriveUpload; file?: File; status: TransferStatus; error: string; speed: number }

export async function sha256(blob: Blob): Promise<string> {
  if (!globalThis.crypto?.subtle) throw new Error('文件校验需要安全连接，请通过 HTTPS 或 localhost 打开应用。');
  return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', await blob.arrayBuffer())), (b) => b.toString(16).padStart(2, '0')).join('');
}

/** Files stay in memory only. The server persists sessions and confirmed chunks. */
export class DriveTransfers {
  tasks: DriveTransfer[] = [];
  private active = new Map<string, AbortController>();
  private disposed = false;
  constructor(private client: DriveClient, private changed: (tasks: DriveTransfer[]) => void, private completed: () => void) {}

  private emit() { if (!this.disposed) this.changed(this.tasks.map((task) => ({ ...task, upload: { ...task.upload } }))); }
  async load() {
    let page = 1;
    do {
      const response = await this.client.uploads(page++);
      if (this.disposed) return;
      for (const upload of response.results) {
        const existing = this.tasks.find((task) => task.upload.id === upload.id);
        if (!existing) this.tasks.push({ upload, status: upload.state === 'uploading' ? 'paused' : upload.state, speed: 0, error: '' });
        else if (!this.active.has(upload.id) && upload.state !== 'uploading') {
          existing.upload = upload; existing.status = upload.state; existing.file = undefined;
        }
      }
      this.emit();
      if (!response.next) break;
    } while (!this.disposed);
  }
  async add(file: File, parent: string | null) {
    const upload = await this.client.createUpload(file, parent);
    if (this.disposed) return;
    this.tasks.unshift({ upload, file, status: 'queued', speed: 0, error: '' });
    this.emit(); this.pump();
  }
  resume(id: string, file?: File) {
    const task = this.tasks.find((value) => value.upload.id === id);
    if (!task || ['completed', 'cancelled', 'cancelling'].includes(task.status)) return;
    const source = file || task.file;
    if (!source) throw new Error('请重新选择原文件以继续上传。');
    if (source.name !== task.upload.name || source.size !== task.upload.size || source.lastModified !== task.upload.last_modified) throw new Error('请选择名称、大小和修改时间一致的原文件。');
    task.file = source; task.status = 'queued'; task.error = '';
    this.emit(); this.pump();
  }
  pause(id: string) {
    const task = this.tasks.find((value) => value.upload.id === id);
    if (!task || !['queued', 'checking', 'uploading'].includes(task.status)) return;
    task.status = 'paused'; task.speed = 0; this.active.get(id)?.abort(); this.emit();
  }
  async cancel(id: string) {
    const task = this.tasks.find((value) => value.upload.id === id);
    if (!task) return;
    task.status = 'cancelling'; this.active.get(id)?.abort(); this.emit();
    try { task.upload = await this.client.cancel(id); task.file = undefined; task.error = ''; }
    catch (error) { task.status = 'error'; task.error = driveError(error); }
    this.emit(); this.completed();
  }
  dispose() { this.disposed = true; this.active.forEach((controller) => controller.abort()); }
  private pump() {
    if (this.disposed) return;
    for (const task of this.tasks) {
      if (this.active.size >= 3) break;
      if (task.status !== 'queued' || this.active.has(task.upload.id)) continue;
      const controller = new AbortController(); this.active.set(task.upload.id, controller);
      void this.run(task, controller.signal).finally(() => { this.active.delete(task.upload.id); this.emit(); this.pump(); });
    }
  }
  private async run(task: DriveTransfer, signal: AbortSignal) {
    try {
      task.status = 'checking'; this.emit();
      let upload = await this.client.upload(task.upload.id, signal);
      if (upload.state === 'completed') { task.upload = upload; task.status = 'completed'; task.file = undefined; this.completed(); return; }
      if (upload.state !== 'uploading') throw new Error('上传已取消或过期，请重新上传。');
      const file = task.file!;
      for (const chunk of upload.chunks || []) {
        signal.throwIfAborted();
        if (await sha256(file.slice(chunk.offset, chunk.offset + chunk.size)) !== chunk.sha256) throw new Error('原文件内容已变化，不能续传。请取消此任务并重新上传。');
      }
      const started = Date.now(), initial = upload.offset;
      signal.throwIfAborted();
      task.status = 'uploading'; task.upload = upload; this.emit();
      while (upload.offset < upload.size) {
        signal.throwIfAborted();
        const blob = file.slice(upload.offset, Math.min(upload.offset + upload.chunk_size, upload.size));
        const hash = await sha256(blob);
        let attempts = 0;
        while (attempts < 3) {
          signal.throwIfAborted();
          try { upload = await this.client.chunk(upload.id, upload.offset, hash, blob, signal); break; }
          catch (error) {
            const code = (error as { response?: { status?: number } })?.response?.status;
            if (signal.aborted || ++attempts >= 3 || (code && code < 500)) throw error;
            await new Promise((resolve) => setTimeout(resolve, attempts * 500));
          }
        }
        task.upload = upload; task.speed = (upload.offset - initial) / Math.max(1, (Date.now() - started) / 1000); this.emit();
      }
      signal.throwIfAborted();
      task.upload = await this.client.complete(upload.id, signal); task.status = 'completed'; task.file = undefined; task.speed = 0;
      this.completed();
    } catch (error) {
      if (!signal.aborted) { task.status = 'error'; task.error = driveError(error); task.speed = 0; }
    }
  }
}
