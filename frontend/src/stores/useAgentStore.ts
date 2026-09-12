import { create } from 'zustand';
import { api } from '@/services/api';
import type { RunResource } from '@/services/applicationRuntime';

interface AgentCategory {
  id: number;
  name: string;
  slug: string;
  description: string;
  icon: string;
  agent_count: number;
}

export interface Agent {
  id: number;
  name: string;
  slug: string;
  description: string;
  icon: string;
  category_name: string;
  is_public: boolean;
  can_edit: boolean;
  can_delete: boolean;
  created_at: string;
}

interface AgentState {
  categories: AgentCategory[];
  agents: Agent[];
  selectedCategory: string | null;
  searchQuery: string;
  executions: RunResource[];
  isLoading: boolean;
  loadCategories: () => Promise<void>;
  loadAgents: (category?: string) => Promise<void>;
  selectCategory: (slug: string | null) => void;
  setSearchQuery: (query: string) => void;
  executeAgent: (agentId: number, inputData: any) => Promise<RunResource>;
  loadMyExecutions: () => Promise<void>;
}

export const useAgentStore = create<AgentState>((set, get) => ({
  categories: [],
  agents: [],
  selectedCategory: null,
  searchQuery: '',
  executions: [],
  isLoading: false,

  loadCategories: async () => {
    try {
      const response = await api.get<any>('/agents/categories/');
      set({ categories: Array.isArray(response) ? response : response.results ?? [] });
    } catch (error) {
      console.error('Failed to load categories:', error);
    }
  },

  loadAgents: async (category?: string) => {
    try {
      set({ isLoading: true });
      const { searchQuery } = get();
      const params: any = {};
      if (category) params.category = category;
      if (searchQuery) params.search = searchQuery;
      const response = await api.get<any>('/agents/', params);
      set({ agents: Array.isArray(response) ? response : response.results ?? [] });
    } catch (error) {
      console.error('Failed to load agents:', error);
    } finally {
      set({ isLoading: false });
    }
  },

  selectCategory: (slug: string | null) => {
    set({ selectedCategory: slug });
  },

  setSearchQuery: (query: string) => {
    set({ searchQuery: query });
  },

  executeAgent: async (agentId: number, inputData: any) => {
    try {
      const response = await api.post<RunResource>(`/agents/${agentId}/execute/`, {
        input_data: inputData,
      });
      return response;
    } catch (error) {
      console.error('Failed to execute agent:', error);
      throw error;
    }
  },

  loadMyExecutions: async () => {
    try {
      const response = await api.get<any>('/agents/my_executions/');
      set({ executions: Array.isArray(response) ? response : response.results ?? [] });
    } catch (error) {
      console.error('Failed to load executions:', error);
    }
  },
}));
