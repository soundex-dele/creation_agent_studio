import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '@/services/api';
import { useAppStore } from '../useAppStore';

vi.mock('@/services/api', () => ({
  api: {
    get: vi.fn(),
  },
}));

describe('useAppStore.loadApp', () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
    useAppStore.setState({ apps: [], error: null, isLoading: false, searchQuery: '' });
  });

  it('shares concurrent requests for the same application', async () => {
    let resolveRequest: ((value: any) => void) | undefined;
    vi.mocked(api.get).mockImplementation(() => new Promise((resolve) => {
      resolveRequest = resolve;
    }));

    const first = useAppStore.getState().loadApp('writing-assistant');
    const second = useAppStore.getState().loadApp('writing-assistant');

    expect(api.get).toHaveBeenCalledTimes(1);
    resolveRequest?.({
      id: 1,
      slug: 'writing-assistant',
      name: '写作助手',
    });

    await expect(first).resolves.toMatchObject({ id: 'writing-assistant' });
    await expect(second).resolves.toMatchObject({ id: 'writing-assistant' });
  });
});

describe('useAppStore.loadApps', () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
    useAppStore.setState({ apps: [], error: null, isLoading: false, searchQuery: '' });
  });

  it('includes applications beyond the first 20 results', async () => {
    const firstPage = Array.from({ length: 20 }, (_, index) => ({
      id: index + 1, slug: `app-${index}`, name: `App ${index}`,
      description: '', category_slug: 'productivity',
    }));
    vi.mocked(api.get)
      .mockResolvedValueOnce({ results: firstPage, next: 'http://backend:8080/api/v1/apps/?page=2' })
      .mockResolvedValueOnce({ results: [{
        id: 21, slug: 'my-computer', name: '我的电脑', description: '连接电脑',
        category_slug: 'productivity', renderer_key: 'my-computer',
      }], next: null });

    await useAppStore.getState().loadApps();

    expect(api.get).toHaveBeenNthCalledWith(2, '/apps/', { page: 2 });
    expect(useAppStore.getState().apps).toHaveLength(21);
    expect(useAppStore.getState().apps[20]).toMatchObject({
      id: 'my-computer', rendererKey: 'my-computer',
    });
  });

  it('preserves category and search parameters across pages', async () => {
    useAppStore.setState({ searchQuery: '电脑' });
    vi.mocked(api.get)
      .mockResolvedValueOnce({ results: [], next: '?page=2' })
      .mockResolvedValueOnce({ results: [{
        id: 21, slug: 'my-computer', name: '我的电脑', description: '连接电脑',
        category_slug: 'productivity',
      }], next: null });

    await useAppStore.getState().loadApps('productivity');

    expect(api.get).toHaveBeenNthCalledWith(1, '/apps/', { category: 'productivity', search: '电脑' });
    expect(api.get).toHaveBeenNthCalledWith(2, '/apps/', { category: 'productivity', search: '电脑', page: 2 });
    expect(useAppStore.getState().apps).toHaveLength(1);
  });

  it('exposes a recoverable error and clears it after a successful retry', async () => {
    vi.mocked(api.get).mockRejectedValueOnce({ response: { data: { detail: '服务暂不可用' } } });

    await useAppStore.getState().loadApps();

    expect(useAppStore.getState()).toMatchObject({
      apps: [],
      error: '服务暂不可用',
      isLoading: false,
    });

    vi.mocked(api.get).mockResolvedValueOnce([{
      id: 7,
      slug: 'writing-assistant',
      name: '写作助手',
      description: '帮助完成写作任务',
      category_slug: 'creative',
      tags: ['写作'],
    }]);

    await useAppStore.getState().loadApps();

    expect(useAppStore.getState().error).toBeNull();
    expect(useAppStore.getState().apps).toHaveLength(1);
  });
});
