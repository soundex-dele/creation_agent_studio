import { api } from './api';
import { streamRunEvents, type RunStreamOptions } from './runStream';

export type Data = Record<string, unknown>;
export type Resource = 'properties' | 'personas' | 'leads' | 'followups' | 'viewings' | 'contents' | 'publications';
export interface CopyBody { titles: string[]; cover: string; body: string; tags: string[]; pages: { photo_ref: string; caption: string; layout: string }[]; script: string; shots: string[]; checks: string[] }
export interface Version { id: string; content_id: string; number: number; body: CopyBody; snapshot: { content?: Data; properties?: RentalRecord[] }; created_at: string }
export interface RentalRecord { id: string; title: string; status: string; archived: boolean; revision: number; data: Data; created_at: string; updated_at: string; lead_id?: string; version_id?: string; latest_version?: Version | null; changes?: string[]; duplicates?: { id: string; title: string }[] }
export interface Task { id: string; kind: string; status: string; error: string; applied: boolean; run_id?: string | null; organization_id?: string; request: Data; result: { body?: CopyBody; content_id?: string; requirements?: Data; answer?: string; questions?: string[]; publication_ids?: string[]; topics?: { title: string; date: string; angle: string }[] }; created_at: string }
export interface Event { id: string; kind: string; title: string; date: string; status: string; active: boolean; actionable: boolean; changes: string[]; overdue: boolean; record: RentalRecord; lead_title?: string }
export interface Overview { today: string; events: Event[]; attention?: (RentalRecord & { gaps: string[] })[]; property_count?: number }
export interface Counts { leads: number; viewed: number; won: number; viewing_rate: number | null; deal_rate: number | null }
export interface Report { summary: Counts; unknown: Counts; note: string; as_of: string; publications: (Counts & { id: string; title: string; platform: string; content_type: string; persona_id: string | null; property_ids: string[]; metrics: Record<string, number | null>; metrics_at: string | null })[]; groups: Record<string, (Counts & { key: string })[]> }
export interface Preferences { timezone: string; voice: string; platform: string }
export interface MatchItem { property: RentalRecord; reasons: string[]; unknown: string[]; conflicts: string[] }
export type Matches = Record<'matched' | 'unknown' | 'conflicts', MatchItem[]>;
export type Library = Record<Resource, RentalRecord[]>;
export const resources: Resource[] = ['properties', 'personas', 'leads', 'followups', 'viewings', 'contents', 'publications'];
export const emptyLibrary = (): Library => Object.fromEntries(resources.map(key => [key, []])) as unknown as Library;
export const string = (value: unknown) => value == null ? '' : String(value);
export const strings = (value: unknown): string[] => Array.isArray(value) ? value.map(String) : [];
export const activeTask = (task: Task) => ['queued', 'running', 'waiting_input', 'waiting_children', 'cancelling'].includes(task.status);

export function subscribeRentalTask(task: Pick<Task, 'run_id' | 'organization_id'>, callbacks: Pick<RunStreamOptions, 'onEvent' | 'onSnapshot' | 'onError' | 'onConnectionChange'>) {
  if (!task.run_id || !task.organization_id) return null;
  return streamRunEvents({ organizationId: task.organization_id, runId: task.run_id, ...callbacks });
}

export function rentalError(error: unknown): string {
  const data = (error as { response?: { data?: unknown } })?.response?.data;
  if (data) return typeof data === 'string' ? data : JSON.stringify(data);
  return error instanceof Error ? error.message : '操作失败，请检查网络后重试。';
}

export function rentalApi(base: string) {
  async function all<T>(resource: string): Promise<T[]> {
    if (resource === 'personas') await api.put(`${base}/personas/built-ins`, {});
    const output: T[] = [];
    let page: number | null = 1;
    while (page) {
      const response: { results: T[]; next: number | null } = await api.get(`${base}/${resource}`, { page, archived: 'all' });
      output.push(...response.results); page = response.next;
    }
    return output;
  }
  return {
    all, settings: () => api.get<Preferences>(`${base}/settings`),
    saveSettings: (value: Preferences) => api.put<Preferences>(`${base}/settings`, value),
    create: (kind: Resource, value: Data) => api.post<RentalRecord>(`${base}/${kind}`, value),
    update: (kind: Resource, row: RentalRecord, value: Data) => api.patch<RentalRecord>(`${base}/${kind}/${row.id}`, { ...value, revision: row.revision }),
    overview: (section: string, params: Data = {}) => api.get<Overview>(`${base}/overview/${section}`, params),
    report: (params: Data = {}) => api.get<Report>(`${base}/overview/reports`, params),
    versions: (id: string) => api.get<Version[]>(`${base}/contents/${id}/versions`),
    saveVersion: (row: RentalRecord, body: CopyBody) => api.post<Version>(`${base}/contents/${row.id}/versions`, { revision: row.revision, body }),
    download: (id: string) => api.get<Blob>(`${base}/versions/${id}/download`, undefined, { responseType: 'blob' }),
    metrics: (id: string, data: Data) => api.post(`${base}/publications/${id}/metrics`, data),
    matches: (id: string) => api.get<Matches>(`${base}/leads/${id}/matches`),
    start: (data: Data) => api.post<Task>(`${base}/ai/tasks`, data),
    cancel: (id: string) => api.post<Task>(`${base}/ai/tasks/${id}/cancel`),
    apply: (id: string) => api.post<Task>(`${base}/ai/tasks/${id}/apply`),
  };
}
export type RentalApi = ReturnType<typeof rentalApi>;

export function dayInZone(zone: string, now = new Date()) {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: zone, year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(now);
  const part = (key: string) => parts.find(p => p.type === key)?.value;
  return `${part('year')}-${part('month')}-${part('day')}`;
}
export function localTime(value: string, zone: string) {
  if (!value) return '';
  const date = new Date(value);
  const parts = new Intl.DateTimeFormat('en-GB', { timeZone: zone, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).formatToParts(date);
  const p = (key: string) => parts.find(part => part.type === key)?.value;
  return `${p('year')}-${p('month')}-${p('day')}T${p('hour')}:${p('minute')}`;
}
export function utcTime(value: string, zone: string) {
  if (!value) return null;
  const target = Date.parse(`${value}:00Z`);
  let instant = target;
  for (let i = 0; i < 3; i++) {
    const rendered = Date.parse(`${localTime(new Date(instant).toISOString(), zone)}:00Z`);
    instant += target - rendered;
  }
  if (localTime(new Date(instant).toISOString(), zone) !== value) throw new Error('此时间在所选时区不存在，请调整时间。');
  return new Date(instant).toISOString();
}
export function downloadBlob(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url; link.download = name; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}
