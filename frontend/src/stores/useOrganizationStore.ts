import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { api } from '@/services/api';

export interface Organization {
  id: string;
  name: string;
  slug: string;
  role: string;
}

interface OrganizationState {
  organizations: Organization[];
  currentOrganizationId: string | null;
  loadedForUserId: string | null;
  isLoading: boolean;
  loadError: string | null;
  loadOrganizations: (userId?: string | null) => Promise<void>;
  selectOrganization: (id: string) => void;
  reset: () => void;
}

export const useOrganizationStore = create<OrganizationState>()(
  persist(
    (set, get) => ({
      organizations: [],
      currentOrganizationId: null,
      loadedForUserId: null,
      isLoading: false,
      loadError: null,
      loadOrganizations: async (userId = get().loadedForUserId) => {
        if (get().isLoading) return;
        set({ isLoading: true, loadError: null });
        try {
          const response = await api.get<Organization[] | { results: Organization[] }>(
            '/enterprise/organizations/'
          );
          const organizations = Array.isArray(response) ? response : response.results;
          const selected = get().currentOrganizationId;
          set({
            organizations,
            currentOrganizationId: organizations.some((item) => item.id === selected)
              ? selected
              : organizations[0]?.id ?? null,
            loadedForUserId: userId ?? null,
            isLoading: false,
          });
        } catch (error) {
          set({
            isLoading: false,
            loadError: error instanceof Error ? error.message : '无法加载组织工作区',
          });
          throw error;
        }
      },
      selectOrganization: (id) => set({ currentOrganizationId: id }),
      reset: () => set({
        organizations: [],
        currentOrganizationId: null,
        loadedForUserId: null,
        isLoading: false,
        loadError: null,
      }),
    }),
    {
      name: 'organization-storage',
      partialize: (state) => ({
        organizations: state.organizations,
        currentOrganizationId: state.currentOrganizationId,
      }),
    }
  )
);
