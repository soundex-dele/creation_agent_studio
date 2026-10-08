import { createIdempotencyKey } from '@/lib/idempotencyKey';
import { api } from './api';

/** Keep uncertain submissions retryable for the lifetime of this tenant's client. */
export function createDouyinSubmitter() {
  const pending = new Map<string, { payload: string; key: string }>();
  return async <T>(url: string, body: unknown): Promise<T> => {
    const payload = JSON.stringify(body);
    let request = pending.get(url);
    if (!request || request.payload !== payload) {
      request = { payload, key: createIdempotencyKey('douyin') };
      pending.set(url, request);
    }
    const result = await api.post<T>(url, body, { headers: { 'Idempotency-Key': request.key } });
    // An older response must not discard a newer submission's retry key.
    if (pending.get(url) === request) pending.delete(url);
    return result;
  };
}
