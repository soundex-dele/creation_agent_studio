import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '@/services/api';
import { useOrganizationStore, type Organization } from '../useOrganizationStore';

vi.mock('@/services/api', () => ({
  api: {
    get: vi.fn(),
  },
}));

describe('useOrganizationStore.loadOrganizations', () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
    useOrganizationStore.getState().reset();
  });

  it('replaces a stale persisted organization with the first accessible one', async () => {
    useOrganizationStore.setState({ currentOrganizationId: 'stale-organization' });
    vi.mocked(api.get).mockResolvedValue({
      single_tenant_mode: false,
      organizations: [
        { id: 'current-organization', name: 'Current', slug: 'current', role: 'owner' },
      ],
    });

    await useOrganizationStore.getState().loadOrganizations('user-2');

    expect(useOrganizationStore.getState()).toMatchObject({
      currentOrganizationId: 'current-organization',
      loadedForUserId: 'user-2',
      isLoading: false,
      loadError: null,
    });
  });

  it('keeps a selected organization when it is still accessible', async () => {
    useOrganizationStore.setState({ currentOrganizationId: 'selected-organization' });
    vi.mocked(api.get).mockResolvedValue({
      single_tenant_mode: false,
      organizations: [
        { id: 'first-organization', name: 'First', slug: 'first', role: 'viewer' },
        { id: 'selected-organization', name: 'Selected', slug: 'selected', role: 'owner' },
      ],
    });

    await useOrganizationStore.getState().loadOrganizations('user-2');

    expect(useOrganizationStore.getState().currentOrganizationId)
      .toBe('selected-organization');
  });

  it('always selects the server organization in single-tenant mode', async () => {
    useOrganizationStore.setState({ currentOrganizationId: 'untrusted-organization' });
    vi.mocked(api.get).mockResolvedValue({
      single_tenant_mode: true,
      organizations: [
        { id: 'enterprise', name: 'Enterprise', slug: 'enterprise', role: 'viewer' },
      ],
    });

    await useOrganizationStore.getState().loadOrganizations('user-2');

    expect(useOrganizationStore.getState()).toMatchObject({
      currentOrganizationId: 'enterprise',
      singleTenantMode: true,
    });
    useOrganizationStore.getState().selectOrganization('untrusted-organization');
    expect(useOrganizationStore.getState().currentOrganizationId).toBe('enterprise');
  });

  it('does not start a second request while organizations are loading', async () => {
    let resolveRequest: ((context: {
      single_tenant_mode: boolean;
      organizations: Organization[];
    }) => void) | undefined;
    vi.mocked(api.get).mockImplementation(() => new Promise((resolve) => {
      resolveRequest = resolve;
    }));

    const first = useOrganizationStore.getState().loadOrganizations('user-2');
    await useOrganizationStore.getState().loadOrganizations('user-2');

    expect(api.get).toHaveBeenCalledTimes(1);
    resolveRequest?.({ single_tenant_mode: false, organizations: [] });
    await first;
  });
});
