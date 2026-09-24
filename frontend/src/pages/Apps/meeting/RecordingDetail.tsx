import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Alert, Button, Checkbox, Empty, Input, Modal, Popconfirm, Select, Space, Tabs, Tag } from 'antd';
import { Check, FileText, ListTodo, Pencil, Play, RotateCcw, Trash2 } from 'lucide-react';
import { activeMeeting, meetingError, meetingStatus, timeLabel, type Evidence, type MeetingAction, type MeetingClient, type MeetingRecord, type TranscriptSegment } from '@/services/meetingAssistant';

export function RecordingDetail({ client, record, onChange, onDelete, onDirty }: {
  client: MeetingClient; record: MeetingRecord; onChange: (record: MeetingRecord) => void; onDelete: () => void; onDirty: (dirty: boolean) => void;
}) {
  const [tab, setTab] = useState('topics');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [url, setUrl] = useState('');
  const [audioError, setAudioError] = useState('');
  const [currentTime, setCurrentTime] = useState(0);
  const [speed, setSpeed] = useState(1);
  const [selected, setSelected] = useState<string[]>([]);
  const [edit, setEdit] = useState<TranscriptSegment | null>(null);
  const [action, setAction] = useState<MeetingAction | null>(null);
  const [metadata, setMetadata] = useState<{ title: string; kind: string; recorded_on: string } | null>(null);
  const [exported, setExported] = useState<{ application_id: number; document_id: string } | null>(null);
  const [todosApp, setTodosApp] = useState<number | null>(null);
  const audio = useRef<HTMLAudioElement>(null);
  const pendingSeek = useRef<number | null>(null);
  const resumePlayback = useRef(false);
  const exportKeys = useRef<Record<string, string>>({});
  const running = activeMeeting(record.status);
  const stale = record.analysis_version !== record.version;
  const dirty = !!edit || !!action || !!metadata;
  const candidatesKey = record.actions.map(item => `${item.id}:${item.revision}:${item.confirmed_at}`).join('|');
  useEffect(() => { onDirty(dirty); return () => onDirty(false); }, [dirty, onDirty]);
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => { if (dirty) { event.preventDefault(); event.returnValue = ''; } };
    window.addEventListener('beforeunload', warn); return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);
  useEffect(() => { setSelected([]); }, [record.version, record.analysis_version, candidatesKey]);
  const loadAudio = useCallback(async () => {
    try {
      const access = await client.access(record.id);
      if (audio.current) { pendingSeek.current = audio.current.currentTime; resumePlayback.current = !audio.current.paused; }
      setUrl(access.url); setAudioError('');
    } catch (e) { setAudioError(meetingError(e)); }
  }, [client, record.id]);
  useEffect(() => {
    let alive = true;
    void client.access(record.id).then(value => { if (alive) setUrl(value.url); }).catch(e => { if (alive) setAudioError(meetingError(e)); });
    const timer = setInterval(() => { if (alive) void loadAudio(); }, 50 * 60 * 1000);
    return () => { alive = false; clearInterval(timer); };
  }, [client, record.id, loadAudio]);
  const perform = async (work: () => Promise<void>) => {
    setBusy(true); setError('');
    try { await work(); } catch (e) { setError(meetingError(e)); } finally { setBusy(false); }
  };
  const seek = (id: string) => {
    const segment = record.segments.find(value => value.id === id);
    if (!segment) return;
    setTab('transcript'); setCurrentTime(segment.start);
    if (audio.current && audio.current.readyState >= 1) audio.current.currentTime = segment.start;
    else pendingSeek.current = segment.start;
    // Tab panels mount after state changes; the next frame locates the source.
    requestAnimationFrame(() => document.getElementById(`meeting-segment-${id}`)?.scrollIntoView?.({ block: 'center' }));
  };
  const refs = (ids: string[]) => <span className="meeting-references">{ids.map(id => {
    const segment = record.segments.find(value => value.id === id);
    return segment && <button type="button" key={id} onClick={() => seek(id)} aria-label={`回听 ${timeLabel(segment.start)}`}><Play size={12} aria-hidden="true" />{timeLabel(segment.start)}</button>;
  })}</span>;
  const evidence = (values: Evidence[] = []) => values.length ? <ul className="meeting-evidence">{values.map((value, i) => <li key={i}><p>{value.text}</p>{refs(value.segment_ids)}</li>)}</ul> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={record.analysis_version ? '暂无明确内容' : '分析完成后会显示在这里'} />;
  const exportDocument = (kind: string) => void perform(async () => {
    const identity = `${record.version}:${kind}`;
    exportKeys.current[identity] ||= crypto.randomUUID();
    const result = await client.document(record.id, record.version, kind, exportKeys.current[identity]);
    setExported(result);
  });
  const actions = <section>
    <div className="meeting-action-intro"><div><h3>确认后再安排</h3><p className="meeting-muted">核对事项、优先级和日期，再将选中项加入你的待办。</p></div>
      <Button type="primary" icon={<ListTodo size={16} aria-hidden="true" />} disabled={!selected.length || running || stale || busy} onClick={() => void perform(async () => {
        const result = await client.confirm(record.id, record.version, record.actions.filter(item => selected.includes(item.id)));
        setTodosApp(result.application_id); setSelected([]); onChange(await client.get(record.id));
      })}>确认加入待办{selected.length ? `（${selected.length}）` : ''}</Button></div>
    {todosApp && <Alert type="success" message={<span>已加入待办。<Link to={`/applications/${todosApp}/ideas-todos`}>打开我的待办</Link></span>} />}
    {!record.actions.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有明确的行动项" />}
    <ul className="meeting-evidence">{record.actions.map(item => <li key={item.id}>
      <div className="meeting-action-heading"><Checkbox aria-label={`选择行动项：${item.title}`} checked={selected.includes(item.id)} disabled={!!item.confirmed_at || running || stale || busy} onChange={e => setSelected(old => e.target.checked ? [...old, item.id] : old.filter(id => id !== item.id))} /><strong>{item.title}</strong>
        {item.confirmed_at ? <Tag icon={<Check size={12} aria-hidden="true" />}>已确认{!item.todo_id ? '（待办已删除）' : ''}</Tag> : <Button type="text" disabled={running || stale || busy} onClick={() => setAction({ ...item })}>编辑</Button>}</div>
      <p>{item.description}</p><Space wrap><Tag>{['', '低', '中', '高'][item.priority]}优先级</Tag><span className="meeting-muted">{item.due_date || '未设截止日期'}</span>{refs(item.segment_ids)}</Space>
    </li>)}</ul>
  </section>;
  const transcript = <section><div className="meeting-section-title"><h3>逐字稿</h3><span className="meeting-muted">点击时间点回听，校对不改变原始录音</span></div>
    {!record.segments.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="转录完成后会显示在这里" />}
    <ol className="meeting-transcript">{record.segments.map(segment => <li id={`meeting-segment-${segment.id}`} key={segment.id} className={currentTime >= segment.start && currentTime < segment.end ? 'is-current' : ''}>
      {refs([segment.id])}<p>{segment.text || '（此段文字已清空）'}</p><Button type="text" aria-label={`校对 ${timeLabel(segment.start)}`} icon={<Pencil size={15} aria-hidden="true" />} disabled={running || busy} onClick={() => setEdit({ ...segment })} />
    </li>)}</ol></section>;
  const material = <section>{([['viewpoints', '主题观点'], ['quotes', '原话引用'], ['facts', '事实素材'], ['outline', '文章提纲']] as const).map(([key, title]) => <section key={key}><h3>{title}</h3>{evidence(record.analysis[key])}</section>)}</section>;
  return <article className="meeting-detail" aria-label="录音详情">
    <header className="meeting-detail-header"><div><div className="meeting-eyebrow"><Tag>{record.kind === 'meeting' ? '会议' : '访谈'}</Tag><span>{record.recorded_on}</span></div><h2>{record.title}</h2>
      <p className="meeting-muted">{record.filename} · {timeLabel(record.duration)} · 仅自己可见</p></div>
      <Space><Button aria-label="刷新录音详情" icon={<RotateCcw size={16} aria-hidden="true" />} disabled={busy || dirty} onClick={() => void perform(async () => onChange(await client.get(record.id)))} />
        <Button aria-label="编辑录音信息" icon={<Pencil size={16} aria-hidden="true" />} disabled={running || busy} onClick={() => setMetadata({ title: record.title, kind: record.kind, recorded_on: record.recorded_on })} />
        <Popconfirm title="删除此录音及分析结果？" description="已保存的文档和待办将保留。" onConfirm={() => perform(async () => { await client.remove(record.id); onDelete(); })} okText="删除" cancelText="取消"><Button danger aria-label="删除录音" disabled={busy} icon={<Trash2 size={16} aria-hidden="true" />} /></Popconfirm></Space>
    </header>
    <div className="meeting-state" role="status" aria-live="polite"><span className={running ? 'meeting-pulse' : ''} /><strong>{meetingStatus[record.status] || record.status}</strong>
      {running ? <Button size="small" disabled={record.status === 'cancelling' || busy} onClick={() => void perform(async () => onChange(await client.cancel(record.id)))}>取消处理</Button> : <Button size="small" icon={<RotateCcw size={13} aria-hidden="true" />} disabled={busy} onClick={() => void perform(async () => {
        await client.run(record.id, record.version, record.segments.length ? 'analyze' : 'process', crypto.randomUUID()); onChange(await client.get(record.id));
      })}>{record.segments.length ? '重新分析' : '重试转录'}</Button>}</div>
    {(error || record.error) && <Alert type="error" message={error || record.error} showIcon role="alert" />}
    {record.stale && <Alert type="warning" message="逐字稿或录音信息已修改，以下分析来自旧版本。请重新分析后再导出或确认行动项。" showIcon />}
    <section className="meeting-player" aria-label="录音播放器"><audio ref={audio} controls preload="metadata" src={url || undefined} onTimeUpdate={e => setCurrentTime(e.currentTarget.currentTime)} onError={() => setAudioError('音频加载失败或浏览器不支持此格式。可刷新链接，或将原文件转换为 MP3 后重新上传。')}
      onLoadedMetadata={e => {
        e.currentTarget.playbackRate = speed;
        if (pendingSeek.current !== null) { e.currentTarget.currentTime = pendingSeek.current; pendingSeek.current = null; }
        if (resumePlayback.current) { resumePlayback.current = false; void e.currentTarget.play().catch(() => setAudioError('链接已刷新，点击播放继续回听。')); }
      }} />
      <Select aria-label="播放速度" value={speed} onChange={value => { setSpeed(value); if (audio.current) audio.current.playbackRate = value; }} options={[0.75, 1, 1.25, 1.5, 2].map(value => ({ value, label: `${value}×` }))} />
    </section>
    {audioError && <Alert type="warning" message={audioError} action={<Button onClick={() => void loadAudio()}>刷新链接</Button>} />}
    <div className="meeting-exports"><span className="meeting-muted"><FileText size={15} aria-hidden="true" />保存到在线文档</span><Space wrap>
      <Button disabled={!record.segments.length || busy} onClick={() => exportDocument('transcript')}>逐字稿</Button>
      <Button disabled={stale || busy || running} onClick={() => exportDocument('minutes')}>会议纪要</Button>
      {record.kind === 'interview' && <Button disabled={stale || busy || running} onClick={() => exportDocument('materials')}>访谈素材包</Button>}</Space></div>
    {exported && <Alert type="success" message={<span>文档已保存。<Link to={`/applications/${exported.application_id}/documents?document=${exported.document_id}`}>打开文档继续编辑</Link></span>} />}
    <Tabs activeKey={tab} onChange={setTab} items={[{ key: 'topics', label: '主题摘要', children: evidence(record.analysis.topics) }, { key: 'transcript', label: '逐字稿', children: transcript },
      { key: 'decisions', label: '决策', children: evidence(record.analysis.decisions) }, { key: 'actions', label: `行动项${record.actions.length ? ` · ${record.actions.length}` : ''}`, children: actions },
      ...(record.kind === 'interview' ? [{ key: 'materials', label: '文章素材', children: material }] : [])]} />
    <Modal open={!!edit} title="校对逐字稿" onCancel={() => setEdit(null)} confirmLoading={busy} onOk={() => edit && void perform(async () => { onChange(await client.saveTranscript(record.id, record.version, [{ id: edit.id, text: edit.text }])); setEdit(null); })} okText="保存校对" cancelText="取消">
      {edit && <div className="meeting-form"><p className="meeting-muted">原始转录：{edit.original_text}</p><label>校对文字<Input.TextArea rows={7} maxLength={6000} value={edit.text} onChange={e => setEdit({ ...edit, text: e.target.value })} /></label>{error && <Alert type="error" message={error} />}</div>}
    </Modal>
    <Modal open={!!action} title="编辑候选行动项" onCancel={() => setAction(null)} confirmLoading={busy} onOk={() => action && void perform(async () => { await client.saveAction(record.id, record.version, action); onChange(await client.get(record.id)); setAction(null); })} okText="保存候选项" cancelText="取消">
      {action && <div className="meeting-form"><label>标题<Input value={action.title} maxLength={200} onChange={e => setAction({ ...action, title: e.target.value })} /></label><label>描述及原文负责人<Input.TextArea rows={4} value={action.description} maxLength={18000} onChange={e => setAction({ ...action, description: e.target.value })} /></label>
        <div className="meeting-form-row"><label>优先级<Select aria-label="行动项优先级" value={action.priority} onChange={priority => setAction({ ...action, priority })} options={[{ value: 1, label: '低' }, { value: 2, label: '中' }, { value: 3, label: '高' }]} /></label><label>截止日期<Input type="date" value={action.due_date || ''} onChange={e => setAction({ ...action, due_date: e.target.value || null })} /></label></div>
        <p className="meeting-muted">保存候选项不会创建待办，仍需勾选并确认。</p>{error && <Alert type="error" message={error} />}</div>}
    </Modal>
    <Modal open={!!metadata} title="录音信息" onCancel={() => setMetadata(null)} confirmLoading={busy} onOk={() => metadata && void perform(async () => { onChange(await client.saveMetadata(record.id, record.version, metadata)); setMetadata(null); })} okText="保存" cancelText="取消">
      {metadata && <div className="meeting-form"><label>标题<Input value={metadata.title} maxLength={200} onChange={e => setMetadata({ ...metadata, title: e.target.value })} /></label><label>类型<Select aria-label="修改录音类型" value={metadata.kind} onChange={kind => setMetadata({ ...metadata, kind })} options={[{ value: 'meeting', label: '会议' }, { value: 'interview', label: '访谈' }]} /></label><label>录音日期<Input type="date" value={metadata.recorded_on} onChange={e => setMetadata({ ...metadata, recorded_on: e.target.value })} /></label>{error && <Alert type="error" message={error} />}</div>}
    </Modal>
  </article>;
}
