import { api } from '@platform/http';
import { API_BASE_URL } from '@platform/services/apiBaseUrl';

export interface DriveEntry {
  id: string; parent: string | null; name: string; kind: 'file' | 'folder'; size: number;
  media_type: string; trash_root: boolean; created_at: string; updated_at: string;
}
export interface DriveCapacity { used: number; reserved: number; limit: number; max_file_size: number }
export interface DriveListing {
  count: number; results: DriveEntry[]; breadcrumbs: { id: string; name: string }[]; capacity: DriveCapacity;
}
export interface DriveUpload {
  id: string; parent: string | null; entry: string | null; name: string; size: number; last_modified: number;
  offset: number; chunk_size: number; state: 'uploading' | 'completed' | 'cancelling' | 'cancelled'; updated_at: string;
  chunks?: { offset: number; size: number; sha256: string }[];
}
export type PreviewKind = 'image' | 'video' | 'audio' | 'text' | 'unsupported';
export type DriveAction = 'rename' | 'move' | 'trash' | 'restore' | 'purge';
export { driveError, formatBytes } from '@platform/files';
export function myDriveApi(base: string) {
  return {
    list: (params: Record<string, unknown>, signal?: AbortSignal) => api.get<DriveListing>(base, params, { signal }),
    folder: (name: string, parent: string | null) => api.post<DriveEntry>(base, { name, parent }),
    action: (action: DriveAction, ids: string[], extra?: { name?: string; parent?: string | null }) => api.post(`${base}/actions`, { action, ids, ...extra }),
    uploads: (page = 1) => api.get<{ count: number; next: string | null; results: DriveUpload[] }>(`${base}/uploads`, { page }),
    createUpload: (file: File, parent: string | null) => api.post<DriveUpload>(`${base}/uploads`, { name: file.name, size: file.size, last_modified: file.lastModified, parent }),
    upload: (id: string, signal?: AbortSignal) => api.get<DriveUpload>(`${base}/uploads/${id}`, undefined, { signal }),
    chunk: (id: string, offset: number, hash: string, data: Blob, signal?: AbortSignal) => api.put<DriveUpload>(`${base}/uploads/${id}/chunk`, data, {
      signal, timeout: 300000, headers: { 'Content-Type': 'application/octet-stream', 'X-Chunk-Offset': String(offset), 'X-Chunk-SHA256': hash },
    }),
    complete: (id: string, signal?: AbortSignal) => api.post<DriveUpload>(`${base}/uploads/${id}/complete`, {}, { signal, timeout: 60000 }),
    cancel: (id: string) => api.delete<DriveUpload>(`${base}/uploads/${id}`),
    access: async (id: string, mode: 'preview' | 'download') => {
      const value = await api.post<{ token: string; kind: PreviewKind; expires_in: number }>(`${base}/entries/${id}/access`, { mode });
      return { ...value, url: `${API_BASE_URL}${base}/content?token=${encodeURIComponent(value.token)}` };
    },
  };
}
export type DriveClient = ReturnType<typeof myDriveApi>;
