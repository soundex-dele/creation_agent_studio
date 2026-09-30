import { api } from './api';
import type { AnimationDestination } from './douyinAnimation';

export interface CollectorConfig { configured: boolean; user_agent: string; has_cookies: boolean; screen: string; language: string; timezone: string; updated_at: string | null }
export type CollectorConfigInput = Pick<CollectorConfig, 'user_agent' | 'screen' | 'language' | 'timezone'> & { cookies?: string };

export interface DouyinAccount { id: string; source_url: string; name: string; group: string; notes: string; profile: { signature?: string }; updated_at: string }
export interface DouyinWork {
  id: string; platform_id: string; title: string; description: string; url: string; video_url?: string; cover: string; kind: string;
  published_at: string | null; duration: number | null; likes: number | null; comments: number | null;
  collects: number | null; shares: number | null; ratio: number | null; outstanding: boolean; has_upload: boolean;
}
export interface Claim { type: 'observation' | 'inference' | 'suggestion'; text: string; refs: string[] }
export interface Script { title: string; cover: string; narration: string; scenes: { time: string; visual: string; spoken: string }[]; checklist: string[] }
export type Kind = 'collect' | 'account' | 'breakdown' | 'topics' | 'script';
export interface DouyinTask {
  id: string; kind: Kind; work_id: string | null; run_id: string; status: string; stage: string; error: string; created_at: string;
  progress: { current?: number; total?: number }; sources: (DouyinWork & { id: string })[];
  output: Partial<Script> & {
    claims?: Claim[]; actual?: number; requested?: number; complete?: boolean; warning?: string; captured_at?: string;
    segments?: { id: string; start: number; end: number; text: string }[]; frames?: { id: string; time: number }[];
    visual_status?: string; visual_note?: string; transcript_note?: string;
    topics?: { title: string; angle: string; hook: string }[];
    statistics?: { sample_count: number; observed_days: number; posts_per_week: number | null; duration_buckets: Record<string, number> };
  };
}
export interface WorkResult { items: DouyinWork[]; sample_size: number; median_likes: number | null; explanation: string; batch: DouyinTask | null }
export interface ScriptVersion { id: string; revision: number; content: Script; created_at: string }
export interface Brief { positioning: string; audience: string; theme: string; duration: number; conditions: string; brand_profile_id?: string | null }
export const kindLabels: Record<Kind, string> = { collect: '采集', account: '账号分析', breakdown: '视频拆解', topics: '选题', script: '脚本' };
export const isActive = (task: DouyinTask) => !['succeeded', 'failed', 'cancelled'].includes(task.status);
export const metric = (value: number | null | undefined) => value == null ? '未获取' : value.toLocaleString('zh-CN');
const key = () => ({ headers: { 'Idempotency-Key': crypto.randomUUID() } });
export function douyinApi(base: string) {
  const account = (id: string) => `${base}/accounts/${id}`;
  const task = (id: string, taskId: string) => `${account(id)}/tasks/${taskId}`;
  return {
    animationDestinations: () => api.get<AnimationDestination[]>(`${base}/animation-integrations`),
    collectorConfig: () => api.get<CollectorConfig>(`${base}/collector-config`),
    saveCollectorConfig: (body: CollectorConfigInput) => api.put<CollectorConfig>(`${base}/collector-config`, body),
    clearCollectorConfig: () => api.delete(`${base}/collector-config`),
    connection: () => api.get<{ connected: boolean; message: string }>(`${base}/connection`),
    brands: () => api.get<{ id: string; name: string }[]>(`${base}/brands`),
    accounts: (page = 1) => api.get<{ count: number; results: DouyinAccount[] }>(`${base}/accounts`, { page }),
    create: (body: { source: string; count: number; group: string; notes: string }) => api.post<DouyinAccount & { task: DouyinTask }>(`${base}/accounts`, body, key()),
    account: (id: string) => api.get<DouyinAccount>(account(id)),
    save: (id: string, body: { group: string; notes: string }) => api.patch<DouyinAccount>(account(id), body),
    remove: (id: string) => api.delete(account(id)),
    works: (id: string, params: { batch_id?: string; search: string; sort: string; outstanding: boolean }) => api.get<WorkResult>(`${account(id)}/works`, params),
    tasks: (id: string, page = 1) => api.get<{ count: number; results: DouyinTask[] }>(`${account(id)}/tasks`, { page }),
    task: (id: string, taskId: string) => api.get<DouyinTask>(task(id, taskId)),
    start: (id: string, body: { kind: Kind; [key: string]: unknown }) => api.post<DouyinTask>(`${account(id)}/tasks`, body, key()),
    cancel: (id: string, taskId: string) => api.post<DouyinTask>(`${task(id, taskId)}/cancel`),
    upload: (id: string, workId: string, file: File) => { const form = new FormData(); form.append('video', file); return api.post(`${account(id)}/works/${workId}/upload`, form, { timeout: 120000 }); },
    frame: (id: string, taskId: string, frameId: string) => api.get<Blob>(`${task(id, taskId)}/frames/${frameId}`, undefined, { responseType: 'blob' }),
    versions: (id: string, taskId: string) => api.get<ScriptVersion[]>(`${task(id, taskId)}/versions`),
    saveScript: (id: string, taskId: string, revision: number, content: Script) => api.post<ScriptVersion>(`${task(id, taskId)}/versions`, { revision, content }),
    download: (id: string, taskId: string, versionId: string) => api.get<Blob>(`${task(id, taskId)}/versions/${versionId}/download`, undefined, { responseType: 'blob' }),
  };
}
export type DouyinClient = ReturnType<typeof douyinApi>;
