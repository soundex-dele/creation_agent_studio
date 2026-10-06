import { api } from './api';

/** Scope every resource request without changing run streaming or other apps. */
export function createCoworkApi(conversationScope: 'cowork' | 'unified' = 'cowork'): typeof api {
  const scoped = (path: string) => {
    const resource = path.match(/^\/(conversations|projects)\//)?.[1];
    if (!resource) return path;
    const [pathname, query] = path.split('?');
    const params = new URLSearchParams(query);
    params.set('scope', resource === 'conversations' ? conversationScope : 'cowork');
    return `${pathname}?${params}`;
  };
  return {
    get: (path, params, config) => api.get(scoped(path), params, config),
    post: (path, data, config) => api.post(scoped(path),
      path === '/conversations/' || path === '/projects/'
        ? { ...(data as Record<string, unknown>), scope: 'cowork' } : data, config),
    put: (path, data, config) => api.put(scoped(path), data, config),
    patch: (path, data, config) => api.patch(scoped(path), data, config),
    delete: (path, config) => api.delete(scoped(path), config),
  };
}

/** Unified history, with folder-project semantics for newly created chats. */
export const createUnifiedChatApi = () => createCoworkApi('unified');

export function coworkError(error: unknown, fallback: string): string {
  const data = (error as { response?: { data?: Record<string, unknown> } })?.response?.data;
  if (data) {
    for (const key of ['detail', 'working_directory', 'title', 'non_field_errors']) {
      const value = data[key];
      if (typeof value === 'string') return value;
      if (Array.isArray(value)) return value.join(' ');
    }
  }
  return fallback;
}
