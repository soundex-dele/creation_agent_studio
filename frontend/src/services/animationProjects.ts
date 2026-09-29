import { api } from './api';
import type { AnimationAspect, AnimationAsset, AnimationGeneration, AnimationRun } from './animationStudio';

export interface SceneStyle { color: string; background: string; font: string }
export interface StudioScene { id: string; title: string; body: string; narration: string; description: string; frames: number; assets: string[]; locked: boolean; style: SceneStyle; source: string }
export interface AudioTrack { asset_id: string; role: 'narration' | 'music' | 'effect'; scene_id?: string; start: number; frames: number; trim_start?: number; volume: number; loop?: boolean; fade_in?: number; fade_out?: number }
export interface Subtitle { start: number; end: number; text: string }
export interface Brand extends Partial<SceneStyle> { logo?: string; ending?: string }
export interface StudioDocument { note?: string; schema_version: number; prompt: string; aspect: AnimationAspect; style: string; scenes: StudioScene[]; audio: AudioTrack[]; subtitles: Subtitle[]; subtitle_style: { enabled: boolean; font: string; size: number; color: string; position: 'top' | 'center' | 'bottom' }; brand: Brand; source_run_id?: string }
export interface StudioVersion { id: string; note: string; document: StudioDocument; created_at: string; run: AnimationGeneration }
export interface StudioProject { id: string; title: string; archived: boolean; revision: number; updated_at: string; draft: StudioDocument; versions?: StudioVersion[]; tasks?: AnimationRun[] }
export interface TemplateField { name: string; scene_id: string; property: 'title' | 'body' | 'narration' | 'assets'; type: 'text' | 'number' | 'image' }
export interface StudioPreset { id: string; name: string; kind: 'template' | 'brand'; builtin: boolean; data: { document?: StudioDocument; fields?: TemplateField[] } & Brand }
export interface LibraryAsset extends AnimationAsset { category: string; archived: boolean }
export interface SpeechConfig { enabled: boolean; app_id: string; resource_id: string; secret_ref: string; voices: { id: string; name: string }[] }
export interface ExportOptions { format: 'mp4' | 'gif' | 'png' | 'srt' | 'vtt'; resolution: 720 | 1080; quality: 'standard' | 'high'; cover_frame: number; scene_id?: string }
export interface BatchRow { index: number; title: string; project_id?: string; status: string; error?: string }
export interface StudioBatch { id: string; rows: BatchRow[]; run: AnimationRun }
export interface ImportedSheet { name: string; columns: string[]; rows: Record<string, string>[] }
export const newDocument = (): StudioDocument => ({ schema_version: 2, prompt: '', aspect: '16:9', style: '简洁清晰', scenes: [], audio: [], subtitles: [], subtitle_style: { enabled: true, font: 'Noto Sans SC', size: 40, color: '#ffffff', position: 'bottom' }, brand: {} });
export const newScene = (): StudioScene => ({ id: crypto.randomUUID(), title: '新场景', body: '', narration: '', description: '', frames: 300, assets: [], locked: false, style: { color: '#4f46e5', background: '#ffffff', font: 'Noto Sans SC' }, source: '' });
export const defaultExport: ExportOptions = { format: 'mp4', resolution: 1080, quality: 'standard', cover_frame: 0 };
export function withScenes(document: StudioDocument, scenes: StudioScene[]): StudioDocument {
  const offsets = (items: StudioScene[]) => { let cursor = 0; return items.map(s => { const item = { id: s.id, start: cursor, end: cursor + s.frames }; cursor += s.frames; return item; }); };
  const old = offsets(document.scenes); const next = offsets(scenes);
  const subtitles = document.subtitles.flatMap(sub => {
    const owner = old.find(s => sub.start >= s.start && sub.start < s.end);
    const target = next.find(s => s.id === owner?.id);
    if (!owner || !target) return [];
    const start = target.start + sub.start - owner.start;
    const end = Math.min(target.end, target.start + sub.end - owner.start);
    return start < end ? [{ ...sub, start, end }] : [];
  });
  return { ...document, scenes, subtitles, audio: document.audio.filter(t => !t.scene_id || scenes.some(s => s.id === t.scene_id)) };
}
export const projectApi = (base: string) => ({
  list: (q = '', archived = false, page = 1) => api.get<{ count: number; results: StudioProject[] }>(`${base}/projects`, { q, archived: archived ? '1' : '0', page }),
  get: (id: string) => api.get<StudioProject>(`${base}/projects/${id}`),
  create: (draft = newDocument(), title = '未命名作品') => api.post<StudioProject>(`${base}/projects`, { draft, title }),
  update: (id: string, data: { title?: string; archived?: boolean }) => api.patch<StudioProject>(`${base}/projects/${id}`, data),
  save: (id: string, revision: number, document: StudioDocument) => api.put<StudioProject>(`${base}/projects/${id}/draft`, { revision, document }),
  action: (id: string, operation: string, data = {}) => api.post<StudioProject>(`${base}/projects/${id}/${operation}`, data),
  task: (id: string, body: Record<string, unknown>, key: string) => api.post<AnimationRun>(`${base}/projects/${id}/tasks`, body, { headers: { 'Idempotency-Key': key } }),
  presets: () => api.get<{ results: StudioPreset[]; fonts: string[] }>(`${base}/presets`),
  preset: (body: Record<string, unknown>) => api.post<StudioPreset>(`${base}/presets`, body),
  assets: (archived = false) => api.get<{ results: LibraryAsset[] }>(`${base}/assets`, { archived: archived ? '1' : '0' }),
  asset: (id: string, body: Record<string, unknown>) => api.patch(`${base}/assets/${id}`, body),
  assetBlob: (id: string) => api.get<Blob>(`${base}/assets/${id}`, undefined, { responseType: 'blob' }),
  speech: () => api.get<SpeechConfig>(`${base}/speech-config`),
  saveSpeech: (body: SpeechConfig) => api.put<SpeechConfig>(`${base}/speech-config`, body),
  export: (id: string, options: ExportOptions, key: string) => api.post<AnimationRun>(`${base}/generations/${id}/exports`, options, { headers: { 'Idempotency-Key': key } }),
  import: (file: File) => { const data = new FormData(); data.append('file', file); return api.post<{ sheets: ImportedSheet[] }>(`${base}/batches/import`, data); },
  batch: (body: Record<string, unknown>, key: string) => api.post<{ id: string; run: AnimationRun }>(`${base}/batches`, body, { headers: { 'Idempotency-Key': key } }),
  batches: () => api.get<{ results: { id: string; status: string; count: number }[] }>(`${base}/batches`),
  getBatch: (id: string) => api.get<StudioBatch>(`${base}/batches/${id}`),
  batchAction: (id: string, operation: string, key: string) => api.post<{ id: string }>(`${base}/batches/${id}`, { operation }, { headers: { 'Idempotency-Key': key } }),
});
export type ProjectClient = ReturnType<typeof projectApi>;
