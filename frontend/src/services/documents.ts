import type { JSONContent } from '@tiptap/core';
import { api } from './api';

export interface OnlineDocument {
  id: string; title: string; content: JSONContent; plain_text: string; version: number;
  owner: number; owner_name: string; permission: 'owner' | 'editor' | 'viewer';
  created_at: string; updated_at: string;
}
export type DocumentSummary = Omit<OnlineDocument, 'content'>;
export interface DocumentPage { count: number; results: DocumentSummary[] }
export interface DocumentMember { user_id: number; user__username: string }
export interface DocumentShare extends DocumentMember { role: 'viewer' | 'editor' }
export type DocumentBody = Pick<OnlineDocument, 'title' | 'content'>;
export interface DocumentAIContext { version: number; selection: string; selection_from: number; selection_to: number }

export function documentError(error: unknown): string {
  const data = (error as { response?: { data?: Record<string, unknown> } })?.response?.data;
  if (data) return Object.values(data).map((value) => Array.isArray(value) ? value.join('；') : String(value)).join('；');
  return error instanceof Error ? error.message : '操作失败，请稍后重试。';
}
export function documentsApi(base: string) {
  return {
    list: (scope: string, search: string, page: number, signal?: AbortSignal) => api.get<DocumentPage>(base, { scope, search, page }, { signal }),
    get: (id: string) => api.get<OnlineDocument>(`${base}/${id}`),
    create: () => api.post<OnlineDocument>(base, { title: '未命名文档' }),
    save: (id: string, body: DocumentBody, version: number) => api.patch<OnlineDocument>(`${base}/${id}`, { ...body, version }),
    copy: (id: string, body?: DocumentBody) => api.post<OnlineDocument>(`${base}/${id}/copy`, body),
    remove: (id: string) => api.delete(`${base}/${id}`),
    members: (search = '') => api.get<DocumentMember[]>(`${base}/members`, { search }),
    shares: (id: string) => api.get<DocumentShare[]>(`${base}/${id}/shares`),
    grant: (id: string, user_id: number, role: string) => api.post(`${base}/${id}/shares`, { user_id, role }),
    revoke: (id: string, userId: number) => api.delete(`${base}/${id}/shares?user_id=${userId}`),
  };
}

export function downloadText(title: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/plain;charset=utf-8' }));
  const link = document.createElement('a');
  const filename = [...title].map((char) => char.charCodeAt(0) < 32 || '<>:"/\\|?*'.includes(char) ? '_' : char).join('');
  link.href = url; link.download = `${filename || '未命名文档'}.txt`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
