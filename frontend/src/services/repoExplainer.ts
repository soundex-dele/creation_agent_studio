import { api } from './api';
import { createIdempotencyKey } from '@/lib/idempotencyKey';

export interface RepoEvidence { id: string; path: string; start: number; end: number; quote: string }
export interface RepoFeature { id: string; title: string; description: string; scenario: string; entry: string; requirements: string; limitations: string; discrepancies: string; status: 'documented' | 'implemented' | 'unconfirmed'; evidence_ids: string[] }
export interface RepoReport { summary: string; audience: string; workflow: string[]; deployment: string[]; limitations: string[]; features: RepoFeature[]; evidence: Record<string, RepoEvidence>; coverage: { files_read: number; files_total: number; chunks_read: number; chunks_total: number; incomplete: boolean; note: string } }
export interface RepoRefs { feature_ids: string[]; evidence_ids: string[]; needs_review: boolean }
export interface RepoScene extends RepoRefs { narration: string; visual: string; seconds: number }
export interface RepoSection extends RepoRefs { heading: string; body: string; image: string }
export interface RepoDocument { title: string; cover: string; aspect: string; checklist: string[]; scenes: RepoScene[]; article: { title: string; intro: string; sections: RepoSection[] }; needs_review: boolean }
export interface RepoContent { id: string; title: string; analysis_id: string; revision: number; draft: RepoDocument; versions: { id: string; revision: number; document: RepoDocument }[] }
export interface RepoSnapshot { id: string; origin: { kind: string; url?: string; path?: string; filename?: string; commit?: string; ref?: string; working_tree?: boolean }; digest: string; status: string; error: string; created_at: string; coverage: { files_included?: number; text_bytes?: number; excluded?: { path: string; reason: string }[]; notes?: string[] } }
export interface RepoTask { id: string; kind: string; status: string; snapshot_id: string; error: string; progress: { stage?: string }; output: Partial<RepoReport> & { content_id?: string }; options: Record<string, unknown> }
export interface RepoProject { id: string; title: string; archived: boolean; updated_at: string }
export interface RepoHandoff { id: string; kind: string; version_id: string; target_application_id: number; target_id: string; url: string; status: string; draft: Record<string, string>; revision: number; created_at: string }
export interface RepoDetail extends RepoProject { snapshots: RepoSnapshot[]; tasks: RepoTask[]; contents: RepoContent[]; handoffs: RepoHandoff[]; limits: Record<string, number> }
export interface RepoDestination { id: number; name: string; slug: string }
export interface RepoBrief { angle: string; output: string; audience: string; style: string; duration: number; aspect: string }
export const defaultRepoBrief: RepoBrief = { angle: 'overview', output: 'both', audience: '有 AI 使用需求的普通用户', style: '清晰、具体、口语自然', duration: 60, aspect: '16:9' };
export const repoTerminal = (status: string) => ['succeeded', 'failed', 'cancelled'].includes(status);
export function repoError(e: unknown): string {
  const data = (e as { response?: { data?: unknown } })?.response?.data;
  if (typeof data === 'object' && data && 'detail' in data) return String(data.detail);
  if (data) return JSON.stringify(data);
  return e instanceof Error ? e.message : '操作失败，请重试';
}

/** Retains keys for uncertain network outcomes; a successful/new payload gets a fresh key. */
export function repoApi(base: string) {
  const requests = new Map<string, { payload: unknown; key: string }>();
  const files = new WeakMap<Blob, number>();
  let fileSequence = 0;
  async function post<T>(path: string, body: unknown) {
    const signature = body instanceof FormData ? JSON.stringify([...body.entries()].map(([key, value]) => {
      if (typeof value === 'string') return [key, value];
      if (!files.has(value)) files.set(value, ++fileSequence);
      return [key, files.get(value)];
    })) : JSON.stringify(body);
    let pending = requests.get(path);
    if (!pending || pending.payload !== signature) {
      pending = { payload: signature, key: createIdempotencyKey() };
      requests.set(path, pending);
    }
    const result = await api.post<T>(base + path, body, { headers: { 'Idempotency-Key': pending.key } });
    if (requests.get(path) === pending) requests.delete(path);
    return result;
  }
  return {
    projects: (archived = false) => api.get<RepoProject[]>(base + '/projects', { archived: archived ? '1' : '0' }),
    create: (title: string) => api.post<RepoProject>(base + '/projects', { title }),
    project: (id: string) => api.get<RepoDetail>(`${base}/projects/${id}`),
    update: (id: string, body: Partial<RepoProject>) => api.patch<RepoProject>(`${base}/projects/${id}`, body),
    import: (id: string, body: FormData | Record<string, string>) => post<RepoTask>(`/projects/${id}/imports`, body),
    task: (id: string, body: Record<string, unknown>) => post<RepoTask>(`/projects/${id}/tasks`, body),
    cancel: (id: string, task: string) => api.post(`${base}/projects/${id}/tasks/${task}/cancel`, {}),
    evidence: (id: string, snapshot: string, path: string) => api.get<{ text: string; source_url: string }>(`${base}/projects/${id}/snapshots/${snapshot}/evidence`, { path }),
    save: (id: string, content: string, revision: number, document: RepoDocument) => api.put<RepoContent>(`${base}/projects/${id}/contents/${content}`, { revision, document }),
    download: (id: string, content: string) => api.get<Blob>(`${base}/projects/${id}/contents/${content}/download`, undefined, { responseType: 'blob' }),
    destinations: () => api.get<RepoDestination[]>(base + '/integrations'),
    handoff: (id: string, version: string, target: number) => post<RepoHandoff>(`/projects/${id}/handoffs`, { version_id: version, target_id: target }),
  };
}
export type RepoClient = ReturnType<typeof repoApi>;
