import { sha256 } from '@noble/hashes/sha256';
import { API_BASE_URL } from './apiBaseUrl';
import { getAccessToken, refreshAccessToken } from './authSession';
import { remotePath } from './chatConnection';
import { terminalKey } from './remoteTerminal';

export const FILE_CHUNK = 256 * 1024;
export const MAX_FILE_SIZE = 2 * 1024 ** 3;
export const fileKey = terminalKey;
export interface FileCapability { supported: boolean; enabled: boolean; max_file_size: number; chunk_size: number }
export interface FileEntry { name: string; path: string; directory: boolean; size: number | null; modified_at: number }
export interface DirectoryPage { path: string; parent: string; entries: FileEntry[]; next_cursor: string }
export interface FileTransfer {
  id: string; direction: 'upload' | 'download'; name: string; size: number; offset: number;
  state: 'ready' | 'transferring' | 'completed' | 'cancelled' | 'failed'; path: string; etag: string; detail: string;
}
export class FileRequestError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

// Quiet transport: reconnecting tasks report their state in the task list, without toast storms.
export async function fileRequest<T>(path: string, body?: unknown, key?: string, signal?: AbortSignal): Promise<T> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (signal?.aborted) abort();
  signal?.addEventListener('abort', abort, { once: true });
  const timeout = setTimeout(abort, 25000);
  const send = () => fetch(`${API_BASE_URL}${path}`, {
    method: body === undefined ? 'GET' : 'POST', credentials: 'include', signal: controller.signal,
    headers: { Accept: 'application/json', ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
      ...(key ? { 'Idempotency-Key': key } : {}), ...(getAccessToken() ? { Authorization: `Bearer ${getAccessToken()}` } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  try {
    let response = await send();
    if (response.status === 401) { await refreshAccessToken(); response = await send(); }
    const value = await response.json();
    if (!response.ok) throw new FileRequestError(response.status, typeof value.detail === 'string' ? value.detail : `文件请求失败（${response.status}）`);
    return value as T;
  } finally { clearTimeout(timeout); signal?.removeEventListener('abort', abort); }
}
export const filePath = (device: string, suffix: string) => remotePath({ deviceId: device }, `/remote-access/files/${suffix}`);
export const fileGet = <T,>(device: string, suffix: string, signal?: AbortSignal) => fileRequest<T>(filePath(device, suffix), undefined, undefined, signal);
export const filePost = <T,>(device: string, suffix: string, body: unknown, key = fileKey(), signal?: AbortSignal) => fileRequest<T>(filePath(device, suffix), body, key, signal);

export async function encodeFileChunk(file: Blob, offset: number) {
  const bytes = new Uint8Array(await file.slice(offset, offset + FILE_CHUNK).arrayBuffer());
  let binary = '';
  for (let i = 0; i < bytes.length; i += 8192) binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
  return { offset, data: btoa(binary), sha256: Array.from(sha256(bytes), b => b.toString(16).padStart(2, '0')).join('') };
}

export function launchDownload(path: string): HTMLIFrameElement {
  const url = new URL(path, new URL(API_BASE_URL, location.href));
  if (url.origin !== new URL(API_BASE_URL, location.href).origin || !/^\/api\/v1\/remote\/devices\/[0-9a-f-]+\/downloads\/[0-9a-f]{32}\/content\/$/.test(url.pathname)) {
    throw new Error('下载地址无效。');
  }
  const frame = document.createElement('iframe');
  frame.hidden = true; frame.title = '浏览器文件下载'; frame.src = url.href;
  document.body.appendChild(frame);
  return frame;
}
