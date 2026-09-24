import { api } from './api';

export interface ResearchProject { id: string; title: string; objective: string; created_at: string; updated_at: string }
export interface ResearchSource {
  id: string; title: string; filename: string; byte_size: number; status: 'pending' | 'indexing' | 'ready' | 'failed';
  error: string; error_code: string; removed: boolean; metadata: { index_stage?: string; index_progress?: number };
  origin: { type: string; id?: string; application_id?: number; version?: number };
}
export type ResearchKind = 'report' | 'comparison' | 'writing_pack';
export const researchKinds: Record<ResearchKind, string> = { report: '研究报告', comparison: '观点对照', writing_pack: '写作资料包' };
export const claimLabels = { fact: '事实', quote: '摘录', inference: '推断', gap: '待核实', suggestion: '建议' };
export interface ResearchCitation {
  id: string; number: number; source_id: string; title: string; quote: string; chunk_id: number;
  page_number: number | null; paragraph_number: number | null; section_path: string[]; position: number;
  context?: string; origin?: ResearchSource['origin']; filename?: string;
}
export interface ResearchOutput {
  title: string; sections: { heading: string; items: { type: keyof typeof claimLabels; text: string; evidence_ids: string[]; source_id?: string; source_title?: string }[] }[];
  citations: ResearchCitation[];
  coverage: { source_id: string; title: string; chunks_reviewed: number; chunks_total: number; evidence_found: number; evidence_selected: number }[];
}
export interface ResearchResult {
  id: string; kind: ResearchKind; instruction: string; objective: string; source_ids: string[]; run_id: string | null;
  status: string; error: string; created_at: string; progress: { stage: string; current: number; total: number } | null;
  output?: ResearchOutput | null;
}
export interface ResearchPage<T> { count: number; results: T[] }
export interface ResearchIntegration { id: number; name: string; target: 'document' | 'drive' }
export interface ImportEntry { id: string; title: string; kind: 'file' | 'folder'; byte_size?: number }
export interface ResearchIntegrations { applications: ResearchIntegration[]; limits: { max_sources: number; max_file_bytes: number; max_text_bytes: number } }
export function citationLocation(c: ResearchCitation) {
  if (c.page_number) return `第 ${c.page_number} 页`;
  return [...c.section_path, ...(c.paragraph_number ? [`第 ${c.paragraph_number} 段`] : [])].join(' / ') || `片段 ${c.position + 1}`;
}
export function isResearchActive(status: string) { return !['succeeded', 'failed', 'cancelled'].includes(status); }
export function researchApi(base: string) {
  const project = (id: string) => `${base}/projects/${id}`;
  return {
    projects: (search: string, page: number, signal?: AbortSignal) => api.get<ResearchPage<ResearchProject>>(`${base}/projects`, { search, page }, { signal }),
    create: (title: string) => api.post<ResearchProject>(`${base}/projects`, { title }),
    project: (id: string) => api.get<ResearchProject>(project(id)),
    save: (id: string, body: Pick<ResearchProject, 'title' | 'objective'>) => api.patch<ResearchProject>(project(id), body),
    remove: (id: string) => api.delete(project(id)),
    sources: (id: string) => api.get<ResearchSource[]>(`${project(id)}/sources`),
    addSource: (id: string, body: unknown, progress?: (percent: number) => void) => api.post<ResearchSource & { reused?: boolean }>(`${project(id)}/sources`, body,
      { timeout: 120000, onUploadProgress: (e) => progress?.(e.total ? Math.round(e.loaded / e.total * 100) : 0) }),
    removeSource: (id: string, source: string) => api.delete(`${project(id)}/sources/${source}`),
    retrySource: (id: string, source: string) => api.post(`${project(id)}/sources/${source}/retry`),
    results: (id: string, page: number) => api.get<ResearchPage<ResearchResult>>(`${project(id)}/results`, { page }),
    result: (id: string, result: string) => api.get<ResearchResult>(`${project(id)}/results/${result}`),
    generate: (id: string, body: { source_ids: string[]; kind: ResearchKind; instruction: string }, key: string) =>
      api.post<ResearchResult>(`${project(id)}/results`, body, { headers: { 'Idempotency-Key': key } }),
    cancel: (id: string, result: string) => api.post(`${project(id)}/results/${result}/cancel`),
    citation: (id: string, result: string, citation: string) => api.get<ResearchCitation>(`${project(id)}/results/${result}/citations/${citation}`),
    integrations: () => api.get<ResearchIntegrations>(`${base}/integrations`),
    imports: (params: { target: string; application_id: number; search: string; page: number; parent?: string }, signal?: AbortSignal) => api.get<ResearchPage<ImportEntry>>(`${base}/imports`, params, { signal }),
    export: (id: string, result: string, integration: ResearchIntegration, key: string) => api.post<{ id: string; target: string; application_id: number }>(`${project(id)}/results/${result}/export`,
      { target: integration.target, application_id: integration.id }, { headers: { 'Idempotency-Key': key } }),
    download: (id: string, result: string) => api.get<Blob>(`${project(id)}/results/${result}/download`, undefined, { responseType: 'blob' }),
    original: (id: string, source: string) => api.get<Blob>(`${project(id)}/sources/${source}/content`, undefined, { responseType: 'blob', timeout: 120000 }),
  };
}
export function saveResearchBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a'); link.href = url;
  link.download = filename.replace(/[<>:"/\\|?*]/g, '_'); link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
