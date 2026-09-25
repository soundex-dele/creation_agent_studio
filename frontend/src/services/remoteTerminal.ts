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
  private pendingBytes = 0;
  private encoder = new TextEncoder();
  private decoder = new TextDecoder('utf-8', { ignoreBOM: true });
  private sending = false;
  private timer?: ReturnType<typeof setTimeout>;
  private controller = new AbortController();
  private enabled = false;
  private failed = false;
  get paused() { return this.failed; }
  get writable() { return this.enabled && !this.controller.signal.aborted; }
  constructor(private device: string, private session: string, private onError: (error: unknown) => void) {}
  setOnline(online: boolean) {
    this.enabled = online && !this.failed && !this.controller.signal.aborted;
    if (!online) {
      const discarded = Boolean(this.pending);
      this.pending = '';
      this.pendingBytes = 0;
      clearTimeout(this.timer); this.timer = undefined;
      if (discarded && !this.failed && !this.controller.signal.aborted) {
        this.onError(new Error('连接已断开，尚未发送的输入已取消。请检查终端内容后重新输入。'));
      }
    }
  }
  write(data: string) {
    if (!this.writable || !data) return;
    let addedBytes = this.encoder.encode(data).length;
    const previousCode = this.pending.charCodeAt(this.pending.length - 1);
    const nextCode = data.charCodeAt(0);
    if (previousCode >= 0xd800 && previousCode <= 0xdbff && nextCode >= 0xdc00 && nextCode <= 0xdfff) addedBytes -= 2;
    if (this.pendingBytes + addedBytes > 256 * 1024) {
      this.failed = true;
      this.setOnline(false);
      this.onError(new Error('输入缓冲区已满，输入已暂停。请检查已输入内容后重新连接，并分段粘贴。'));
      return;
    }
    this.pending += data;
    this.pendingBytes += addedBytes;
    if (!this.timer && !this.sending) this.timer = setTimeout(() => { this.timer = undefined; void this.flush(); }, 20);
  }
  private async flush() {
    if (!this.enabled || this.sending || !this.pending) return;
    const encoded = this.encoder.encode(this.pending);
    let boundary = Math.min(encoded.length, 16384);
    while (boundary < encoded.length && (encoded[boundary] & 0xc0) === 0x80) boundary--;
    const data = this.decoder.decode(encoded.subarray(0, boundary));
    this.pending = this.pending.slice(data.length);
    this.pendingBytes -= boundary;
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
  dispose() { this.controller.abort(); this.setOnline(false); }
}
