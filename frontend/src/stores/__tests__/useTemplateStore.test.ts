import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '@/services/api';
import { useTemplateStore } from '../useTemplateStore';

vi.mock('@/services/api', () => ({ api: { get: vi.fn() } }));
beforeEach(() => {
  vi.clearAllMocks();
  useTemplateStore.getState().clearTemplates();
  useTemplateStore.getState().clearCurrentTemplate();
  useTemplateStore.setState({ page: 1, mine: false, sourceKind: '', searchQuery: '', selectedCategory: null });
});

describe('Case library state', () => {
  it('sends real search/filter/page parameters and preserves server totals', async () => {
    vi.mocked(api.get).mockResolvedValue({ count: 47, results: [{ id: 1 }] });
    useTemplateStore.setState({ page: 2, mine: true, sourceKind: 'douyin', searchQuery: '科普' });
    await useTemplateStore.getState().loadTemplates();
    expect(api.get).toHaveBeenCalledWith('/templates/', { page: 2, mine: true, source_kind: 'douyin', search: '科普' });
    expect(useTemplateStore.getState().count).toBe(47);
    useTemplateStore.getState().setSourceKind('');
    expect(useTemplateStore.getState().page).toBe(1);
  });
  it('shows request errors and can retry', async () => {
    vi.mocked(api.get).mockRejectedValueOnce(new Error('Network Error')).mockResolvedValue({ count: 0, results: [] });
    await useTemplateStore.getState().loadTemplates();
    expect(useTemplateStore.getState().error).toContain('Network Error');
    await useTemplateStore.getState().loadTemplates();
    expect(useTemplateStore.getState().error).toBe('');
  });
  it('does not let a stale response replace newer results', async () => {
    let resolve!: (data: unknown) => void;
    vi.mocked(api.get).mockImplementationOnce(() => new Promise(done => { resolve = done; })).mockResolvedValueOnce({ count: 1, results: [{ id: 2 }] });
    const first = useTemplateStore.getState().loadTemplates();
    await useTemplateStore.getState().loadTemplates();
    resolve({ count: 1, results: [{ id: 1 }] }); await first;
    expect(useTemplateStore.getState().templates[0].id).toBe(2);
  });
  it('discards in-flight private results when leaving the page or changing organization', async () => {
    let resolve!: (data: unknown) => void;
    vi.mocked(api.get).mockImplementationOnce(() => new Promise(done => { resolve = done; }));
    const first = useTemplateStore.getState().loadTemplates();
    useTemplateStore.getState().clearTemplates();
    resolve({ count: 1, results: [{ id: 1 }] }); await first;
    expect(useTemplateStore.getState().templates).toEqual([]);
  });
});
