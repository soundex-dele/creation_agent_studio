import { api } from './api';
import { API_BASE_URL } from './apiBaseUrl';

export interface TranscriptSegment { id: string; start: number; end: number; text: string; original_text: string }
export interface Evidence { text: string; segment_ids: string[] }
export interface MeetingAction {
  id: string; analysis_version: number; revision: string; title: string; description: string; priority: number;
  due_date: string | null; segment_ids: string[]; todo_id: string | null; confirmed_at: string | null;
}
export type MeetingAnalysis = Record<'topics' | 'decisions' | 'viewpoints' | 'quotes' | 'facts' | 'outline', Evidence[]>;
export interface MeetingRecord {
  id: string; title: string; kind: 'meeting' | 'interview'; recorded_on: string; language: string;
  filename: string; size: number; duration: number; segments: TranscriptSegment[];
  version: number; analysis_version: number; analysis: Partial<MeetingAnalysis>; status: string;
  stale: boolean; error: string; actions: MeetingAction[]; run_id: string | null; created_at: string; updated_at: string;
}
export type MeetingSummary = Omit<MeetingRecord, 'segments' | 'analysis' | 'actions'>;
export type MeetingClient = ReturnType<typeof meetingApi>;
export const activeMeeting = (status: string) => ['queued', 'running', 'transcribing', 'analyzing', 'cancelling'].includes(status);
export const meetingStatus: Record<string, string> = {
  queued: '排队中', running: '处理中', transcribing: '正在转录', analyzing: '正在分析',
  completed: '已完成', failed: '处理失败', cancelled: '已取消', cancelling: '正在取消',
};
export const timeLabel = (seconds: number) => {
  const value = Math.max(0, Math.floor(seconds));
  return `${Math.floor(value / 3600).toString().padStart(2, '0')}:${Math.floor(value % 3600 / 60).toString().padStart(2, '0')}:${(value % 60).toString().padStart(2, '0')}`;
};
export function meetingError(error: unknown): string {
  const data = (error as { response?: { data?: unknown } })?.response?.data;
  if (data && typeof data === 'object') return Object.values(data).flat().join('；');
  return error instanceof Error ? error.message : '操作失败，请重试。';
}
export function audioFileError(file: File): string {
  if (!/\.(mp3|wav|m4a|aac|flac|ogg)$/i.test(file.name)) return '支持 MP3、WAV、M4A、AAC、FLAC 和 OGG。';
  return file.size <= 0 || file.size > 200 * 1024 * 1024 ? '录音大小须为 1 字节至 200 MiB。' : '';
}
export function meetingApi(base: string) {
  const record = (id: string) => `${base}/records/${id}`;
  return {
    list: (search: string, page: number, signal?: AbortSignal) => api.get<{ count: number; results: MeetingSummary[] }>(`${base}/records`, { search, page }, { signal }),
    get: (id: string, signal?: AbortSignal) => api.get<MeetingRecord>(record(id), undefined, { signal }),
    upload: (data: FormData, progress: (percent: number) => void, signal?: AbortSignal) => api.post<MeetingRecord>(`${base}/records`, data, {
      timeout: 600000, signal, headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: (event) => progress(Math.round((event.loaded / (event.total || 1)) * 100)),
    }),
    saveMetadata: (id: string, version: number, data: { title: string; kind: string; recorded_on: string }) => api.patch<MeetingRecord>(record(id), { ...data, version }),
    saveTranscript: (id: string, version: number, segments: { id: string; text: string }[]) => api.patch<MeetingRecord>(`${record(id)}/transcript`, { version, segments }),
    run: (id: string, version: number, operation: 'process' | 'analyze', key: string) => api.post(`${record(id)}/runs`, { version, operation }, { headers: { 'Idempotency-Key': key } }),
    cancel: (id: string) => api.post<MeetingRecord>(`${record(id)}/cancel`),
    remove: (id: string) => api.delete(record(id)),
    saveAction: (id: string, version: number, action: MeetingAction) => api.patch<MeetingAction>(`${record(id)}/actions/${action.id}`, {
      version, revision: action.revision, title: action.title, description: action.description, priority: action.priority, due_date: action.due_date,
    }),
    confirm: (id: string, version: number, actions: MeetingAction[]) => api.post<{ application_id: number; actions: MeetingAction[] }>(`${record(id)}/confirm-actions`, {
      version, confirmed: true, action_ids: actions.map(action => action.id),
      action_versions: Object.fromEntries(actions.map(action => [action.id, action.revision])),
    }),
    document: (id: string, version: number, kind: string, key: string) => api.post<{ application_id: number; document_id: string }>(`${record(id)}/documents`, { version, kind }, { headers: { 'Idempotency-Key': key } }),
    access: async (id: string) => {
      const value = await api.post<{ token: string; expires_in: number }>(`${record(id)}/access`);
      return { url: `${API_BASE_URL}${base}/content?token=${encodeURIComponent(value.token)}`, expires_in: value.expires_in };
    },
  };
}
