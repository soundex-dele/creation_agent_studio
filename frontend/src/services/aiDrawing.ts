import { api } from './api';
import type { RunArtifact, RunResource } from './applicationRuntime';

export type DrawingOrientation = 'auto' | 'square' | 'landscape' | 'portrait';
export interface DrawingInput {
  prompt: string;
  orientation: DrawingOrientation;
  reference_id?: string;
  source_artifact_id?: string;
}
export interface DrawingRun extends RunResource { input: DrawingInput & Record<string, unknown>; artifacts: RunArtifact[] }
export interface DrawingPage { count: number; results: DrawingRun[] }
export interface DrawingReference { id: string; width: number; height: number; size: number; mime_type: string }
export const drawingTerminal = (status: string) => ['succeeded', 'failed', 'cancelled'].includes(status);
export function drawingStatus(status: string, stage = '') {
  if (status === 'running' && stage === 'saving') return '正在保存图片';
  return ({ queued: '排队中', running: '正在生成图片', cancelling: '正在取消', cancelled: '已取消', succeeded: '已完成', failed: '生成失败', waiting_input: '需要处理执行权限' } as Record<string, string>)[status] || '处理中';
}
export function drawingError(error: unknown): string {
  const data = (error as { response?: { data?: Record<string, unknown> } })?.response?.data;
  if (data) return String(data.detail || Object.values(data).flat().join('；'));
  return error instanceof Error ? error.message : '操作失败，请稍后重试。';
}
export function drawingApi(base: string) {
  return {
    list: (page = 1) => api.get<DrawingPage>(`${base}/generations`, { page }),
    get: (id: string) => api.get<DrawingRun>(`${base}/generations/${id}`),
    generate: (body: DrawingInput, key: string) => api.post<DrawingRun>(`${base}/generations`, body, { headers: { 'Idempotency-Key': key } }),
    upload: (file: File) => {
      const form = new FormData(); form.append('file', file);
      return api.post<DrawingReference>(`${base}/references`, form, { headers: { 'Content-Type': 'multipart/form-data' } });
    },
    referenceContent: (id: string) => api.get<Blob>(`${base}/references/${id}/content`, undefined, { responseType: 'blob' }),
  };
}

export async function downloadDrawing(url: string, name: string) {
  const response = await fetch(url);
  if (!response.ok) throw new Error('图片下载失败，请重新打开作品后重试。');
  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = objectUrl; link.download = name; link.click();
  setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
}
