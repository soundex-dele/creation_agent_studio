import { api } from './api';
import { createDouyinSubmitter } from './douyinRequests';
import type { AnimationDestination } from './douyinAnimation';

export interface CollectorConfig { configured: boolean; user_agent: string; has_cookies: boolean; cookies: string; screen: string; language: string; timezone: string; updated_at: string | null }
export type CollectorConfigInput = Pick<CollectorConfig, 'user_agent' | 'screen' | 'language' | 'timezone'> & { cookies?: string };

export interface DouyinAccount { is_owned?: boolean; id: string; source_url: string; name: string; group: string; notes: string; profile: { signature?: string }; updated_at: string }
export interface DouyinWork {
  id: string; platform_id: string; title: string; description: string; url: string; video_url?: string; cover: string; kind: string;
  published_at: string | null; duration: number | null; likes: number | null; comments: number | null;
  collects: number | null; shares: number | null; ratio: number | null; outstanding: boolean; has_upload: boolean;
}
export interface Claim { type: 'observation' | 'inference' | 'suggestion'; text: string; refs: string[] }
export const productionFormats = {
  talking_head: { label: '真人口播', hint: '出镜表达、景别机位、动作与提词' },
  screencast: { label: '录屏演示', hint: '屏幕操作、步骤高亮、同步解说' },
  animation: { label: '动画演示', hint: '图形动效、画面转场、旁白配合' },
  live_action: { label: '实景拍摄', hint: '场地道具、运镜动作、环境声音' },
  mixed: { label: '混合形式', hint: '组合多种形式，逐镜头标明用途' },
} as const;
export type ProductionFormat = keyof typeof productionFormats;
export interface Script { production_format?: ProductionFormat; title: string; cover: string; narration: string; scenes: { time: string; visual: string; spoken: string }[]; checklist: string[] }
export type Kind = 'collect' | 'account' | 'breakdown' | 'topics' | 'script' | 'transcribe' | 'rewrite';
export interface RewriteContent { text: string }
export interface RewriteVersion { id: string; revision: number; content: RewriteContent; created_at: string }
export interface DouyinTask {
  id: string; kind: Kind; work_id: string | null; run_id: string; status: string; stage: string; error: string; created_at: string;
  progress: { current?: number; total?: number; ai_preview?: { text: string; state: 'waiting' | 'receiving' | 'received' } }; sources: (DouyinWork & { id: string })[];
  copy_context?: { work_title: string; source_task_id: string; source_text: string; rewrite_requirements: string } | null;
  output: Partial<Script> & {
    text?: string;
    claims?: Claim[]; actual?: number; requested?: number; complete?: boolean; warning?: string; captured_at?: string;
    segments?: { id: string; start: number; end: number; text: string }[]; frames?: { id: string; time: number }[];
    visual_status?: string; visual_note?: string; transcript_note?: string;
    topics?: { title: string; angle: string; hook: string }[];
    statistics?: { sample_count: number; observed_days: number; posts_per_week: number | null; duration_buckets: Record<string, number> };
  };
}
export interface WorkResult { items: DouyinWork[]; sample_size: number; median_likes: number | null; explanation: string; batch: DouyinTask | null }
export interface ScriptVersion { id: string; revision: number; content: Script; created_at: string }
export interface Brief { production_format: ProductionFormat; positioning: string; audience: string; theme: string; duration: number; conditions: string; brand_profile_id?: string | null }
export const kindLabels: Record<Kind, string> = { collect: '采集', account: '账号分析', breakdown: '视频拆解', topics: '选题', script: '脚本', transcribe: '文案转写', rewrite: '文案复刻' };
export const isActive = (task: { status: string }) => !['succeeded', 'failed', 'cancelled'].includes(task.status);
export const metric = (value: number | null | undefined) => value == null ? '未获取' : value.toLocaleString('zh-CN');
export function douyinApi(base: string) {
  const submit = createDouyinSubmitter();
  const account = (id: string) => `${base}/accounts/${id}`;
  const task = (id: string, taskId: string) => `${account(id)}/tasks/${taskId}`;
  return {
    profiles: () => api.get<{ count: number; results: { id: string; name: string; positioning: string; audience: string; conditions: string; is_default: boolean; account?: string | null }[] }>(`${base}/creator-profiles`),
    animationDestinations: () => api.get<AnimationDestination[]>(`${base}/animation-integrations`),
    collectorConfig: () => api.get<CollectorConfig>(`${base}/collector-config`),
    saveCollectorConfig: (body: CollectorConfigInput) => api.put<CollectorConfig>(`${base}/collector-config`, body),
    clearCollectorConfig: () => api.delete(`${base}/collector-config`),
    connection: () => api.get<{ connected: boolean; message: string }>(`${base}/connection`),
    brands: () => api.get<{ id: string; name: string }[]>(`${base}/brands`),
    accounts: (page = 1) => api.get<{ count: number; results: DouyinAccount[] }>(`${base}/accounts`, { page }),
    create: (body: { source: string; count: number; group: string; notes: string; is_owned?: boolean }) => submit<DouyinAccount & { task: DouyinTask }>(`${base}/accounts`, body),
    account: (id: string) => api.get<DouyinAccount>(account(id)),
    save: (id: string, body: { group: string; notes: string }) => api.patch<DouyinAccount>(account(id), body),
    remove: (id: string) => api.delete(account(id)),
    works: (id: string, params: { batch_id?: string; search: string; sort: string; outstanding: boolean }) => api.get<WorkResult>(`${account(id)}/works`, params),
    tasks: (id: string, page = 1) => api.get<{ count: number; results: DouyinTask[] }>(`${account(id)}/tasks`, { page }),
    task: (id: string, taskId: string) => api.get<DouyinTask>(task(id, taskId)),
    downloadAccountAnalysis: (id: string, taskId: string) => api.get<Blob>(`${task(id, taskId)}/download`, undefined, { responseType: 'blob' }),
    start: (id: string, body: { kind: Kind; [key: string]: unknown }) => submit<DouyinTask>(`${account(id)}/tasks`, body),
    cancel: (id: string, taskId: string) => api.post<DouyinTask>(`${task(id, taskId)}/cancel`),
    upload: (id: string, workId: string, file: File) => { const form = new FormData(); form.append('video', file); return api.post(`${account(id)}/works/${workId}/upload`, form, { timeout: 120000 }); },
    frame: (id: string, taskId: string, frameId: string) => api.get<Blob>(`${task(id, taskId)}/frames/${frameId}`, undefined, { responseType: 'blob' }),
    versions: (id: string, taskId: string) => api.get<ScriptVersion[]>(`${task(id, taskId)}/versions`),
    rewriteVersions: (id: string, taskId: string) => api.get<RewriteVersion[]>(`${task(id, taskId)}/versions`),
    saveRewrite: (id: string, taskId: string, revision: number, content: RewriteContent) => api.post<RewriteVersion>(`${task(id, taskId)}/versions`, { revision, content }),
    saveScript: (id: string, taskId: string, revision: number, content: Script) => api.post<ScriptVersion>(`${task(id, taskId)}/versions`, { revision, content }),
    download: (id: string, taskId: string, versionId: string) => api.get<Blob>(`${task(id, taskId)}/versions/${versionId}/download`, undefined, { responseType: 'blob' }),
  };
}
export type DouyinClient = ReturnType<typeof douyinApi>;
