import { api } from './api';
import { createIdempotencyKey } from '@/lib/idempotencyKey';

export type Data = Record<string, unknown>;
export type Resource = 'cases' | 'topics' | 'channels' | 'feedback';
export interface CopyBody { title: string; body: string; cover: string; pages: string; script: string; materials: string; shots: string; checks: string; formatted_html: string }
export interface Version { id: string; number: number; body: CopyBody; snapshot: Data; created_at: string }
export interface SourceSnapshot { origin?: { path?: string; commit?: string }; digest?: string; coverage?: { files_read: number; files_total: number; note: string }; evidence?: Record<string, { path: string; start: number; end: number; quote: string; sha256: string }> }
export interface PromotionRecord { id: string; title: string; status: string; archived: boolean; revision: number; data: Data; case_id?: string; topic_id?: string; channel_id?: string | null; platform?: string; confirmed_version_id?: string | null; latest_version?: Version | null; source_snapshot?: SourceSnapshot }
export interface Task { id: string; kind: string; status: string; applied: boolean; error: string; request: Data; result: Data; stage?: string; created_at: string }
export interface Group { key: string; label: string; publications: number; metrics: Record<string, { total: number | null; samples: number }> }
export interface Report { publications: Data[]; groups: { platforms: Group[]; cases: Group[] }; unknown_source_count: number; note: string }
export interface Handoff { id: string; version_id: string; target_application_id: number; kind: string; url: string; status: string; target_id: string }
export interface Destination { id: number; name: string; slug: string }
export const resources: Resource[] = ['cases', 'topics', 'channels', 'feedback'];
export const platforms: Record<string, string> = { wechat: '公众号', xiaohongshu: '小红书', douyin: '抖音', moments: '朋友圈' };
export const directions: Record<string, string> = { demo: '功能演示', solution: '问题解决', development: '开发记录', experience: '经验分享' };
export const statuses: Record<string, string> = { draft: '待制作', confirmed: '已确认', ready: '待发布', published: '已发布', paused: '暂缓', recorded: '已记录' };
export const bodyLabels: Record<keyof CopyBody, string> = { title: '标题', body: '正文／发布配文', cover: '封面文字', pages: '逐页文案', script: '演示脚本', materials: '所需素材', shots: '拍摄清单', checks: '待核实事项', formatted_html: '排版 HTML（仅保存与下载）' };
export const string = (value: unknown) => value == null ? '' : String(value);
export const activeTask = (task: Task) => ['queued', 'running', 'waiting_input', 'waiting_children', 'cancelling'].includes(task.status);
export function promotionError(error: unknown): string {
  const data = (error as { response?: { data?: unknown } })?.response?.data;
  return data ? typeof data === 'string' ? data : JSON.stringify(data) : error instanceof Error ? error.message : '操作失败，请重试。';
}
export function promotionApi(base: string) {
  let pending: { signature: string; key: string } | null = null;
  async function all<T>(resource: string): Promise<T[]> {
    const rows: T[] = []; let page: number | null = 1;
    while (page) {
      const result: { results: T[]; next: number | null } = await api.get(`${base}/${resource}`, { page });
      rows.push(...result.results); page = result.next;
    }
    return rows;
  }
  return {
    all,
    record: (kind: Resource, id: string) => api.get<PromotionRecord>(`${base}/${kind}/${id}`),
    create: (kind: Resource, data: Data) => api.post<PromotionRecord>(`${base}/${kind}`, data),
    update: (kind: Resource, row: PromotionRecord, data: Data) => api.patch<PromotionRecord>(`${base}/${kind}/${row.id}`, { ...data, revision: row.revision }),
    report: () => api.get<Report>(`${base}/report`),
    start: async (value: Data) => {
      const signature = JSON.stringify(value);
      if (pending?.signature !== signature) pending = { signature, key: createIdempotencyKey('promotion') };
      const result = await api.post<Task>(`${base}/ai/tasks`, { ...value, request_key: pending.key });
      pending = null;
      return result;
    },
    apply: (id: string) => api.post<Task>(`${base}/ai/tasks/${id}/apply`),
    cancel: (id: string) => api.post<Task>(`${base}/ai/tasks/${id}/cancel`),
    versions: (id: string) => api.get<Version[]>(`${base}/channels/${id}/versions`),
    saveVersion: (row: PromotionRecord, body: CopyBody, baseVersion?: string) => api.post<Version>(`${base}/channels/${row.id}/versions`, { revision: row.revision, body, ...(baseVersion ? { base_version_id: baseVersion } : {}) }),
    confirm: (row: PromotionRecord, id: string) => api.post<PromotionRecord>(`${base}/channels/${row.id}/versions/${id}/confirm`, { revision: row.revision }),
    download: (row: PromotionRecord, id: string, format = 'md') => api.get<Blob>(`${base}/channels/${row.id}/versions/${id}/download`, { format }, { responseType: 'blob' }),
    destinations: () => api.get<Destination[]>(`${base}/integrations`),
    handoffs: () => api.get<Handoff[]>(`${base}/handoffs`),
    handoff: (row: PromotionRecord, version: string, target: number) => api.post<Handoff>(`${base}/handoffs`, { channel_id: row.id, version_id: version, target_id: target }),
    results: (id: string) => api.get<{ id: number; content: string; created_at: string }[]>(`${base}/handoffs/${id}/results`),
    importResult: (id: string, message: number) => api.post<Version>(`${base}/handoffs/${id}/results`, { message_id: message }),
  };
}
export type PromotionApi = ReturnType<typeof promotionApi>;
