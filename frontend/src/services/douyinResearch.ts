import { api } from './api';
import { createDouyinSubmitter } from './douyinRequests';
import { douyinApi, type DouyinTask, type DouyinWork, type Script, type ScriptVersion, type Claim } from './douyinBenchmark';

export interface Page<T> { count: number; results: T[] }
export interface RecordBase { id: string; revision: number; created_at: string; updated_at: string }
export interface CreatorProfile extends RecordBase { name: string; positioning: string; audience: string; experiences: string; products: string; voice: string; conditions: string; is_default: boolean; account?: string | null; content_pillars?: string; content_boundaries?: string; shared_inspiration_ids?: string[]; active_version?: string | null; active_version_number?: number | null }
export interface VoiceContent { current_positioning: string; positioning: string; audience: string; content_pillars: string; content_boundaries: string; rules: string; examples: string; avoid: string; prompt: string }
export interface VoiceSample extends RecordBase { profile: string; work: string | null; source_task: string | null; title: string; text: string; usage: 'style' | 'content' | 'exclude'; source_url: string; source_missing: boolean; work_kind?: string | null }
export interface VoiceEvidence { id: string; title: string; text: string; usage: string; source_url: string; work_id: string | null }
export interface VoiceVersion { id: string; number: number; profile: string; content: VoiceContent; evidence: VoiceEvidence[]; source_task: string | null; created_at: string }
export interface ArticleContent { title: string; body: string; notes: string[] }
export interface Inspiration extends RecordBase { title: string; kind: string; text: string; notes: string; tags: string[]; work: string | null; source_task: string | null; source_ref: string; source_time: number | null }
export interface Idea extends RecordBase { title: string; notes: string; tags: string[]; status: string; position: number; inspiration: string | null; source_task: string | null }
export interface ResearchWork extends DouyinWork { account_id: string; account_name: string; is_owned: boolean; captured_at: string }
export interface Publication extends RecordBase { work: string; idea: string | null; script_version: string | null; theme: string; title: string; hook: string; notes: string; work_detail: ResearchWork }
export interface Subscription extends RecordBase { account: string; enabled: boolean; interval_hours: number; count: number; tracked_works: string[]; rules: Record<string, number>; next_run_at: string | null; blocked_reason: string }
export interface Notice extends RecordBase { title: string; kind: string; read: boolean; account: string | null; work: string | null; body: { message?: string; title?: string; digest_id?: string; changes?: Record<string, { before: number; after: number; delta: number }> } }
export interface Digest extends RecordBase { day: string; body: { from: string; to: string; new_works: number; growth_alerts: number; errors: number; changes: { work_id: string; title: string; delta: Record<string, number> }[] } }
export type MetricKey = 'likes' | 'comments' | 'collects' | 'shares';
export interface TrendPoint { captured_at: string; values: Record<MetricKey, number | null>; delta: Record<MetricKey, number | null>; per_hour: Record<MetricKey, number | null> }
export interface Trend { work: ResearchWork; points: TrendPoint[] }
export interface PublicationSummary { note: string; by_theme: SummaryGroup[]; by_expression: SummaryGroup[] }
export interface SummaryGroup { label: string; sample_count: number; medians: Record<MetricKey, number | null>; age_days: number[] | null }
export interface Comparison { days: number; note: string; accounts: { account_id: string; name: string; captured_at: string | null; sample_count: number; posts_per_week: number | null; observed_days: number; duration_buckets: Record<string, number>; medians: Record<MetricKey, number | null>; eligible_sample: number; outstanding_share: number | null; explanation: string }[] }
export interface Topic { title: string; angle: string; hook?: string; refs?: string[]; is_new?: boolean | null; sample_count?: number; account_count?: number; median_likes?: number | null; pillar?: string; reason?: string; materials_needed?: string; duplicate_note?: string }
export interface Variant { text: string; angle: string }
export interface CommentRow { id: string; platform_id: string; parent_id: string; text: string; likes: number | null; published_at?: string | null }
export interface ResearchTask extends Omit<DouyinTask, 'kind' | 'output'> { account_id?: string | null; kind: string; output: Partial<Script> & {
  body?: string; notes?: string[];
  content?: VoiceContent; profile_id?: string; target_account_id?: string; voice_evidence?: VoiceEvidence[];
  findings?: { category: 'positioning' | 'keep' | 'improve'; text: string; sample_id: string; quote: string }[];
  creation_context?: { target_account_id?: string; account_name?: string; voice_version_number?: number };
  claims?: Claim[]; topics?: Topic[]; hooks?: Variant[]; titles?: Variant[]; covers?: Variant[]; warning?: string; actual?: number; note?: string;
  batch_id?: string; source_task_id?: string; comments?: CommentRow[]; sample_count?: number; work_id?: string; baseline?: boolean; new_topic_note?: string;
  coverage?: { available: number; sampled: number; days: number; accounts: { account_id: string; account_name: string; available: number; sampled: number }[] };
  children?: { task_id: string; work_id: string; status: string; error: string }[];
  evidence?: { task_id: string; account_id: string; work_id: string; segments: { id: string; start: number; end: number; text: string }[]; frames: { id: string; time: number }[] }[];
  comparison?: Comparison | { id: string; work: ResearchWork; theme: string; title: string; hook: string }[];
  segments?: { id: string; start: number; end: number; text: string }[]; frames?: { id: string; time: number }[];
} }
export interface ResearchVersion extends RecordBase { content: Partial<Script> & { text?: string; body?: string; notes?: string[]; hooks?: Variant[]; titles?: Variant[]; covers?: Variant[] } }
export function researchApi(base: string) {
  const submit = createDouyinSubmitter();
  return {
    list: <T>(resource: string, params: Record<string, unknown> = {}) => api.get<Page<T>>(`${base}/${resource}`, params),
    create: <T>(resource: string, body: unknown) => api.post<T>(`${base}/${resource}`, body),
    update: <T>(resource: string, id: string, body: unknown) => api.patch<T>(`${base}/${resource}/${id}`, body),
    remove: (resource: string, id: string) => api.delete(`${base}/${resource}/${id}`),
    start: (body: Record<string, unknown>) => submit<ResearchTask>(`${base}/tasks`, body),
    voiceVersions: (profile: string) => api.get<VoiceVersion[]>(`${base}/creator-profiles/${profile}/voice-versions`),
    confirmVoice: (profile: string, body: { revision: number; content: VoiceContent; source_task_id?: string }) => api.post<{ version: VoiceVersion; revision: number }>(`${base}/creator-profiles/${profile}/voice-versions`, body),
    activateVoice: (profile: string, version: string, revision: number) => api.post<{ version: VoiceVersion; revision: number }>(`${base}/creator-profiles/${profile}/voice-versions/${version}/activate`, { revision }),
    task: (id: string) => api.get<ResearchTask>(`${base}/tasks/${id}`),
    cancel: (id: string) => api.post<ResearchTask>(`${base}/tasks/${id}/cancel`),
    compare: (account_ids: string[], days: number) => api.post<Comparison>(`${base}/comparisons`, { account_ids, days }),
    trend: (id: string) => api.get<Trend>(`${base}/works/${id}/trend`),
    publicationSummary: () => api.get<PublicationSummary>(`${base}/publications/summary`),
    comments: (id: string, page = 1, batch?: string) => api.get<Page<CommentRow> & { batch: string | null; task_id?: string; warning?: string; batches: { id: string; task_id: string; created_at: string }[] }>(`${base}/works/${id}/comments`, { page, batch }),
    versions: (id: string) => api.get<ResearchVersion[]>(`${base}/tasks/${id}/versions`),
    saveVersion: (id: string, revision: number, content: ResearchVersion['content']) => api.post<ResearchVersion>(`${base}/tasks/${id}/versions`, { revision, content }),
    apply: (id: string, body: unknown) => api.post<ResearchVersion>(`${base}/tasks/${id}/apply`, body),
    refresh: (id: string) => submit<ResearchTask>(`${base}/subscriptions/${id}/refresh`, {}),
    frame: (taskId: string, ref: string) => api.get<Blob>(`${base}/tasks/${taskId}/frames/${ref}`, undefined, { responseType: 'blob' }),
    editor: {
      ...douyinApi(base),
      versions: (_account: string, taskId: string) => api.get<ScriptVersion[]>(`${base}/tasks/${taskId}/versions`),
      saveScript: (_account: string, taskId: string, revision: number, content: Script) => api.post<ScriptVersion>(`${base}/tasks/${taskId}/versions`, { revision, content }),
      download: (_account: string, taskId: string, versionId: string) => api.get<Blob>(`${base}/tasks/${taskId}/versions/${versionId}/download`, undefined, { responseType: 'blob' }),
    },
  };
}
export type ResearchClient = ReturnType<typeof researchApi>;
export function researchTaskStatus(task: { status: string; stage: string }): string {
  const labels: Record<string, string> = { queued: '排队中', succeeded: '已完成', failed: '失败', cancelled: '已取消', cancelling: '正在取消', waiting_input: '等待输入', waiting_children: '等待子任务' };
  if (labels[task.status]) return labels[task.status];
  if (task.stage === 'completed') return '正在保存结果';
  return !task.stage || ['queue', 'queued', 'running'].includes(task.stage) ? '正在执行' : task.stage;
}
export const researchLabels: Record<string, string> = { article: '文章写作', voice_analysis: '定位与文风分析', radar: '选题雷达', joint: '联合拆解', compare: '账号比较研究', comments: '评论采集', needs: '评论需求研究', variants: '表达实验', review: '作品复盘', refresh: '指标刷新', topics: '创作选题', script: '拍摄脚本', rewrite: '文案改写', breakdown: '视频拆解', transcribe: '转写', account: '账号分析', collect: '账号采集' };
export const metricLabels: Record<MetricKey, string> = { likes: '点赞', comments: '评论', collects: '收藏', shares: '分享' };
