import { api } from './api';
import { API_BASE_URL } from './apiBaseUrl';
import { getAccessToken, refreshAccessToken } from './authSession';
import { remotePath } from './chatConnection';

export interface TerminalSession {
  id: string;
  shell: string;
  created_at: string;
  exited: boolean;
  exit_code: number | null;
}
export interface TerminalCapability { supported: boolean; enabled: boolean; shell: string; max_sessions: number }
export type TerminalEvent = { type: 'ready' } | { type: 'output'; sequence: number; data: string }
  | { type: 'truncated'; sequence: number } | { type: 'exit'; exit_code: number | null };
export const terminalRoot = '/remote-access/terminals/';
// getRandomValues also works for the supported HTTP LAN deployments.
export const terminalKey = () => Array.from(crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, '0')).join('');
export const terminalPath = (deviceId: string, suffix = '') => remotePath({ deviceId }, terminalRoot + suffix);

export function terminalError(error: unknown): string {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof detail === 'string' ? detail : error instanceof Error ? error.message : '终端连接失败。';
}

/** The caller owns the key. Identical input text in different batches is never deduplicated. */
export async function terminalPost<T>(deviceId: string, suffix: string, body: unknown, key: string, signal?: AbortSignal): Promise<T> {
  for (let attempt = 0; ; attempt++) {
    try {
      return await api.post<T>(terminalPath(deviceId, suffix), body, {
        signal, timeout: 25000, headers: { 'Idempotency-Key': key },
      });
    } catch (error) {
      const status = (error as { response?: { status?: number } }).response?.status;
      if (signal?.aborted || attempt >= 2 || (status && ![502, 503, 504].includes(status))) throw error;
      await new Promise(resolve => setTimeout(resolve, 300 * (attempt + 1)));
      if (signal?.aborted) throw error;
    }
  }
}

export class TerminalFrameBuffer {
  private buffer = '';
  push(text: string): TerminalEvent[] {
    this.buffer += text;
    const result: TerminalEvent[] = [];
    let boundary: number;
    while ((boundary = this.buffer.indexOf('\n\n')) >= 0) {
      const frame = this.buffer.slice(0, boundary);
      this.buffer = this.buffer.slice(boundary + 2);
      const data = frame.split('\n').filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n');
      if (data) result.push(JSON.parse(data) as TerminalEvent);
    }
    if (this.buffer.length > 256 * 1024) throw new Error('终端输出格式无效。');
    return result;
  }
}

export async function terminalStream(deviceId: string, sessionId: string, after: number, signal: AbortSignal,
  onEvent: (event: TerminalEvent) => Promise<void>): Promise<void> {
  const send = () => fetch(`${API_BASE_URL}${terminalPath(deviceId, `${sessionId}/stream/`)}?after=${after}`, {
    signal, credentials: 'include', headers: { Accept: 'text/event-stream',
      ...(getAccessToken() ? { Authorization: `Bearer ${getAccessToken()}` } : {}) },
  });
  let response = await send();
  if (response.status === 401) { await refreshAccessToken(); response = await send(); }
  if (!response.ok || !response.body) {
    const problem = await response.json().catch(() => ({}));
    throw Object.assign(new Error(problem.detail || '终端连接中断。'), { status: response.status });
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const frames = new TerminalFrameBuffer();
  try {
    while (!signal.aborted) {
      const { done, value } = await reader.read();
      if (done) return;
      for (const event of frames.push(decoder.decode(value, { stream: true }))) await onEvent(event);
    }
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}

/** One in-flight input batch, bounded pending keystrokes, and no offline queue. */
export class TerminalInput {
  private client = terminalKey();
  private sequence = 0;
  private pending = '';
  private sending = false;
  private timer?: ReturnType<typeof setTimeout>;
  private controller = new AbortController();
  private enabled = false;
  private failed = false;
  get paused() { return this.failed; }
  constructor(private device: string, private session: string, private onError: (error: unknown) => void) {}
  setOnline(online: boolean) {
    this.enabled = online && !this.failed;
    if (!online) this.pending = '';
  }
  write(data: string) {
    if (!this.enabled) return;
    if (new TextEncoder().encode(this.pending + data).length > 16384) {
      this.onError(new Error('输入过长或连接繁忙，请分段粘贴。'));
      return;
    }
    this.pending += data;
    if (!this.timer && !this.sending) this.timer = setTimeout(() => { this.timer = undefined; void this.flush(); }, 20);
  }
  private async flush() {
    if (!this.enabled || this.sending || !this.pending) return;
    const data = this.pending;
    this.pending = '';
    this.sending = true;
    try {
      await terminalPost(this.device, `${this.session}/input/`, {
        client_id: this.client, sequence: ++this.sequence, data,
      }, terminalKey(), this.controller.signal);
    } catch (error) {
      if (!this.controller.signal.aborted) {
        this.failed = true;
        this.setOnline(false);
        this.onError(new Error(`${terminalError(error)} 输入已暂停，请检查执行结果后重新连接。`));
      }
    } finally {
      this.sending = false;
      if (!this.controller.signal.aborted) void this.flush();
    }
  }
  dispose() { this.setOnline(false); clearTimeout(this.timer); this.controller.abort(); }
}
