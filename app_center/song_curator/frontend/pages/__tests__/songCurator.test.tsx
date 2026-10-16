// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { api } from '@platform/http';
import { songApi, musicLinks, type Library, type MusicTask } from '../../services/songCurator';
import { SongWorkspace } from '../SongCuratorPage';
import { ImportReview } from '../ImportReview';

vi.mock('@/services/api', () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } }));
const track = { id: 'track-1', title: 'Hello', artist: 'Adele', album: '', version: '' };
const state: Library = { revision: 0, playlists: [{ id: 'list-1', name: 'Favorites', tracks: [track] }], preferences: { language: 'follow', exploration: 'balanced', excludeHeard: true }, feedback: [] };
const result: MusicTask = { id: 'task-1', kind: 'conditions', status: 'succeeded', progress: '已完成', error: '', imported: false, imageIds: [], filters: {}, createdAt: '2026-10-16T00:00:00Z', result: { tracks: [{ ...track, reason: '温暖的人声', verification: { status: 'unavailable', source: 'iTunes', checkedAt: '2026-10-16T00:00:00Z' } }], notice: 'AI 判断' } };
let container: HTMLDivElement; let root: Root;
beforeEach(() => {
  vi.useFakeTimers(); vi.clearAllMocks();
  const computed = window.getComputedStyle.bind(window);
  vi.spyOn(window, 'getComputedStyle').mockImplementation(element => computed(element));
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() })));
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  vi.mocked(api.get).mockImplementation(async url => url.endsWith('/state') ? structuredClone(state) : url.endsWith('/tasks/task-1') ? structuredClone(result) : { count: 1, results: [structuredClone(result)] });
  vi.mocked(api.post).mockResolvedValue(result);
  vi.mocked(api.patch).mockResolvedValue({ ...state, revision: 1 });
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
const button = (label: string) => [...document.querySelectorAll('button')].find(b => b.textContent?.replace(/\s/g, '').includes(label.replace(/\s/g, '')))!;
const render = async (path = '/?tab=discover') => { await act(async () => root.render(<MemoryRouter initialEntries={[path]}><SongWorkspace base="/music" /></MemoryRouter>)); };

it.each(['missing', 'throws', 'absent'])('recommendation workflow reaches API and reuses only failed keys with crypto %s', async variant => {
  vi.stubGlobal('crypto', variant === 'absent' ? undefined : variant === 'throws' ? { randomUUID: () => { throw new Error('insecure'); } } : {});
  vi.mocked(api.post).mockRejectedValueOnce(new Error('Network failed')).mockResolvedValue(result);
  await render();
  await act(async () => button('为我推荐').click());
  expect(document.body.textContent).toContain('Network failed');
  const first = vi.mocked(api.post).mock.calls[0][1] as Record<string, unknown>;
  expect(first.kind).toBe('conditions'); expect(typeof first.requestKey).toBe('string');
  await act(async () => button('为我推荐').click());
  const second = vi.mocked(api.post).mock.calls[1][1] as Record<string, unknown>;
  expect(second.requestKey).toBe(first.requestKey);
  await act(async () => button('为我推荐').click());
  const third = vi.mocked(api.post).mock.calls[2][1] as Record<string, unknown>;
  expect(third.requestKey).not.toBe(second.requestKey);
});

it('uses the same submission path for imports and similar recommendations with changed payload keys', async () => {
  vi.stubGlobal('crypto', undefined);
  const client = songApi('/music');
  vi.mocked(api.post).mockRejectedValueOnce(new Error('offline'));
  await expect(client.startTask({ kind: 'import', revision: 0, imageIds: ['one'] })).rejects.toThrow();
  await client.startTask({ kind: 'import', revision: 0, imageIds: ['two'] });
  await client.startTask({ kind: 'similar', revision: 0, playlistId: 'list-1', trackIds: [] });
  const bodies = vi.mocked(api.post).mock.calls.map(c => c[1] as Record<string, unknown>);
  expect(new Set(bodies.map(b => b.requestKey)).size).toBe(3);
});

it('restores results, clearly labels unverified songs, and persists feedback', async () => {
  await render('/?task=task-1');
  expect(document.body.textContent).toContain('温暖的人声');
  expect(document.body.textContent).toContain('目录暂不可用');
  expect(document.querySelector('a[href*="music.163.com"]')?.getAttribute('href')).toContain('Hello%20Adele');
  await act(async () => button('不感兴趣').click());
  expect(api.patch).toHaveBeenCalledWith('/music/state', expect.objectContaining({ action: 'feedback', feedback: 'dislike', tracks: [{ title: 'Hello', artist: 'Adele', album: '', version: '' }] }));
});

it('does not import OCR results until review confirmation and supports correcting text', async () => {
  const save = vi.fn().mockResolvedValue(true);
  await act(async () => root.render(<ImportReview client={songApi('/music')} task={{ ...result, kind: 'import', result: { tracks: [track, { ...track, id: 'duplicate' }, { ...track, id: 'live', version: 'Live' }] } }} playlists={[]} busy={false} onSave={save} />));
  expect(save).not.toHaveBeenCalled();
  await act(async () => button('去除重复').click());
  expect(document.body.textContent).toContain('已移除 1 首重复歌曲');
  const input = document.querySelector<HTMLInputElement>('#song-0-title')!;
  await act(async () => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, 'Corrected'); input.dispatchEvent(new Event('input', { bubbles: true })); });
  await act(async () => button('确认并保存').click());
  expect(save).toHaveBeenCalledWith([expect.objectContaining({ title: 'Corrected' }), expect.objectContaining({ version: 'Live' })], 'new', '我的新歌单');
});

it('shows task failures and supports manual entry without requiring AI', async () => {
  vi.mocked(api.get).mockImplementation(async url => url.endsWith('/state') ? state : url.endsWith('/tasks/task-1') ? { ...result, status: 'failed', error: '图片输入不支持' } : { count: 0, results: [] });
  await render('/?task=task-1');
  expect(document.body.textContent).toContain('图片输入不支持');
  await act(async () => button('手动录入').click());
  expect(document.body.textContent).toContain('粘贴文字歌单');
});

it('encodes user supplied names into fixed music search addresses', () => {
  const links = musicLinks({ ...track, title: 'https://evil.test/?x=&', artist: '甲 乙' });
  expect(links.qq).toMatch(/^https:\/\/y\.qq\.com\//);
  expect(links.netease).toContain(encodeURIComponent('https://evil.test/?x=& 甲 乙'));
});

it('imports a JSON file into review and saves the playlist only after confirmation', async () => {
  vi.useRealTimers();
  await render();
  await act(async () => button('导入 JSON 歌单').click());
  const file = new File([JSON.stringify({ name: '乡村', platform: 'qqmusic', tracks: [{ title: 'We Got Love', artist: 'Don Williams', album: 'New Moves' }] })], '乡村.json', { type: 'application/json' });
  const input = document.querySelector<HTMLInputElement>('#song-json-file')!;
  await act(async () => {
    Object.defineProperty(input, 'files', { configurable: true, value: [file] });
    input.dispatchEvent(new Event('change', { bubbles: true }));
    await new Promise(resolve => setTimeout(resolve, 40));
  });
  expect(document.body.textContent).toContain('乡村');
  expect(api.post).not.toHaveBeenCalled(); expect(api.patch).not.toHaveBeenCalled();
  await act(async () => button('核对歌单').click());
  expect(document.querySelector<HTMLInputElement>('#song-import-name')?.value).toBe('乡村');
  expect(document.querySelector<HTMLInputElement>('#song-0-title')?.value).toBe('We Got Love');
  expect(api.patch).not.toHaveBeenCalled();
  await act(async () => button('确认并保存').click());
  expect(api.patch).toHaveBeenCalledWith('/music/state', expect.objectContaining({ action: 'create', name: '乡村', tracks: [{ title: 'We Got Love', artist: 'Don Williams', album: 'New Moves', version: '' }] }));
  expect(api.post).not.toHaveBeenCalled();
});

it('keeps invalid JSON in the import dialog without writing or enabling confirmation', async () => {
  vi.useRealTimers(); await render();
  await act(async () => button('导入 JSON 歌单').click());
  const input = document.querySelector<HTMLInputElement>('#song-json-file')!;
  await act(async () => {
    Object.defineProperty(input, 'files', { configurable: true, value: [new File(['bad'], 'bad.json')] });
    input.dispatchEvent(new Event('change', { bubbles: true }));
    await new Promise(resolve => setTimeout(resolve, 40));
  });
  expect(document.body.textContent).toContain('不是有效的 JSON');
  expect(button('核对歌单').disabled).toBe(true);
  expect(api.patch).not.toHaveBeenCalled(); expect(api.post).not.toHaveBeenCalled();
});
