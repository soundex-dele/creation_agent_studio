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

    const first = useAppStore.getState().loadApp('wechat-article-writer');
    const second = useAppStore.getState().loadApp('wechat-article-writer');

    expect(api.get).toHaveBeenCalledTimes(1);
    resolveRequest?.({
      id: 1,
      slug: 'wechat-article-writer',
      name: '微信公众号文章生成',
    });

    await expect(first).resolves.toMatchObject({ id: 'wechat-article-writer' });
    await expect(second).resolves.toMatchObject({ id: 'wechat-article-writer' });
  });
});

describe('useAppStore.loadApps', () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
    useAppStore.setState({ apps: [], error: null, isLoading: false, searchQuery: '' });
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
