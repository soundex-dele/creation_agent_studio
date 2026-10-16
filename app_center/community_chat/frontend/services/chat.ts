import { api } from '@/services/api';
import { API_BASE_URL } from '@/services/apiBaseUrl';
import { createIdempotencyKey } from '@/lib/idempotencyKey';

export interface ChatUser { id: number; username: string; nickname: string; avatar: string }
export interface ChatFile { id: string; name: string; size: number; image: boolean; content_type: string }
export interface ChatMessage {
  id: number; room_id: string; author: ChatUser; text: string; withdrawn: boolean;
  revision: number; request_key: string; created_at: string; attachments: ChatFile[];
}
export interface ChatRoom {
  id: string; kind: 'lobby' | 'direct' | 'group'; name: string; owner_id: number | null;
  version: number; unread: number; last_read_id: number; member_count: number; preview: string; updated_at: string;
}
export interface MessagePage { messages: ChatMessage[]; revision: number; has_more: boolean }
export interface RoomDetail extends ChatRoom { members: ChatUser[] }
export interface Draft {
  key: string; room: string; text: string; files: File[]; uploaded: ChatFile[];
  status: 'sending' | 'failed'; progress: number; error?: string;
  created_at: string; sent?: ChatMessage;
}
export const MAX_BYTES = 100 * 1024 * 1024;
const base = '/community-chat';
const room = (id: string) => `${base}/rooms/${id}`;

export const chat = {
  users: (q = '') => api.get<{ me: ChatUser; users: ChatUser[] }>(`${base}/users/`, { q }),
  rooms: () => api.get<ChatRoom[]>(`${base}/rooms/`),
  detail: (id: string) => api.get<RoomDetail>(`${room(id)}/`),
  create: (kind: 'direct' | 'group', user_ids: number[], name = '') => api.post<ChatRoom>(`${base}/rooms/`, { kind, user_ids, name }),
  manage: (id: string, action: string, extra: { user_id?: number; name?: string } = {}) => api.patch(`${room(id)}/`, { action, ...extra }),
  messages: (id: string, params: { before?: number; after_revision?: number } = {}) => api.get<MessagePage>(`${room(id)}/messages/`, params),
  read: (id: string, message_id: number) => api.post(`${room(id)}/read/`, { message_id }),
  withdraw: (id: string, messageId: number) => api.post<ChatMessage>(`${room(id)}/messages/${messageId}/withdraw/`),
  access: async (id: string, preview = false) => {
    const result = await api.post<{ url: string }>(`${base}/attachments/${id}/access/`, { preview });
    return new URL(result.url, new URL(API_BASE_URL, window.location.href).origin).href;
  },
};

export function createDraft(roomId: string, text: string, files: File[]): Draft {
  if (!text.trim() && !files.length) throw new Error('请填写消息或选择附件。');
  if (text.length > 10000) throw new Error('消息不能超过 10000 字。');
  if (files.length > 9 || files.some(f => f.size === 0 || f.size > MAX_BYTES) || files.reduce((n, f) => n + f.size, 0) > MAX_BYTES) {
    throw new Error('最多 9 个非空附件，单文件及总大小均不超过 100MB。');
  }
  return { key: createIdempotencyKey('community'), room: roomId, text, files: [...files], uploaded: [], status: 'sending', progress: 0, created_at: new Date().toISOString() };
}

export async function sendDraft(draft: Draft, progress: (percent: number) => void): Promise<ChatMessage> {
  // Persist successful uploads on the draft: retries never upload them again.
  for (let i = draft.uploaded.length; i < draft.files.length; i += 1) {
    const body = new FormData();
    body.append('file', draft.files[i]);
    const file = await api.post<ChatFile>(`${room(draft.room)}/uploads/`, body, {
      timeout: 0,
      onUploadProgress: event => progress(Math.round(((i + (event.total ? event.loaded / event.total : 0)) / draft.files.length) * 95)),
    });
    draft.uploaded.push(file);
  }
  return api.post<ChatMessage>(`${room(draft.room)}/messages/`, {
    text: draft.text, attachments: draft.uploaded.map(f => f.id), request_key: draft.key,
  });
}

export function mergeMessages(current: ChatMessage[], incoming: ChatMessage[]): ChatMessage[] {
  const items = new Map(current.map(item => [item.id, item]));
  for (const item of incoming) {
    const old = items.get(item.id);
    if (!old || item.revision >= old.revision) items.set(item.id, item);
  }
  return [...items.values()].sort((a, b) => a.id - b.id);
}

export function mergeMessageChanges(current: ChatMessage[], incoming: ChatMessage[]): ChatMessage[] {
  // A withdrawal outside the loaded history must not move the pagination boundary.
  const oldest = current[0]?.id || 0;
  return mergeMessages(current, incoming.filter(item => !item.withdrawn || item.id >= oldest));
}

export function errorText(error: unknown): string {
  const value = error as { response?: { data?: { detail?: string; non_field_errors?: string[] } }; message?: string };
  return value.response?.data?.detail || value.response?.data?.non_field_errors?.join('，') || value.message || '操作失败，请重试。';
}

export function isDenied(error: unknown): boolean {
  return [403, 404].includes((error as { response?: { status: number } }).response?.status || 0);
}

export function formatSize(bytes: number): string {
  return bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

/** One notification socket for the page; HTTP remains the durable source of truth. */
export function connectChat(onChange: () => void, onStatus: (status: string) => void) {
  let stopped = false;
  let socket: WebSocket | undefined;
  let retry: ReturnType<typeof setTimeout> | undefined;
  let ready = false;
  let lastFrame = Date.now();
  let attempts = 0;
  let lastSync = 0;
  const seen = new Set<string>();
  const refresh = () => { lastSync = Date.now(); onChange(); };
  const open = async () => {
    try {
      const { ticket } = await api.post<{ ticket: string }>(`${base}/ticket/`);
      if (stopped) return;
      const url = new URL('/ws/community-chat/', new URL(API_BASE_URL, window.location.href));
      url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
      socket = new WebSocket(url);
      let handshake: ReturnType<typeof setTimeout> | undefined = setTimeout(() => socket?.close(), 7000);
      socket.onopen = () => socket?.send(JSON.stringify({ ticket }));
      socket.onmessage = event => {
        lastFrame = Date.now();
        try {
          const data = JSON.parse(event.data);
          if (data.type === 'ready') {
            clearTimeout(handshake); handshake = undefined;
            ready = true; attempts = 0; seen.clear();
            onStatus('实时连接'); refresh();
          } else if (data.type === 'changed') {
            if (!seen.has(data.event_id)) {
              seen.add(data.event_id);
              if (seen.size > 256) seen.delete(seen.values().next().value!);
              refresh();
            }
          }
        } catch { /* Ignore malformed notifications; periodic reconciliation survives. */ }
      };
      socket.onclose = () => { clearTimeout(handshake); reconnect(); };
      socket.onerror = () => socket?.close();
    } catch { reconnect(); }
  };
  const reconnect = () => {
    if (stopped) return;
    ready = false; onStatus('重连中 · 每 5 秒同步');
    clearTimeout(retry);
    retry = setTimeout(() => void open(), Math.min(30000, 1000 * 2 ** Math.min(attempts++, 5)));
  };
  const timer = setInterval(() => {
    if (ready && Date.now() - lastFrame > 60000) { ready = false; socket?.close(); }
    if (Date.now() - lastSync >= (ready ? 30000 : 5000)) refresh();
  }, 1000);
  const resume = () => { if (document.visibilityState === 'visible') refresh(); };
  document.addEventListener('visibilitychange', resume);
  onStatus('连接中');
  void open();
  return () => {
    stopped = true; clearTimeout(retry); clearInterval(timer);
    document.removeEventListener('visibilitychange', resume);
    socket?.close();
  };
}
