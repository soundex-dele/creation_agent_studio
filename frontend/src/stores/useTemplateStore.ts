import { create } from 'zustand';
import { api } from '@/services/api';
import { casesApi } from '@/services/cases';
import { documentError } from '@/services/documents';
import type {
  TemplateCategory,
  TemplateDetail,
  TemplateSummary,
} from '@/types/template';

interface TemplateState {
  clearTemplates: () => void;
  detailError: string;
  count: number; page: number; mine: boolean; sourceKind: string; error: string;
  setPage: (page: number) => void;
  setMine: (mine: boolean) => void;
  setSourceKind: (kind: string) => void;
  categories: TemplateCategory[];
  templates: TemplateSummary[];
  currentTemplate: TemplateDetail | null;
  isLoadingTemplate: boolean;
  selectedCategory: string | null;
  searchQuery: string;
  isLoading: boolean;
  loadCategories: () => Promise<void>;
  loadTemplates: (category?: string) => Promise<void>;
  loadTemplate: (id: number) => Promise<TemplateDetail>;
  clearCurrentTemplate: () => void;
  selectCategory: (slug: string | null) => void;
  setSearchQuery: (query: string) => void;
}

const unwrap = <T,>(response: T[] | { results?: T[] }): T[] =>
  Array.isArray(response) ? response : response.results ?? [];

let listRequest = 0;
let detailRequest = 0;

export const useTemplateStore = create<TemplateState>((set, get) => ({
  detailError: '',
  clearTemplates: () => { listRequest++; set({ templates: [], count: 0, isLoading: true, error: '' }); },
  count: 0, page: 1, mine: false, sourceKind: '', error: '',
  setPage: page => set({ page }),
  setMine: mine => set({ mine, page: 1 }),
  setSourceKind: sourceKind => set({ sourceKind, page: 1 }),
  categories: [],
  templates: [],
  currentTemplate: null,
  isLoadingTemplate: false,
  selectedCategory: null,
  searchQuery: '',
  isLoading: false,

  loadCategories: async () => {
    try {
      const response = await api.get<TemplateCategory[] | { results?: TemplateCategory[] }>(
        '/templates/categories/',
      );
      set({ categories: unwrap(response) });
    } catch (error) {
      console.error('Failed to load case categories:', error);
    }
  },

  loadTemplate: async (id: number) => {
    const token = ++detailRequest;
    set({ isLoadingTemplate: true, currentTemplate: null, detailError: '' });
    try {
      const response = await api.get<TemplateDetail>(`/templates/${id}/`);
      if (token === detailRequest) set({ currentTemplate: response });
      return response;
    } catch (error) {
      if (token === detailRequest) set({ currentTemplate: null, detailError: documentError(error) });
      throw error;
    } finally {
      if (token === detailRequest) set({ isLoadingTemplate: false });
    }
  },

  clearCurrentTemplate: () => { detailRequest++; set({ currentTemplate: null, isLoadingTemplate: false, detailError: '' }); },

  loadTemplates: async (category?: string) => {
    const token = ++listRequest;
    set({ isLoading: true, error: '', templates: [], count: 0 });
    try {
      const { searchQuery, page, mine, sourceKind } = get();
      const response = await casesApi.list({ page, ...(category && { category }),
        ...(searchQuery.trim() && { search: searchQuery.trim() }), ...(mine && { mine: true }),
        ...(sourceKind && { source_kind: sourceKind }) });
      if (token === listRequest) set({ templates: response.results, count: response.count });
    } catch (error) {
      if (token === listRequest) set({ templates: [], count: 0, error: documentError(error) });
    } finally {
      if (token === listRequest) set({ isLoading: false });
    }
  },

  selectCategory: (slug) => set({ selectedCategory: slug, page: 1 }),
  setSearchQuery: (query) => set({ searchQuery: query, page: 1 }),
}));
