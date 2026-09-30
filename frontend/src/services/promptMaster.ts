import { api } from './api';

export const scenes = { auto: '自动识别', writing: '写作', coding: '编程', learning: '学习', office: '办公', image: '绘图', video: '视频', general: '通用' };
export type Scene = keyof typeof scenes;
export type Mode = 'generate' | 'optimize';
export interface PromptInput { mode: Mode; topic: string; original: string; objective: string; scene: Scene; language: 'zh' | 'en' }
export interface Question { id: string; label: string; help: string; type: 'text' | 'single_choice' | 'multi_choice'; options: { value: string; label: string }[]; recommended: string }
export type Answers = Record<string, string | string[] | null>;
export interface Health { problem: string; suggestion: string }
export interface PromptVersion {
  id: string; source: string; standard: string; concise: string; assumptions: string[]; health: Health[];
  changes: string[]; health_stale: boolean; constraints: { text: string; standard_excerpt: string; concise_excerpt: string }[];
  basis: Record<string, unknown>; created_at: string;
}
export interface PromptTask { id: string; kind: TaskKind; status: string; error: string; revision: number; result: Record<string, unknown> }
export type TaskKind = 'analyze' | 'generate' | 'optimize' | 'check';
export interface SessionSummary {
  id: string; title: string; mode: Mode; scene: Scene; detected_scene: Scene; favorite: boolean;
  revision: number; results_stale: boolean; created_at: string; updated_at: string;
}
export interface PromptSession extends PromptInput, SessionSummary {
  questions: Question[]; answers: Answers; rounds: number; analysis: { summary?: string; issues?: Health[] };
  latest_version: PromptVersion | null; latest_task: PromptTask | null;
}
export interface Template { id: string; scene: Scene; title: string; topic: string }
export interface Page<T> { count: number; results: T[] }
export const isActiveTask = (task: PromptTask | null) => !!task && ['queued', 'running', 'waiting_input', 'waiting_children', 'cancelling'].includes(task.status);
export const blankInput = (mode: Mode = 'generate'): PromptInput => ({ mode, topic: '', original: '', objective: '', scene: 'auto', language: 'zh' });
export const inputOf = (s: PromptInput): PromptInput => ({ mode: s.mode, topic: s.topic, original: s.original, objective: s.objective, scene: s.scene, language: s.language });
export const promptApi = (base: string) => {
  const path = (id: string) => `${base}/sessions/${id}`;
  return {
    catalog: () => api.get<{ templates: Template[] }>(`${base}/catalog`),
    list: (search: string, scene: string, favorite: boolean, page: number) => api.get<Page<SessionSummary>>(`${base}/sessions`, { search, scene, favorite: favorite ? '1' : '', page }),
    create: (data: PromptInput) => api.post<PromptSession>(`${base}/sessions`, data),
    get: (id: string) => api.get<PromptSession>(path(id)),
    update: (id: string, revision: number, data: Partial<PromptInput> & { title?: string; favorite?: boolean; answers?: Answers }) => api.patch<PromptSession>(path(id), { ...data, revision }),
    remove: (id: string, revision: number) => api.delete(`${path(id)}?revision=${revision}`),
    copy: (id: string) => api.post<PromptSession>(`${path(id)}/copy`),
    versions: (id: string, page = 1) => api.get<Page<PromptVersion>>(`${path(id)}/versions`, { page }),
    saveVersion: (id: string, revision: number, version_id: string, standard: string, concise: string) => api.post<PromptSession>(`${path(id)}/versions`, { revision, version_id, standard, concise }),
    start: (id: string, revision: number, kind: TaskKind, request_key: string, instruction = '', version_id?: string) => api.post<PromptTask>(`${path(id)}/tasks`, { revision, kind, request_key, instruction, ...(version_id ? { version_id } : {}) }),
    task: (id: string, taskId: string) => api.get<PromptTask>(`${path(id)}/tasks/${taskId}`),
    cancel: (id: string, taskId: string) => api.post<PromptTask>(`${path(id)}/tasks/${taskId}/cancel`),
  };
};
export type PromptClient = ReturnType<typeof promptApi>;

export function promptError(error: unknown): string {
  const data = (error as { response?: { data?: unknown } })?.response?.data;
  if (typeof data === 'string') return data.slice(0, 300);
  if (data && typeof data === 'object') {
    return Object.values(data).flat().filter((value) => typeof value === 'string').join('；') || '请求失败，请稍后重试。';
  }
  return '网络连接失败，请检查连接后重试。';
}
