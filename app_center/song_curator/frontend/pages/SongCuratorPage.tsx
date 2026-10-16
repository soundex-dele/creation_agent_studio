import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { Alert, Button, Checkbox, Empty, Input, Modal, Pagination, Popconfirm, Select, Spin, Tabs, Tag } from 'antd';
import { ArrowLeft, Headphones, Heart, ListMusic, Plus, ScanLine, Sparkles } from 'lucide-react';
import { useOrganizationStore } from '@platform/organization';
import { useAuthStore } from '@platform/auth';
import { tenantApiRoot } from '@platform/tenant';
import { resolveApplicationPresentation } from '@platform/presentation';
import { documentError } from '@platform/errors';
import { saveResearchBlob } from '@platform/download';
import { songApi, isActive, musicLinks, plainTrack, songText, trackIdentity } from '../services/songCurator';
import type { Feedback, Filters, Library, MusicTask, Mutation, Preferences, Track, TrackInput } from '../services/songCurator';
import { ImportReview } from './ImportReview';
import { JsonPlaylistImport } from './JsonPlaylistImport';
import type { PlaylistDraft } from '../services/playlistJson';
import './SongCuratorPage.css';

const languages = [{ value: 'follow', label: '跟随歌单 · 无歌单时不限' }, { value: 'any', label: '不限语言' }, { value: 'zh', label: '华语' }, { value: 'en', label: '欧美' }, { value: 'ja-ko', label: '日韩' }];
const exploration = [{ value: 'close', label: '贴近原风格' }, { value: 'balanced', label: '均衡探索' }, { value: 'explore', label: '更多探索' }];
const statusLabels: Record<string, string> = { queued: '等待执行', running: '处理中', succeeded: '已完成', failed: '失败', cancelled: '已取消' };
const verifyLabels = { verified: '目录已核验', ambiguous: '存在歧义 · 待核对', not_found: '未找到 · 待核验', unavailable: '目录暂不可用 · 待核验' };
const feedbackLabels = { like: '喜欢', dislike: '不感兴趣', heard: '听过了', none: '撤销反馈' };

function TrackCard({ track, feedback, busy, onFeedback, onSave, selectable }: {
  track: Track; feedback?: Feedback; busy: boolean; onFeedback: (value: Feedback) => void; onSave: () => void; selectable?: React.ReactNode;
}) {
  const links = musicLinks(track); const verification = track.verification;
  return <article className="song-track">
    <div className="song-track-main">{selectable}<span className="song-record"><Headphones size={23} aria-hidden="true" /></span><div className="song-track-title"><h3>{track.title}</h3><p>{track.artist || '歌手待补充'}{track.version && ` · ${track.version}`}{track.album && ` · ${track.album}`}</p></div></div>
    {track.reason && <p className="song-reason"><span>推荐理由 · AI 判断</span>{track.reason}</p>}
    {verification && <div className="song-verification"><Tag>{verifyLabels[verification.status]}</Tag>{verification.url && <a href={verification.url} target="_blank" rel="noopener noreferrer">iTunes 来源</a>}<time dateTime={verification.checkedAt}>{new Date(verification.checkedAt).toLocaleDateString('zh-CN')}</time></div>}
    <div className="song-track-footer"><div className="song-actions"><a href={links.netease} target="_blank" rel="noopener noreferrer">网易云搜索 ↗</a><a href={links.qq} target="_blank" rel="noopener noreferrer">QQ 音乐搜索 ↗</a></div><div className="song-actions">{(['like', 'dislike', 'heard'] as const).map(value => <Button key={value} size="small" disabled={busy} aria-pressed={feedback === value} type={feedback === value ? 'primary' : 'default'} onClick={() => onFeedback(feedback === value ? 'none' : value)}>{feedbackLabels[value]}</Button>)}<Button size="small" disabled={busy} onClick={onSave} icon={<Plus size={14} aria-hidden="true" />}>存入歌单</Button></div></div>
  </article>;
}

export function SongWorkspace({ base }: { base: string }) {
  const client = useMemo(() => songApi(base), [base]);
  const [params, setParams] = useSearchParams();
  const tab = params.get('tab') || 'discover'; const selectedTaskId = params.get('task') || '';
  const [library, setLibrary] = useState<Library>(); const [tasks, setTasks] = useState<MusicTask[]>([]);
  const [taskCount, setTaskCount] = useState(0); const [page, setPage] = useState(1);
  const [selectedTask, setSelectedTask] = useState<MusicTask>();
  const [error, setError] = useState(''); const [info, setInfo] = useState(''); const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true); const [refresh, setRefresh] = useState(0);
  const [playlistId, setPlaylistId] = useState(''); const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [search, setSearch] = useState(''); const [mode, setMode] = useState<'similar' | 'conditions'>('conditions');
  const [filters, setFilters] = useState<Filters>({}); const [prefs, setPrefs] = useState<Preferences>();
  const [importOpen, setImportOpen] = useState(false); const [manual, setManual] = useState(false); const [manualKey, setManualKey] = useState(0);
  const [jsonOpen, setJsonOpen] = useState(false); const [jsonDraft, setJsonDraft] = useState<PlaylistDraft>();
  const [images, setImages] = useState<{ file: File; id?: string; error?: string }[]>([]);
  const [uploading, setUploading] = useState(false); const uploadLock = useRef(false);
  const [saveTracks, setSaveTracks] = useState<TrackInput[] | null>(null); const [saveTarget, setSaveTarget] = useState('new');
  const [name, setName] = useState('我的新歌单'); const [rename, setRename] = useState(false);
  const [copyText, setCopyText] = useState(''); const [resultIds, setResultIds] = useState<string[]>([]);
  const navigate = useCallback((changes: Record<string, string>) => setParams(old => { const next = new URLSearchParams(old); Object.entries(changes).forEach(([k, v]) => v ? next.set(k, v) : next.delete(k)); return next; }), [setParams]);

  useEffect(() => {
    let alive = true; setLoading(true);
    void client.state().then(data => { if (alive) { setLibrary(data); setPrefs(data.preferences); } }).catch(e => { if (alive) setError(documentError(e)); }).finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [client, refresh]);
  useEffect(() => {
    let alive = true; let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const [data, detail] = await Promise.all([client.tasks(page), selectedTaskId ? client.task(selectedTaskId) : Promise.resolve(undefined)]);
        if (!alive) return;
        setTasks(data.results); setTaskCount(data.count); setSelectedTask(detail);
        if (data.results.some(isActive) || (detail && isActive(detail))) timer = setTimeout(() => void poll(), 3000);
      } catch (e) { if (alive) setError(documentError(e)); }
    };
    void poll(); return () => { alive = false; clearTimeout(timer); };
  }, [client, page, refresh, selectedTaskId]);
  useEffect(() => { setResultIds([]); }, [selectedTaskId]);

  const mutate = async (body: Omit<Mutation, 'revision'>) => {
    if (!library || busy) return false;
    setBusy(true); setError('');
    try { setLibrary(await client.mutate({ ...body, revision: library.revision })); return true; }
    catch (e) { setError(documentError(e)); return false; }
    finally { setBusy(false); }
  };
  const start = async (kind: MusicTask['kind']) => {
    if (!library || busy) return;
    setBusy(true); setError('');
    try {
      const task = await client.startTask({ revision: library.revision, kind,
        ...(kind === 'import' ? { imageIds: images.map(i => i.id!) } : { filters, ...(kind === 'similar' ? { playlistId, trackIds: selectedIds } : {}) }) });
      setSelectedTask(task); setManual(false); navigate({ task: task.id, tab: 'discover' });
      if (kind === 'import') { setImages([]); setImportOpen(false); }
      setRefresh(v => v + 1);
    } catch (e) { setError(documentError(e)); } finally { setBusy(false); }
  };
  const uploadFiles = async (files: File[], retry = false) => {
    if (uploadLock.current) return;
    if (!retry && images.length + files.length > 5) { setError('每批最多 5 张图片。'); return; }
    if (files.some(file => !['image/png', 'image/jpeg', 'image/webp'].includes(file.type) || !file.size || file.size > 20 * 1024 * 1024)) { setError('请选择不超过 20 MB 的静态 PNG、JPEG 或 WebP 图片。'); return; }
    uploadLock.current = true; setUploading(true); setError('');
    if (!retry) setImages(old => [...old, ...files.map(file => ({ file }))]);
    try {
      for (const file of files) {
        try { const result = await client.upload(file); setImages(old => old.map(i => i.file === file ? { file, id: result.id } : i)); }
        catch (e) { const message = documentError(e); setImages(old => old.map(i => i.file === file ? { file, error: message } : i)); }
      }
    } finally { setUploading(false); uploadLock.current = false; }
  };
  const runAction = async (action: () => Promise<unknown>) => { setBusy(true); setError(''); try { await action(); setRefresh(v => v + 1); } catch (e) { setError(documentError(e)); } finally { setBusy(false); } };
  const feedbackFor = (track: Track) => library?.feedback.find(f => trackIdentity(f.track) === trackIdentity(track))?.value;
  const feedback = (track: Track, value: Feedback) => void mutate({ action: 'feedback', tracks: [plainTrack(track)], feedback: value });
  const playlist = library?.playlists.find(p => p.id === playlistId);
  const filteredTracks = playlist?.tracks.filter(t => `${t.title} ${t.artist} ${t.album}`.toLowerCase().includes(search.toLowerCase())) || [];
  const openSave = (tracks: TrackInput[]) => { setSaveTracks(tracks.map(plainTrack)); setSaveTarget('new'); setName('我的新歌单'); };
  const openManual = () => { setJsonDraft(undefined); setManual(true); setManualKey(v => v + 1); navigate({ tab: 'discover', task: '' }); };
  const selectedResult = selectedTask?.result.tracks?.filter(t => resultIds.includes(t.id)) || [];
  const renderTrack = (track: Track, selectable?: React.ReactNode) => <TrackCard key={track.id} track={track} busy={busy} feedback={feedbackFor(track)} onFeedback={value => feedback(track, value)} onSave={() => openSave([track])} selectable={selectable} />;

  return <main className="song-page app-scroll-page"><div className="song-container">
    <header className="song-header"><div>{resolveApplicationPresentation(params).showApplicationHeader && <Link className="song-back" to="/apps"><ArrowLeft size={15} aria-hidden="true" /> 返回应用</Link>}<span className="song-eyebrow">YOUR NEXT FAVORITE SONG</span><h1><Headphones aria-hidden="true" /> 歌曲推荐官</h1><p>从你喜欢的歌出发，遇见下一次心动。</p></div><div className="song-actions"><Button disabled={busy} onClick={() => setJsonOpen(true)}>导入 JSON 歌单</Button><Button onClick={openManual} disabled={busy}>手动录入</Button><Button type="primary" icon={<ScanLine size={17} aria-hidden="true" />} onClick={() => setImportOpen(true)}>导入歌单截图</Button></div></header>
    {error && <Alert type="error" showIcon message={error} description="输入已保留。网络失败可重试同一操作；数据冲突时请刷新后重新应用。" action={<Button disabled={busy} onClick={() => { setError(''); setRefresh(v => v + 1); }}>刷新数据</Button>} />}
    {info && <Alert type="success" message={info} closable onClose={() => setInfo('')} />}
    {loading && !library ? <Spin tip="加载音乐资料库"><div className="song-loading" /></Spin> : !library ? <Empty description="暂时无法加载资料库，请重试。" /> : <>
      <Tabs activeKey={tab} onChange={value => navigate({ tab: value })} items={[{ key: 'discover', label: <span className="song-tab"><Sparkles size={17} aria-hidden="true" />发现推荐</span> }, { key: 'library', label: <span className="song-tab"><ListMusic size={17} aria-hidden="true" />我的歌单</span> }, { key: 'history', label: <span className="song-tab"><Heart size={17} aria-hidden="true" />偏好与历史</span> }]} />
      {tab === 'discover' && <>
        <section className="song-panel song-discover"><div className="song-section-heading"><div><span className="song-eyebrow">01 · 选择发现方式</span><h2>今天想听点什么？</h2></div><Select aria-label="推荐方式" value={mode} onChange={setMode} options={[{ value: 'conditions', label: '按流派与场景' }, { value: 'similar', label: '从喜欢的歌出发' }]} /></div>
          {mode === 'similar' && <div className="song-field"><label htmlFor="song-seed">种子歌单</label><Select id="song-seed" placeholder="选择一张歌单" value={playlistId || undefined} onChange={value => { setPlaylistId(value); setSelectedIds([]); }} options={library.playlists.map(p => ({ value: p.id, label: `${p.name} · ${p.tracks.length} 首` }))} />{playlist && <><p className="song-muted">未勾选时使用整张歌单（{playlist.tracks.length} 首）；长歌单分批分析，不会只取前几首。</p><Select mode="multiple" aria-label="选择部分种子歌曲" placeholder="可选：指定部分歌曲" value={selectedIds} onChange={setSelectedIds} maxTagCount="responsive" options={playlist.tracks.map(t => ({ value: t.id, label: `${t.title} — ${t.artist}` }))} /></>}</div>}
          <div className="song-filters">{([['genre', '流派', ['流行', '摇滚', '民谣', '电子', '爵士', '古典', '嘻哈', 'R&B']], ['mood', '心情', ['轻松', '治愈', '快乐', '伤感', '热血', '平静']], ['scene', '场景', ['通勤', '专注工作', '夜跑', '雨天', '旅行', '睡前']], ['decade', '年代', ['2020年代', '2010年代', '2000年代', '1990年代', '1980年代及以前']]] as const).map(([field, label, options]) => <div className="song-field" key={field}><label htmlFor={`song-filter-${field}`}>{label}</label><Select id={`song-filter-${field}`} value={filters[field] || undefined} allowClear placeholder="不限" onChange={value => setFilters(old => ({ ...old, [field]: value || '' }))} options={options.map(value => ({ value, label: value }))} /></div>)}
            <div className="song-field"><label htmlFor="song-language">语言范围</label><Select id="song-language" value={filters.language || library.preferences.language} options={languages} onChange={value => setFilters(old => ({ ...old, language: value }))} /></div><div className="song-field"><label htmlFor="song-explore">探索程度</label><Select id="song-explore" value={filters.exploration || library.preferences.exploration} options={exploration} onChange={value => setFilters(old => ({ ...old, exploration: value }))} /></div>
          </div><div className="song-section-heading"><p className="song-muted">每次最多 10 首，参考你的反馈并避开近期推荐。</p><Button type="primary" loading={busy} disabled={mode === 'similar' && !playlist?.tracks.length} onClick={() => void start(mode)} icon={<Sparkles size={16} aria-hidden="true" />}>为我推荐</Button></div>
        </section>
        {manual && <ImportReview key={`manual-${manualKey}`} initialDraft={jsonDraft} client={client} playlists={library.playlists} busy={busy} onSave={async (tracks, target, newName) => { const ok = await mutate({ action: target === 'new' ? 'create' : 'add', tracks, ...(target === 'new' ? { name: newName } : { playlistId: target }) }); if (ok) { setManual(false); setInfo('歌曲已保存到歌单。'); } return ok; }} />}
        {selectedTask && !manual && <section className="song-results" aria-label="任务结果"><div className="song-section-heading"><h2>{selectedTask.kind === 'import' ? '截图导入' : '为你发现'}</h2><div className="song-actions"><Tag>{statusLabels[selectedTask.status] || selectedTask.status}</Tag>{isActive(selectedTask) && <Button disabled={busy} onClick={() => void runAction(() => client.cancel(selectedTask.id))}>取消任务</Button>}</div></div>
          {isActive(selectedTask) && <div className="song-progress" role="status"><Spin /><p>{selectedTask.progress || '任务排队中，可离开页面，稍后在历史中查看。'}</p></div>}
          {selectedTask.status === 'failed' && <Alert type="error" message={selectedTask.error} action={<Button onClick={selectedTask.kind === 'import' ? () => setImportOpen(true) : () => void start(mode)}>{selectedTask.kind === 'import' ? '重新上传图片' : '按当前条件重新推荐'}</Button>} />}
          {selectedTask.status === 'cancelled' && <Alert type="info" message="任务已取消，未修改你的歌单。" />}
          {selectedTask.status === 'succeeded' && (selectedTask.kind === 'import' ? <ImportReview key={`${selectedTask.id}:${selectedTask.imported}`} task={selectedTask} client={client} playlists={library.playlists} busy={busy} onSave={async (tracks, target, newName) => { const ok = await mutate({ action: 'confirm', taskId: selectedTask.id, tracks, ...(target === 'new' ? { name: newName } : { playlistId: target }) }); if (ok) { setRefresh(v => v + 1); setInfo('截图中的歌曲已保存。'); } return ok; }} /> : <>
            <p className="song-muted">{selectedTask.result.notice}</p><div className="song-actions"><Button disabled={!selectedTask.result.tracks?.length} onClick={() => setResultIds(selectedTask.result.tracks!.map(t => t.id))}>全选结果</Button><Button disabled={!resultIds.length} onClick={() => setResultIds([])}>取消选择</Button><Button type="primary" disabled={!selectedResult.length || busy} onClick={() => openSave(selectedResult)}>保存所选 {selectedResult.length} 首</Button></div>
            {!selectedTask.result.tracks?.length && <Empty description="这次没有符合条件的新歌曲，试试其他流派或探索程度。" />}
            {selectedTask.result.tracks?.map(track => renderTrack(track, <Checkbox aria-label={`选择 ${track.title}`} checked={resultIds.includes(track.id)} onChange={event => setResultIds(old => event.target.checked ? [...old, track.id] : old.filter(id => id !== track.id))} />))}
          </>)}
        </section>}
        {!selectedTask && !manual && <div className="song-welcome"><ListMusic size={36} aria-hidden="true" /><h2>把熟悉的旋律，变成新的发现</h2><p>选择一个场景开始，或导入你珍藏的歌单截图。</p><span>识别后核对 · 反馈后更懂你 · 推荐可以追溯</span></div>}
      </>}
      {tab === 'library' && <section className="song-panel"><div className="song-section-heading"><div><h2>我的歌单</h2><p className="song-muted">{library.playlists.length} 张私人歌单 · 支持文字导出</p></div><Button type="primary" onClick={() => openSave([])} icon={<Plus size={16} aria-hidden="true" />}>新建歌单</Button></div>
        <div className="song-fields"><div className="song-field"><label htmlFor="song-playlist">选择或搜索歌单</label><Select id="song-playlist" showSearch optionFilterProp="label" value={playlistId || undefined} placeholder="选择歌单" onChange={value => { setPlaylistId(value); setSelectedIds([]); }} options={library.playlists.map(p => ({ value: p.id, label: p.name }))} /></div><div className="song-field"><label htmlFor="song-search">搜索歌名／歌手／专辑</label><Input id="song-search" value={search} onChange={event => setSearch(event.target.value)} allowClear /></div></div>
        {playlist ? <><div className="song-actions"><Button onClick={() => { setMode('similar'); navigate({ tab: 'discover' }); }}>推荐相似歌曲</Button><Button onClick={openManual}>添加歌曲</Button><Button disabled={busy} onClick={() => { setName(playlist.name); setRename(true); }}>重命名</Button><Button onClick={() => { const text = songText(playlist.tracks); if (!navigator.clipboard?.writeText) setCopyText(text); else void navigator.clipboard.writeText(text).then(() => setInfo('已复制歌曲清单。')).catch(() => setCopyText(text)); }}>复制清单</Button>{(['txt', 'csv'] as const).map(format => <Button key={format} disabled={busy} onClick={() => void runAction(async () => saveResearchBlob(await client.export(playlist.id, format), `${playlist.name}.${format}`))}>导出 {format.toUpperCase()}</Button>)}<Popconfirm title="删除整张歌单？" description="此操作不可恢复。" onConfirm={() => void mutate({ action: 'delete', playlistId: playlist.id }).then(ok => { if (ok) setPlaylistId(''); })}><Button danger disabled={busy}>删除歌单</Button></Popconfirm></div>
          <div className="song-section-heading"><p>{selectedIds.length ? `已选 ${selectedIds.length} 首` : `${playlist.tracks.length} 首歌曲`}</p><Button danger disabled={busy || !selectedIds.length} onClick={() => void mutate({ action: 'remove', playlistId: playlist.id, trackIds: selectedIds }).then(ok => { if (ok) setSelectedIds([]); })}>移除所选歌曲</Button></div>{!filteredTracks.length && <Empty description={search ? '没有匹配的歌曲。' : '歌单还是空的，添加几首喜欢的歌吧。'} />}
          {filteredTracks.map(track => renderTrack(track, <Checkbox aria-label={`选择 ${track.title}`} checked={selectedIds.includes(track.id)} onChange={event => setSelectedIds(old => event.target.checked ? [...old, track.id] : old.filter(id => id !== track.id))} />))}
        </> : <Empty description="创建或选择一张歌单，开始收集喜欢的歌曲。" />}
      </section>}
      {tab === 'history' && <><section className="song-panel"><h2>让推荐更懂你</h2>{prefs && <><div className="song-fields"><div className="song-field"><label htmlFor="song-pref-language">默认语言范围</label><Select id="song-pref-language" value={prefs.language} options={languages} onChange={value => setPrefs({ ...prefs, language: value })} /></div><div className="song-field"><label htmlFor="song-pref-exploration">默认探索程度</label><Select id="song-pref-exploration" value={prefs.exploration} options={exploration} onChange={value => setPrefs({ ...prefs, exploration: value })} /></div></div><div className="song-actions"><Checkbox checked={prefs.excludeHeard} onChange={event => setPrefs({ ...prefs, excludeHeard: event.target.checked })}>不再推荐听过的歌</Checkbox><Button type="primary" loading={busy} onClick={() => void mutate({ action: 'preferences', preferences: prefs }).then(ok => { if (ok) setInfo('偏好已保存，将用于后续推荐。'); })}>保存偏好</Button></div></>}
        <details><summary>我的反馈（{library.feedback.length} 条）</summary>{!library.feedback.length && <p className="song-muted">在歌曲卡片上标记喜欢、不感兴趣或听过了。</p>}{library.feedback.map(f => <div className="song-history-row" key={trackIdentity(f.track)}><span>{f.track.title} — {f.track.artist} · {feedbackLabels[f.value]}</span><Button disabled={busy} onClick={() => feedback(f.track, 'none')}>撤销</Button></div>)}</details></section>
        <section className="song-panel"><div className="song-section-heading"><h2>发现与导入历史</h2><Button onClick={() => setRefresh(v => v + 1)}>刷新历史</Button></div>{!tasks.length && <Empty description="推荐和识别任务会保存在这里。" />}{tasks.map(task => <div className="song-history-row" key={task.id}><div><strong>{task.kind === 'import' ? '歌单截图识别' : task.kind === 'similar' ? '相似歌曲推荐' : '流派与场景推荐'}</strong><p className="song-muted">{new Date(task.createdAt).toLocaleString('zh-CN')} · {statusLabels[task.status] || task.status}{task.imported ? ' · 已导入' : ''}</p><span>{task.progress}</span></div><div className="song-actions"><Button onClick={() => { setManual(false); navigate({ tab: 'discover', task: task.id }); }}>查看</Button>{isActive(task) && <Button disabled={busy} onClick={() => void runAction(() => client.cancel(task.id))}>取消</Button>}<Popconfirm title="删除任务及其原图？" description="已保存的歌单不受影响。" onConfirm={() => void runAction(async () => { await client.deleteTask(task.id); if (selectedTaskId === task.id) navigate({ task: '' }); })}><Button danger disabled={busy}>删除</Button></Popconfirm></div></div>)}<Pagination current={page} pageSize={20} total={taskCount} showSizeChanger={false} hideOnSinglePage onChange={setPage} /></section>
      </>}
    </>}
    {jsonOpen && <JsonPlaylistImport onClose={() => setJsonOpen(false)} onReady={draft => { setJsonDraft(draft); setJsonOpen(false); setManual(true); setManualKey(v => v + 1); navigate({ tab: 'discover', task: '' }); }} />}
    <Modal className="song-modal" title="导入歌单截图" open={importOpen} onCancel={() => !uploading && !busy && setImportOpen(false)} footer={null}>
      <p>01 上传截图 → 02 核对歌曲 → 03 保存歌单</p><div className="song-upload" tabIndex={0} onPaste={event => { const files = Array.from(event.clipboardData.files); if (files.length) { event.preventDefault(); void uploadFiles(files); } }}><ScanLine size={32} aria-hidden="true" /><label htmlFor="song-images">选择图片，或聚焦此区域粘贴截图</label><input id="song-images" type="file" multiple accept="image/png,image/jpeg,image/webp" disabled={uploading || busy || images.length >= 5} onChange={event => { void uploadFiles(Array.from(event.target.files || [])); event.target.value = ''; }} /><p className="song-muted">最多 5 张 · 单张 20 MB · PNG / JPEG / WebP</p></div>
      {images.map((image, i) => <div className="song-upload-row" key={i}><span>{image.file.name} · {image.id ? '已上传' : image.error || '上传中…'}</span><div className="song-actions">{image.error && <Button disabled={uploading} onClick={() => void uploadFiles([image.file], true)}>重试上传</Button>}<Button disabled={uploading || busy} onClick={() => void runAction(async () => { if (image.id) await client.deleteImage(image.id); setImages(old => old.filter(item => item !== image)); })}>移除</Button></div></div>)}
      {error && <Alert type="error" message={error} />}<div className="song-actions"><Button type="primary" loading={busy || uploading} disabled={!images.length || images.some(i => !i.id)} onClick={() => void start('import')}>识别歌单</Button><Button disabled={busy || uploading} onClick={() => { setImportOpen(false); openManual(); }}>改用文字／手动录入</Button></div>
    </Modal>
    <Modal className="song-modal" title={saveTracks?.length ? `保存 ${saveTracks.length} 首歌曲` : '新建歌单'} open={saveTracks !== null} confirmLoading={busy} onCancel={() => !busy && setSaveTracks(null)} okText="保存" okButtonProps={{ disabled: saveTarget === 'new' && !name.trim() }} onOk={() => void mutate({ action: saveTarget === 'new' ? 'create' : 'add', tracks: saveTracks || [], ...(saveTarget === 'new' ? { name: name.trim() } : { playlistId: saveTarget }) }).then(ok => { if (ok) { setSaveTracks(null); setInfo('已保存到歌单。'); } })}>
      {!!saveTracks?.length && <div className="song-field"><label htmlFor="song-save-target">保存到</label><Select id="song-save-target" value={saveTarget} onChange={setSaveTarget} options={[{ value: 'new', label: '新建歌单' }, ...(library?.playlists || []).map(p => ({ value: p.id, label: p.name }))]} /></div>}{saveTarget === 'new' && <div className="song-field"><label htmlFor="song-save-name">歌单名称</label><Input id="song-save-name" maxLength={120} value={name} onChange={event => setName(event.target.value)} /></div>}{error && <Alert type="error" message={error} />}
    </Modal>
    <Modal className="song-modal" title="重命名歌单" open={rename} onCancel={() => !busy && setRename(false)} confirmLoading={busy} okText="保存" okButtonProps={{ disabled: !name.trim() }} onOk={() => void mutate({ action: 'rename', playlistId, name: name.trim() }).then(ok => { if (ok) setRename(false); })}><label htmlFor="song-rename">歌单名称</label><Input id="song-rename" maxLength={120} value={name} onChange={event => setName(event.target.value)} />{error && <Alert type="error" message={error} />}</Modal>
    <Modal className="song-modal" title="复制歌曲清单" open={!!copyText} onCancel={() => setCopyText('')} footer={null}><p>当前浏览器无法自动复制，请全选下方文字后复制。</p><Input.TextArea aria-label="歌曲清单" value={copyText} readOnly rows={10} onFocus={event => event.target.select()} /></Modal>
  </div></main>;
}

export default function SongCuratorPage() {
  const { applicationId } = useParams<{ applicationId: string }>();
  const organizationId = useOrganizationStore(s => s.currentOrganizationId); const userId = useAuthStore(s => s.user?.id);
  if (!applicationId || !organizationId || !userId) return <Empty description="请选择组织并登录。" />;
  return <SongWorkspace key={`${organizationId}:${applicationId}:${userId}`} base={`${tenantApiRoot(organizationId)}/applications/${applicationId}/song-curator`} />;
}
