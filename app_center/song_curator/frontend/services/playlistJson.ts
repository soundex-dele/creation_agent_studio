import type { Track } from './songCurator';

export interface PlaylistDraft { name: string; tracks: Track[]; notice: string }
export const MAX_PLAYLIST_FILE_BYTES = 5 * 1024 * 1024;

const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null && !Array.isArray(value);

function field(value: unknown, label: string, maxLength: number, required = false): string {
  if (value === undefined || value === null) {
    if (required) throw new Error(`${label}不能为空。`);
    return '';
  }
  if (typeof value !== 'string') throw new Error(`${label}必须是文字。`);
  const text = value.trim();
  if (required && !text) throw new Error(`${label}不能为空。`);
  if ([...text].length > maxLength) throw new Error(`${label}不能超过 ${maxLength} 个字符。`);
  return text;
}

export function parsePlaylistJson(text: string, filename = '导入的歌单.json'): PlaylistDraft {
  let value: unknown;
  try { value = JSON.parse(text.replace(/^\uFEFF/, '')); }
  catch { throw new Error('文件不是有效的 JSON，请检查内容或重新导出歌单。'); }
  const metadata = isRecord(value) ? value : undefined;
  const rows = Array.isArray(value) ? value : metadata?.tracks;
  if (!Array.isArray(rows)) throw new Error('未找到歌曲列表：需要包含 tracks 数组的歌单对象，或直接提供歌曲数组。');
  if (!rows.length) throw new Error('文件中的歌曲列表为空，请选择包含歌曲的歌单。');
  if (rows.length > 500) throw new Error(`文件包含 ${rows.length} 首歌曲，单个歌单最多 500 首，请拆分后导入。`);
  const name = field(metadata?.name, '歌单名称', 120) || [...filename.replace(/\.(json|txt)$/i, '')].slice(0, 120).join('') || '导入的歌单';
  const tracks = rows.map((row: unknown, index): Track => {
    if (!isRecord(row)) throw new Error(`第 ${index + 1} 首歌曲格式无效，需要包含 title、artist 等字段的对象。`);
    const prefix = `第 ${index + 1} 首歌曲的`;
    // Never trust imported IDs, links, verification flags or platform availability.
    return { id: `json-${index}`, title: field(row.title, `${prefix}歌名`, 300, true),
      artist: field(row.artist, `${prefix}歌手`, 300), album: field(row.album, `${prefix}专辑`, 300),
      version: field(row.version, `${prefix}版本`, 120) };
  });
  const notices: string[] = [];
  const total = metadata?.trackCount;
  if (metadata?.isPartial === true || (typeof total === 'number' && total > tracks.length)) {
    notices.push(`源文件为部分歌单，本次只能导入文件中实际包含的 ${tracks.length} 首歌曲。`);
  }
  const loaded = metadata?.loadedTrackCount;
  if (typeof loaded === 'number' && loaded !== tracks.length) notices.push(`文件标注的已加载数量与歌曲列表不一致，以实际 ${tracks.length} 首为准。`);
  return { name, tracks, notice: notices.join(' ') };
}

export async function readPlaylistFile(file: File): Promise<PlaylistDraft> {
  if (!file.size) throw new Error('文件为空，请重新选择。');
  if (file.size > MAX_PLAYLIST_FILE_BYTES) throw new Error('歌单文件不能超过 5 MB。');
  const text = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ''));
    reader.onerror = () => reject(new Error('无法读取文件，请重新选择。'));
    reader.onabort = () => reject(new Error('文件读取已取消，请重新选择。'));
    reader.readAsText(file, 'UTF-8');
  });
  return parsePlaylistJson(text, file.name);
}
