import { api } from '@platform/http';
import { createIdempotencyKey } from '@platform/idempotency';

export interface Track {
  id: string; title: string; artist: string; album: string; version: string;
  reason?: string; sourceImageId?: string; note?: string;
  verification?: { status: 'verified' | 'ambiguous' | 'not_found' | 'unavailable'; source: string; url?: string; checkedAt: string; catalogId?: string };
}
export type TrackInput = Pick<Track, 'title' | 'artist' | 'album' | 'version'>;
export interface Playlist { id: string; name: string; tracks: Track[] }
export type Feedback = 'like' | 'dislike' | 'heard' | 'none';
export interface Preferences { language: string; exploration: string; excludeHeard: boolean }
export interface Library { revision: number; preferences: Preferences; feedback: { track: Track; value: Feedback }[]; playlists: Playlist[] }
export interface Filters { genre?: string; mood?: string; scene?: string; decade?: string; language?: string; exploration?: string }
export interface MusicTask {
  id: string; kind: 'import' | 'similar' | 'conditions'; status: string; error: string; progress: string; imported: boolean;
  imageIds: string[]; filters: Filters; createdAt: string; result: { tracks?: Track[]; notice?: string; processedSeeds?: number };
}
export interface TaskRequest { revision: number; kind: MusicTask['kind']; imageIds?: string[]; playlistId?: string; trackIds?: string[]; filters?: Filters }
export interface Mutation {
  revision: number; action: 'create' | 'rename' | 'delete' | 'add' | 'remove' | 'confirm' | 'feedback' | 'preferences';
  playlistId?: string; taskId?: string; name?: string; tracks?: TrackInput[]; trackIds?: string[]; feedback?: Feedback; preferences?: Preferences;
}
export const isActive = (task: MusicTask) => !['succeeded', 'failed', 'cancelled'].includes(task.status);
export const trackIdentity = (track: TrackInput) => [track.title, track.artist, track.version].map(v => v.normalize('NFKC').trim().replace(/\s+/g, ' ').toLowerCase()).join('|');
export const plainTrack = ({ title, artist, album, version }: TrackInput): TrackInput => ({ title, artist, album, version });
export const songText = (tracks: TrackInput[]) => tracks.map(t => `${t.title} — ${t.artist || '歌手待补充'}${t.version ? ` (${t.version})` : ''}`).join('\n');
export function musicLinks(track: TrackInput) {
  const query = encodeURIComponent(`${track.title} ${track.artist} ${track.version}`.trim());
  return { netease: `https://music.163.com/#/search/m/?s=${query}&type=1`, qq: `https://y.qq.com/n/ryqq/search?w=${query}&t=song` };
}

export function songApi(base: string) {
  // Failed requests retain their key until that exact payload succeeds. Separate channels
  // prevent feedback clicks from changing an import/task retry key.
  const pending = new Map<string, { fingerprint: string; key: string }>();
  async function submit<T>(channel: string, body: object, send: (value: object) => Promise<T>): Promise<T> {
    const fingerprint = JSON.stringify(body);
    let entry = pending.get(channel);
    if (!entry || entry.fingerprint !== fingerprint) {
      entry = { fingerprint, key: createIdempotencyKey('song') };
      pending.set(channel, entry);
    }
    const result = await send({ ...body, requestKey: entry.key });
    if (pending.get(channel) === entry) pending.delete(channel);
    return result;
  }
  const uploads = new WeakMap<File, string>();
  return {
    state: () => api.get<Library>(`${base}/state`),
    mutate: (body: Mutation) => submit('mutation', body, value => api.patch<Library>(`${base}/state`, value)),
    startTask: (body: TaskRequest) => submit('task', body, value => api.post<MusicTask>(`${base}/tasks`, value)),
    tasks: (page = 1) => api.get<{ count: number; results: MusicTask[] }>(`${base}/tasks`, { page }),
    task: (id: string) => api.get<MusicTask>(`${base}/tasks/${id}`),
    cancel: (id: string) => api.post<MusicTask>(`${base}/tasks/${id}/cancel`),
    deleteTask: (id: string) => api.delete(`${base}/tasks/${id}`),
    upload: async (file: File) => {
      let key = uploads.get(file);
      if (!key) { key = createIdempotencyKey('song-image'); uploads.set(file, key); }
      const form = new FormData(); form.append('file', file);
      const result = await api.post<{ id: string }>(`${base}/images`, form, { headers: { 'Idempotency-Key': key }, timeout: 120000 });
      uploads.delete(file); return result;
    },
    image: (id: string) => api.get<Blob>(`${base}/images/${id}`, undefined, { responseType: 'blob' }),
    deleteImage: (id: string) => api.delete(`${base}/images/${id}`),
    export: (id: string, format: 'txt' | 'csv') => api.get<Blob>(`${base}/playlists/${id}/export`, { fileType: format }, { responseType: 'blob' }),
  };
}
export type SongApi = ReturnType<typeof songApi>;
