import { api } from './api';
import type { TemplateCategory, TemplateDetail, TemplateSummary } from '@/types/template';

export interface CasePage { count: number; results: TemplateSummary[] }
export interface CasePreview {
  case_id: number | null; task_id: string | null; title: string; summary: string;
  category: number | null; tags: string[]; source_content: string;
  analysis_sections: { title: string; content: string; evidence_quote?: string }[];
}
export interface CaseSaveInput { task_id?: string; action: 'save' | 'update'; title?: string; summary?: string; category?: number; tags?: string[] }
export interface CaseSaved { case_id: number; result: 'created' | 'existing' | 'updated' }
export interface CaseReference { id: number; title: string; source_content?: string }
export const casesApi = {
  list: async (params: Record<string, unknown> = {}): Promise<CasePage> => {
    const result = await api.get<CasePage | TemplateSummary[]>('/templates/', params);
    return Array.isArray(result) ? { count: result.length, results: result } : result;
  },
  detail: (id: number) => api.get<TemplateDetail>(`/templates/${id}/`),
  categories: async () => {
    const result = await api.get<TemplateCategory[] | { results: TemplateCategory[] }>('/templates/categories/');
    return Array.isArray(result) ? result : result.results;
  },
  applications: () => api.get<{ id: number; name: string }[]>('/templates/douyin_applications/'),
};
