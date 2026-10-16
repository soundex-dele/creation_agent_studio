import { useEffect, useState } from 'react';
import { Alert, Button, Empty, Input, Select } from 'antd';
import type { MusicTask, Playlist, SongApi, Track, TrackInput } from '../services/songCurator';
import { plainTrack, trackIdentity } from '../services/songCurator';
import type { PlaylistDraft } from '../services/playlistJson';

function SourceImage({ client, id }: { client: SongApi; id: string }) {
  const [url, setUrl] = useState(''); const [error, setError] = useState(false);
  useEffect(() => {
    let alive = true; let objectUrl = '';
    void client.image(id).then(blob => { objectUrl = URL.createObjectURL(blob); if (alive) setUrl(objectUrl); else URL.revokeObjectURL(objectUrl); })
      .catch(() => { if (alive) setError(true); });
    return () => { alive = false; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [client, id]);
  return error ? <Alert type="warning" message="原图暂时无法加载，可稍后重新打开任务。" /> : url ? <a href={url} target="_blank" rel="noreferrer"><img className="song-source-image" src={url} alt="歌单来源截图，点击查看原图" /></a> : <p role="status">加载原图…</p>;
}

export function ImportReview({ task, initialDraft, client, playlists, busy, onSave }: {
  task?: MusicTask; client: SongApi; playlists: Playlist[]; busy: boolean;
  initialDraft?: PlaylistDraft;
  onSave: (tracks: TrackInput[], target: string, name: string) => Promise<boolean>;
}) {
  const [rows, setRows] = useState<Track[]>(task?.result.tracks || initialDraft?.tracks || []);
  const [source, setSource] = useState(task?.imageIds[0] || '');
  const [target, setTarget] = useState('new'); const [name, setName] = useState(initialDraft?.name || '我的新歌单');
  const [text, setText] = useState(''); const [notice, setNotice] = useState('');
  const [next, setNext] = useState(0);
  const add = (values: TrackInput[]) => {
    const additions = values.map((value, i) => ({ ...value, id: `manual-${next + i}` }));
    setNext(next + values.length); setRows(old => [...old, ...additions]);
  };
  const dedupe = () => {
    const seen = new Set<string>(); const unique = rows.filter(row => { const key = trackIdentity(row); if (seen.has(key)) return false; seen.add(key); return true; });
    setRows(unique); setNotice(`已移除 ${rows.length - unique.length} 首重复歌曲；不同歌手或版本分别保留。`);
  };
  return <section className="song-panel" aria-label="核对歌曲">
    <div className="song-section-heading"><div><span className="song-eyebrow">02 · 核对与保存</span><h2>{task ? '核对识别结果' : initialDraft ? '核对 JSON 歌单' : '手动录入歌曲'}</h2></div><span>{rows.length} 首</span></div>
    <p className="song-muted">模糊信息可以留空。保存只导入歌曲信息，不会同步到音乐平台。</p>
    {task?.imported && <Alert type="success" message="这批识别结果已经导入歌单。" />}
    {notice && <Alert type="info" message={notice} showIcon />}
    {initialDraft?.notice && <Alert type="warning" message={initialDraft.notice} showIcon />}
    <div className={task?.imageIds.length ? 'song-review-grid' : ''}>
      {!!task?.imageIds.length && <aside className="song-source"><label htmlFor="song-source">来源截图</label><Select id="song-source" value={source} onChange={setSource} options={task.imageIds.map((id, i) => ({ value: id, label: `截图 ${i + 1}` }))} /><SourceImage key={source} client={client} id={source} /></aside>}
      <div className="song-review-rows">
        {!rows.length && <Empty description="没有识别到歌曲，可更换图片或手动补充。" />}
        {rows.map((row, index) => <div className="song-edit-row" key={row.id}>
          <div className="song-section-heading"><strong>歌曲 {index + 1}</strong><div className="song-actions">{row.sourceImageId && <Button size="small" onClick={() => setSource(row.sourceImageId!)}>对照原图</Button>}<Button size="small" danger disabled={busy || task?.imported} onClick={() => setRows(rows.filter((_, i) => i !== index))}>移除</Button></div></div>
          <div className="song-fields">{(['title', 'artist', 'album', 'version'] as const).map((field, i) => <div className="song-field" key={field}><label htmlFor={`song-${index}-${field}`}>{['歌名', '歌手', '专辑（选填）', '版本（选填）'][i]}</label><Input id={`song-${index}-${field}`} value={row[field]} maxLength={field === 'version' ? 120 : 300} disabled={busy || task?.imported} onChange={event => setRows(old => old.map((r, n) => n === index ? { ...r, [field]: event.target.value } : r))} /></div>)}</div>
          {(row.note || !row.artist) && <p className="song-muted">待核对：{row.note || '截图未明确提供歌手，可手动补充。'}</p>}
        </div>)}
      </div>
    </div>
    {!task?.imported && <>
      <div className="song-actions"><Button disabled={busy || rows.length >= 500} onClick={() => add([{ title: '', artist: '', album: '', version: '' }])}>补充一首</Button><Button disabled={busy || !rows.length} onClick={dedupe}>去除重复</Button></div>
      <details className="song-text-import"><summary>粘贴文字歌单</summary><label htmlFor="song-paste-text">每行一首：歌名 — 歌手（也支持制表符）</label><Input.TextArea id="song-paste-text" rows={4} maxLength={20000} value={text} onChange={event => setText(event.target.value)} /><Button disabled={busy || !text.trim()} onClick={() => {
        const values = text.split('\n').filter(s => s.trim()).map(line => { const [title, ...artist] = line.split(/\t|\s+—\s+|\s+-\s+/); return { title: title.trim(), artist: artist.join(' ').trim(), album: '', version: '' }; });
        if (rows.length + values.length > 500) { setNotice('每批最多 500 首，请分批添加。'); return; }
        add(values); setText('');
      }}>加入核对列表</Button></details>
      <div className="song-fields"><div className="song-field"><label htmlFor="song-import-target">保存到</label><Select id="song-import-target" value={target} onChange={setTarget} options={[{ value: 'new', label: '新建歌单' }, ...playlists.map(p => ({ value: p.id, label: p.name }))]} /></div>{target === 'new' && <div className="song-field"><label htmlFor="song-import-name">新歌单名称</label><Input id="song-import-name" value={name} maxLength={120} onChange={event => setName(event.target.value)} /></div>}</div>
      <Button type="primary" loading={busy} disabled={!rows.length || rows.some(row => !row.title.trim()) || (target === 'new' && !name.trim())} onClick={() => void onSave(rows.map(plainTrack), target, name.trim()).then(ok => { if (ok) setNotice('已保存到歌单。'); })}>确认并保存 {rows.length} 首</Button>
    </>}
  </section>;
}
