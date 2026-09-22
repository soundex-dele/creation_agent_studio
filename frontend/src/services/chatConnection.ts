import { api, type ApiRequestConfig } from './api';
import { createIdempotencyKey } from '@/lib/idempotencyKey';

export interface RemoteConnection {
  deviceId: string;
}

export function remotePath(connection: RemoteConnection, path: string): string {
  if (!path.startsWith('/') || path.startsWith('//') || path.includes('://')) {
    throw new Error('Remote requests require an API-relative path');
  }
  return `/remote/devices/${encodeURIComponent(connection.deviceId)}/proxy${path}`;
}

export async function loadConnectionCollection<T>(client: typeof api, path: string, params: Record<string, unknown> = {}): Promise<T[]> {
  const result: T[] = [];
  for (let page = 1; ; page += 1) {
    const response = await client.get<T[] | { results: T[]; next: string | null }>(path, { ...params, page });
    if (Array.isArray(response)) return response;
    result.push(...response.results);
    if (!response.next || !response.results.length) return result;
    // Never follow an absolute pagination URL from another deployment.
  }
}

/** Each instance captures its computer. No global transport or tenant mutation. */
export function createConnectionApi(connection: RemoteConnection): typeof api {
  const uncertainRequests = new Map<string, string>();
  const retry = async <T,>(send: () => Promise<T>): Promise<T> => {
    for (let attempt = 0; ; attempt += 1) {
      try { return await send(); } catch (error) {
        const status = (error as { response?: { status?: number } }).response?.status;
        if (attempt >= 2 || (status && ![502, 503, 504].includes(status))) throw error;
        await new Promise(resolve => setTimeout(resolve, 300 * (attempt + 1)));
      }
    }
  };
  return {
    get: (path, params, config) => api.get(remotePath(connection, path), params, { ...config, timeout: 25000 }),
    post: async <T,>(path: string, data?: unknown, config?: ApiRequestConfig): Promise<T> => {
      const payload = data as Record<string, unknown> | undefined;
      const command = path.endsWith('/commands');
      const fingerprint = JSON.stringify([path, command ? { ...payload, idempotency_key: undefined } : payload]);
      const key = uncertainRequests.get(fingerprint)
        || String((command ? payload?.idempotency_key : (config?.headers as Record<string, string>)?.['Idempotency-Key'])
          || createIdempotencyKey('remote'));
      uncertainRequests.set(fingerprint, key);
      const result = await retry(() => api.post<T>(
        remotePath(connection, path), command ? { ...payload, idempotency_key: key } : data,
        { ...config, headers: { ...config?.headers, 'Idempotency-Key': key }, timeout: 25000 },
      ));
      uncertainRequests.delete(fingerprint);
      return result;
    },
    put: (path, data, config) => api.put(remotePath(connection, path), data, config),
    patch: (path, data, config) => api.patch(remotePath(connection, path), data, config),
    delete: (path, config) => api.delete(remotePath(connection, path), config),
  };
}
