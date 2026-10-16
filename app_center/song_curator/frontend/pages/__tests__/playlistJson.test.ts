// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import { parsePlaylistJson, readPlaylistFile, MAX_PLAYLIST_FILE_BYTES } from '../../services/playlistJson';

const song = { title: "Kiss An Angel Good Mornin'", artist: 'Alan Jackson', album: 'Under The Influence' };

describe('playlist JSON import', () => {
  it('reads Playlist Out metadata and extracts only editable song fields', () => {
    const draft = parsePlaylistJson(JSON.stringify({ name: '乡村', generator: 'Playlist Out', platform: 'qqmusic', trackCount: 1, loadedTrackCount: 1, isPartial: false, tracks: [{ ...song, id: 'external-id', sourceUrl: 'https://example.test/song', isVip: true, verification: { status: 'verified' } }] }));
    expect(draft.name).toBe('乡村'); expect(draft.notice).toBe('');
    expect(draft.tracks).toEqual([{ ...song, id: 'json-0', version: '' }]);
  });
  it('supports BOM, plain arrays and filename-derived names', () => {
    const draft = parsePlaylistJson('\uFEFF' + JSON.stringify([{ title: '晴天' }, { title: '晴天', version: 'Live' }]), '我的歌单.txt');
    expect(draft.name).toBe('我的歌单'); expect(draft.tracks[0].artist).toBe('');
    expect(draft.tracks[1].version).toBe('Live');
  });
  it('reports partial exports and count mismatches without inventing missing tracks', () => {
    const draft = parsePlaylistJson(JSON.stringify({ name: '部分', trackCount: 25, loadedTrackCount: 3, isPartial: true, tracks: [song] }));
    expect(draft.tracks).toHaveLength(1); expect(draft.notice).toContain('部分歌单'); expect(draft.notice).toContain('不一致');
  });
  it.each(['no json', 'null', '{}', '[]', '{"tracks":{}}', '{"tracks":[null]}', '{"tracks":[{"artist":"Adele"}]}', '{"tracks":[{"title":"Hello","artist":123}]}'])('rejects malformed or invalid tracks: %s', input => {
    expect(() => parsePlaylistJson(input)).toThrow();
  });
  it('rejects excess count and long fields rather than truncating songs', () => {
    expect(() => parsePlaylistJson(JSON.stringify(Array.from({ length: 501 }, () => song)))).toThrow('501');
    expect(() => parsePlaylistJson(JSON.stringify([{ ...song, title: 'x'.repeat(301) }]))).toThrow('第 1 首');
    expect(() => parsePlaylistJson(JSON.stringify({ name: 'x'.repeat(121), tracks: [song] }))).toThrow('歌单名称');
  });
  it('keeps duplicates for review and preserves ordering', () => {
    const draft = parsePlaylistJson(JSON.stringify([song, song, { title: 'Other' }]));
    expect(draft.tracks.map(t => t.title)).toEqual([song.title, song.title, 'Other']);
    expect(new Set(draft.tracks.map(t => t.id)).size).toBe(3);
  });
  it('reads UTF-8 JSON stored in a TXT file', async () => {
    const draft = await readPlaylistFile(new File([JSON.stringify({ name: '乡村', tracks: [song] })], '已粘贴的文本.txt', { type: 'text/plain' }));
    expect(draft.name).toBe('乡村'); expect(draft.tracks).toHaveLength(1);
  });
  it('rejects empty or oversized files before reading', async () => {
    await expect(readPlaylistFile(new File([], 'empty.json'))).rejects.toThrow('文件为空');
    const oversized = new File(['{}'], 'big.json');
    Object.defineProperty(oversized, 'size', { value: MAX_PLAYLIST_FILE_BYTES + 1 });
    await expect(readPlaylistFile(oversized)).rejects.toThrow('5 MB');
  });
});
