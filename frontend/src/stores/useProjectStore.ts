import { create } from 'zustand';
import { api } from '@/services/api';

export interface Project {
  id: number;
  title: string;
  description: string;
  status: string;
  thumbnail: string;
  application_id?: number | null;
  application_slug?: string | null;
  application_kind?: string | null;
  conversation_id?: number | null;
  working_directory?: string;
  source?: 'application' | 'workflow';
  created_at: string;
  updated_at: string;
}

interface ProjectState {
  projects: Project[];
  currentProject: any;
  isLoading: boolean;
  loadProjects: () => Promise<void>;
  loadProject: (id: number) => Promise<void>;
  createProject: (data: any) => Promise<Project>;
  updateProject: (id: number, data: any) => Promise<void>;
  deleteProject: (id: number) => Promise<void>;
}

export const useProjectStore = create<ProjectState>((set, get) => ({
  projects: [],
  currentProject: null,
  isLoading: false,

  loadProjects: async () => {
    try {
      set({ isLoading: true });
      const response = await api.get<any>('/projects/');
      set({ projects: Array.isArray(response) ? response : response.results ?? [] });
    } catch (error) {
      console.error('Failed to load projects:', error);
    } finally {
      set({ isLoading: false });
    }
  },

  loadProject: async (id: number) => {
    try {
      set({ isLoading: true });
      const response = await api.get<Project>(`/projects/${id}/`);
      set({ currentProject: response });
    } catch (error) {
      console.error('Failed to load project:', error);
    } finally {
      set({ isLoading: false });
    }
  },

  createProject: async (data) => {
    try {
      const response = await api.post<Project>('/projects/', data);
      const { projects } = get();
      set({ projects: [response, ...projects] });
      return response;
    } catch (error) {
      console.error('Failed to create project:', error);
      throw error;
    }
  },

  updateProject: async (id: number, data) => {
    try {
      await api.put(`/projects/${id}/`, data);
      await get().loadProjects();
    } catch (error) {
      console.error('Failed to update project:', error);
      throw error;
    }
  },

  deleteProject: async (id: number) => {
    try {
      await api.delete(`/projects/${id}/`);
      const { projects, currentProject } = get();
      set({
        projects: projects.filter(p => p.id !== id),
        currentProject: currentProject?.id === id ? null : currentProject,
      });
    } catch (error) {
      console.error('Failed to delete project:', error);
      throw error;
    }
  },
}));
