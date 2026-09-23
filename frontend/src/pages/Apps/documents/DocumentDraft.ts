import type { DocumentBody, OnlineDocument } from '@/services/documents';
import { documentError } from '@/services/documents';

/** Owns debounce, composition and serialized saves independently of React renders. */
export class DocumentDraft {
  document: OnlineDocument;
  body: DocumentBody;
  status: 'saved' | 'dirty' | 'saving' | 'error' | 'conflict' = 'saved';
  error = '';
  composing = false;
  private revision = 0;
  private savedRevision = 0;
  private timer?: ReturnType<typeof setTimeout>;
  private pending?: Promise<OnlineDocument>;
  private listeners = new Set<() => void>();
  private disposed = false;
  constructor(document: OnlineDocument, private persist: (body: DocumentBody, version: number) => Promise<OnlineDocument>) {
    this.document = document;
    this.body = { title: document.title, content: document.content };
  }
  get hasChanges() { return this.revision !== this.savedRevision; }
  subscribe = (listener: () => void) => { this.disposed = false; this.listeners.add(listener); return () => { this.listeners.delete(listener); }; };
  private notify() { if (!this.disposed) this.listeners.forEach((listener) => listener()); }
  update(body: Partial<DocumentBody>) {
    this.body = { ...this.body, ...body };
    this.revision++;
    if (this.status !== 'conflict') { this.status = 'dirty'; this.error = ''; }
    this.notify(); this.schedule();
  }
  private schedule() {
    clearTimeout(this.timer);
    if (!this.composing && !this.disposed && this.status !== 'conflict') {
      this.timer = setTimeout(() => { void this.save().catch(() => undefined); }, 1000);
    }
  }
  composition(active: boolean) {
    this.composing = active;
    clearTimeout(this.timer);
    if (!active && this.hasChanges) this.schedule();
  }
  save(): Promise<OnlineDocument> {
    clearTimeout(this.timer);
    if (this.composing) return Promise.reject(new Error('请完成当前输入后再操作。'));
    if (this.status === 'conflict') return Promise.reject(new Error(this.error));
    if (this.pending) return this.pending;
    this.pending = this.flush().finally(() => { this.pending = undefined; });
    return this.pending;
  }
  private async flush() {
    while (this.hasChanges) {
      if (this.composing) { this.status = 'dirty'; this.notify(); throw new Error('请完成当前输入后再操作。'); }
      const revision = this.revision;
      const body = structuredClone(this.body);
      this.status = 'saving'; this.notify();
      try {
        const saved = await this.persist(body, this.document.version);
        this.document = saved;
        this.savedRevision = revision;
        if (!this.hasChanges) this.body = { title: saved.title, content: saved.content };
      } catch (error) {
        this.status = (error as { response?: { status: number } })?.response?.status === 409 ? 'conflict' : 'error';
        this.error = documentError(error); this.notify();
        throw error;
      }
      if (this.disposed) break;
    }
    this.status = this.hasChanges ? 'dirty' : 'saved'; this.error = ''; this.notify();
    return this.document;
  }
  dispose() { this.disposed = true; clearTimeout(this.timer); this.listeners.clear(); }
}
