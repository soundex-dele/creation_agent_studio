import { api } from '@platform/http';
import type { RunArtifact, RunResource } from '@platform/runtime';

export interface FetchRun extends RunResource { input: { url: string }; artifacts: RunArtifact[] }
export interface FetchHistory { count: number; results: FetchRun[] }
export interface WebDocument {
  version: number; requestedUrl: string; url: string; title: string | null; author: string | null;
  publishedAt: string | null; siteName: string | null; summary: string | null; canonicalUrl: string | null;
  language: string | null; capturedAt: string; adapter: string; extractionMethod: string; markdown: string;
  media: { type: string; url: string; alt: string | null }[]; warnings: string[];
}
export const terminal = (status: string) => ['succeeded', 'failed', 'cancelled'].includes(status);
export function statusLabel(status: string, stage = '') {
  const stages: Record<string, string> = { starting: '正在启动浏览器', loading: '正在加载网页', rendering: '正在等待页面内容', extracting: '正在提取正文', saving: '正在保存结果' };
  return (status === 'running' && stages[stage]) || ({ queued: '排队中', running: '正在抓取', cancelling: '正在取消', cancelled: '已取消', succeeded: '已完成', failed: '抓取失败', waiting_input: '等待处理' } as Record<string, string>)[status] || '处理中';
}
export function errorMessage(error: unknown) {
  const data = (error as { response?: { data?: Record<string, unknown> } })?.response?.data;
  if (typeof Blob !== 'undefined' && data instanceof Blob) return '结果文件读取失败，请刷新后重试。';
  return (data ? String(data.detail || Object.values(data).flat().join('；')) : error instanceof Error ? error.message : '') || '操作失败，请稍后重试。';
}
export function fetchApi(base: string) {
  return {
    list: (page = 1) => api.get<FetchHistory>(`${base}/runs`, { page }),
    get: (id: string) => api.get<FetchRun>(`${base}/runs/${id}`),
    start: (url: string, key: string) => api.post<FetchRun>(`${base}/runs`, { url }, { headers: { 'Idempotency-Key': key } }),
  };
}
export function safeLink(value: string) {
  try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password ? url.href : ''; }
  catch { return ''; }
}
export interface ArtifactAccess { url: string; content_path?: string | null }
async function artifactBlob(access: ArtifactAccess, signal?: AbortSignal): Promise<Blob> {
  // Policy-protected artifacts require current authentication as well as their
  // signed URL. Only platform-relative paths may receive the auth transport.
  if (access.content_path?.startsWith('/api/v1/organizations/')) {
    return api.get<Blob>(access.content_path.slice('/api/v1'.length), undefined, { responseType: 'blob', signal });
  }
  const response = await fetch(access.url, { signal });
  if (!response.ok) throw new Error('结果读取失败，请重新加载。');
  return response.blob();
}
export async function readDocument(access: ArtifactAccess, signal?: AbortSignal): Promise<WebDocument> {
  const data = JSON.parse(await (await artifactBlob(access, signal)).text());
  if (data.version !== 1 || typeof data.markdown !== 'string' || !Array.isArray(data.media) || !Array.isArray(data.warnings)) throw new Error('结果格式无效，请重新抓取。');
  return data;
}
export async function downloadArtifact(access: ArtifactAccess, filename: string) {
  const objectUrl = URL.createObjectURL(await artifactBlob(access));
  const link = document.createElement('a'); link.href = objectUrl; link.download = filename;
  link.click(); setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
}
