import { api } from './api';
import type { RunArtifact, RunResource } from './applicationRuntime';

export type AnimationAspect = '16:9' | '9:16' | '1:1';
export interface AnimationInput {
  action?: 'generate' | 'export'; prompt: string; aspect: AnimationAspect; duration: number;
  style: string; asset_ids: string[]; source_run_id?: string;
}
export interface AnimationRun extends RunResource { input: AnimationInput & Record<string, unknown>; artifacts: RunArtifact[] }
export interface AnimationGeneration extends AnimationRun { exports: AnimationRun[] }
export interface AnimationAsset { id: string; name: string; mime_type: string; size: number; duration: number | null }
export interface AnimationList { count: number; results: AnimationGeneration[] }
export const animationTerminal = (status: string) => ['succeeded', 'failed', 'cancelled'].includes(status);
export const animationStatus = (status: string, stage = '') => ({
  generating: '正在编排动画', repairing: '正在修复动画', building_preview: '正在构建 HTML 预览',
  rendering: '正在导出 MP4', saving: '正在保存作品',
}[stage] || ({ queued: '排队中', running: '制作中', succeeded: '已完成', failed: '失败', cancelling: '正在取消', cancelled: '已取消', waiting_input: '等待执行权限' } as Record<string, string>)[status] || '处理中');
export const animationArtifact = (run: AnimationRun | undefined, kind: string) => run?.artifacts.find(item => item.kind === kind);
export const completedExport = (generation: AnimationGeneration | undefined) => generation?.exports.find(run => run.status === 'succeeded' && animationArtifact(run, 'animation-video'));
export const activeExport = (generation: AnimationGeneration | undefined) => generation?.exports.find(run => !animationTerminal(run.status));
export function animationError(error: unknown): string {
  const data = (error as { response?: { data?: Record<string, unknown> } })?.response?.data;
  return data ? String(data.detail || Object.values(data).flat().join('；')) : error instanceof Error ? error.message : '操作失败，请稍后重试。';
}
export function animationApi(base: string) {
  return {
    list: (page = 1) => api.get<AnimationList>(`${base}/generations`, { page }),
    get: (id: string) => api.get<AnimationGeneration>(`${base}/generations/${id}`),
    generate: (body: AnimationInput, key: string) => api.post<AnimationGeneration>(`${base}/generations`, body, { headers: { 'Idempotency-Key': key } }),
    export: (id: string, key: string) => api.post<AnimationRun>(`${base}/generations/${id}/exports`, {}, { headers: { 'Idempotency-Key': key } }),
    upload: (file: File) => {
      const data = new FormData(); data.append('file', file);
      return api.post<AnimationAsset>(`${base}/assets`, data, { headers: { 'Content-Type': 'multipart/form-data' } });
    },
  };
}
