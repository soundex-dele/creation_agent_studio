import { api } from './api';
import { createIdempotencyKey } from '@/lib/idempotencyKey';

export type CleanerMode = 'analysis' | 'large' | 'cache';
export interface CleanerHost {
  id: string; name: string; supported: boolean; worker_online: boolean;
  volumes: { path: string; total: number; used: number; free: number }[]; cache_roots: string[];
}
export interface CleanerTask {
  id: string; kind: 'scan' | 'cleanup'; state: string; cancel_requested: boolean;
  parameters: { mode: CleanerMode; root: string; minimum_bytes: number };
  processed: number; total_bytes: number; skipped: number; deleted_bytes: number;
  free_before: Record<string, number>; free_after: Record<string, number>;
  message: string; created_at: string; finished_at: string | null; summary: Record<string, number>;
}
export interface CleanerEntry {
  id: string; path: string; parent: string; kind: 'file' | 'directory'; size: number;
  modified_at: string | null; cleanable: boolean; state?: string; reason?: string;
}
export interface CleanerListing { count: number; results: CleanerEntry[] }
export interface CleanerPreview {
  id: string; token: string; count: number; total_bytes: number; expires_at: string; host_name: string; root: string;
}
export interface CleanerDirectories { path: string; parent: string; directories: { path: string; name: string }[]; truncated: boolean }
export const cleanerActive = (task?: CleanerTask) => !!task && ['queued', 'running'].includes(task.state);

/** One key per unchanged payload, including retries after an ambiguous network failure. */
class RequestKey {
  private payload = '';
  private key = '';
  get(value: unknown) {
    const payload = JSON.stringify(value);
    if (payload !== this.payload || !this.key) {
      this.payload = payload;
      this.key = createIdempotencyKey('disk-cleaner');
    }
    return this.key;
  }
  clear() { this.key = ''; }
}

export function diskCleanerApi(base: string) {
  const scanKey = new RequestKey();
  const cleanupKey = new RequestKey();
  return {
    resetScanKey: () => scanKey.clear(),
    host: (signal?: AbortSignal) => api.get<CleanerHost>(`${base}/host`, undefined, { signal }),
    tasks: (signal?: AbortSignal) => api.get<{ count: number; results: CleanerTask[] }>(`${base}/tasks`, undefined, { signal }),
    task: (id: string, signal?: AbortSignal) => api.get<CleanerTask>(`${base}/tasks/${id}`, undefined, { signal }),
    entries: (id: string, params: Record<string, unknown>, signal?: AbortSignal) => api.get<CleanerListing>(`${base}/tasks/${id}/entries`, params, { signal }),
    directories: (path: string) => api.get<CleanerDirectories>(`${base}/directories`, { path }),
    scan: async (payload: { mode: CleanerMode; root: string; minimum_bytes: number }) => {
      const result = await api.post<CleanerTask>(`${base}/tasks`, { ...payload, request_key: scanKey.get(payload) });
      scanKey.clear(); return result;
    },
    cancel: (id: string) => api.post<CleanerTask>(`${base}/tasks/${id}`, {}),
    preview: (scan_id: string, entry_ids: string[]) => api.post<CleanerPreview>(`${base}/previews`, { scan_id, entry_ids }),
    previewEntries: (id: string, page: number, signal?: AbortSignal) => api.get<CleanerListing>(`${base}/previews/${id}`, { page }, { signal }),
    cleanup: async (token: string) => {
      const result = await api.post<CleanerTask>(`${base}/cleanups`, { token, request_key: cleanupKey.get(token) });
      cleanupKey.clear(); return result;
    },
  };
}
