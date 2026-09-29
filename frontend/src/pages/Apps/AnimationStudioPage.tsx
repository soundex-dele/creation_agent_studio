import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { Alert, Button, Empty, InputNumber, Pagination, Select, Spin } from 'antd';
import { ArrowLeft, ArrowUpRight, Check, Clapperboard, Code2, Download, Film, Layers, Plus, Sparkles, Upload, X } from 'lucide-react';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { resolveApplicationPresentation } from '@/lib/applicationPresentation';
import { tenantApiRoot } from '@/services/tenantContext';
import { createApplicationRuntimeClient, type ApplicationRuntimeClient, type RunArtifact } from '@/services/applicationRuntime';
import { activeExport, animationApi, animationArtifact, animationError, animationStatus, animationTerminal, completedExport,
  type AnimationAspect, type AnimationAsset, type AnimationGeneration, type AnimationInput, type AnimationRun } from '@/services/animationStudio';
import './AnimationStudioPage.css';
import AnimationStudioEditor from './animation/AnimationStudioEditor';
import AnimationTaskDetails from './animation/AnimationTaskDetails';

const EXAMPLES = [
  { title: '知识讲解', text: '用 30 秒讲清楚番茄工作法：专注 25 分钟、休息 5 分钟，用简洁的时钟和进度动画辅助说明。' },
  { title: '流程演示', text: '制作一个从灵感到发布的创作流程动画，依次展示收集灵感、整理提纲、完成初稿、修改发布四个步骤。' },
  { title: '数据解读', text: '用一组演示数据制作柱状图动画：第一季度 20、第二季度 35、第三季度 50。标明这是示例数据，突出逐步增长。' },
];

export function AnimationPreview({ runtime, generation }: { runtime: ApplicationRuntimeClient; generation: AnimationGeneration }) {
  const exported = completedExport(generation);
  const video = animationArtifact(exported, 'animation-video');
  const preview = animationArtifact(generation, 'animation-preview');
  const artifact = video || preview;
  const artifactId = artifact?.id;
  const isVideo = Boolean(video);
  const runId = video ? exported!.id : generation.id;
  const [content, setContent] = useState<{ key: string; value: string }>();
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);
  const key = `${runId}:${artifact?.id}`;
  useEffect(() => {
    setContent(undefined); setError('');
    if (!artifactId) return;
    const controller = new AbortController();
    let objectUrl = '';
    void (async () => {
      const access = await runtime.getArtifactAccess(runId, artifactId);
      if (controller.signal.aborted) return;
      const response = await fetch(access.url, { signal: controller.signal });
      if (!response.ok) throw new Error('预览文件不可用，请重新加载。');
      // MP4 is fetched as a Blob so seeking works even when storage serves attachment-only responses.
      const value = isVideo ? (objectUrl = URL.createObjectURL(await response.blob())) : await response.text();
      if (!controller.signal.aborted) setContent({ key, value });
      else if (objectUrl) URL.revokeObjectURL(objectUrl);
    })().catch(e => {
      if (!controller.signal.aborted) setError(e instanceof TypeError
        ? '无法连接预览文件，请检查网络后重新加载。' : animationError(e));
    });
    return () => { controller.abort(); if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [runtime, key, runId, artifactId, isVideo, reload]);
  if (!artifact) return <div className="animation-placeholder"><Clapperboard size={48} strokeWidth={1} /><h3>让想法动起来</h3><p>填写内容后生成 HTML 动画，满意后再导出视频。</p></div>;
  if (error) return <div className="animation-placeholder" role="alert"><p>{error}</p><Button onClick={() => setReload(value => value + 1)}>重新加载预览</Button></div>;
  if (!content || content.key !== key) return <Spin tip="正在加载预览"><div style={{ height: 100 }} /></Spin>;
  return video ? <video key={key} src={content.value} controls playsInline preload="metadata" aria-label="MP4 视频预览" onError={() => setError('视频播放失败，请重新加载或下载查看。')} />
    : <iframe key={key} title="HTML 动画预览" sandbox="allow-scripts" referrerPolicy="no-referrer" srcDoc={content.value} />;
}

export function AnimationStudioWorkspace({ organizationId, applicationId, initialRunId, showHeader = true, onSelect }: {
  organizationId: string; applicationId: string; initialRunId?: string; showHeader?: boolean; onSelect?: (id: string) => void;
}) {
  const client = useMemo(() => animationApi(`${tenantApiRoot(organizationId)}/applications/${applicationId}/animation-studio`), [organizationId, applicationId]);
  const runtime = useMemo(() => createApplicationRuntimeClient({ organizationId, applicationId }), [organizationId, applicationId]);
  const [prompt, setPrompt] = useState('');
  const [aspect, setAspect] = useState<AnimationAspect>('16:9');
  const [duration, setDuration] = useState(30);
  const [style, setStyle] = useState('简洁清晰，注重信息层次');
  const [assets, setAssets] = useState<AnimationAsset[]>([]);
  const [source, setSource] = useState<AnimationGeneration>();
  const [selected, setSelected] = useState<AnimationGeneration>();
  const [records, setRecords] = useState<AnimationGeneration[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [refresh, setRefresh] = useState(0);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState('');
  const [listError, setListError] = useState('');
  const [connectionError, setConnectionError] = useState('');
  const [stage, setStage] = useState('');
  const [detailedRun, setDetailedRun] = useState<AnimationRun>();
  const [tab, setTab] = useState(initialRunId ? 'preview' : 'create');
  const initialized = useRef(false);
  const selection = useRef(0);
  const submitting = useRef(false);
  const uploadingRef = useRef(false);
  const mounted = useRef(true);
  const pending = useRef<{ fingerprint: string; key: string }>();
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const currentId = selected?.id;
  const exporting = activeExport(selected);
  const generating = selected && !animationTerminal(selected.status) ? selected : undefined;
  const active = generating || exporting;
  const activeId = active?.id;
  const choose = useCallback((run: AnimationGeneration) => { setSelected(run); setStage(''); setConnectionError(''); onSelect?.(run.id); }, [onSelect]);

  useEffect(() => { mounted.current = true; return () => { mounted.current = false; selection.current += 1; }; }, []);
  useEffect(() => {
    let alive = true; setLoading(true); setListError('');
    const token = selection.current;
    void client.list(page).then(async result => {
      if (!alive) return;
      setRecords(result.results); setTotal(result.count);
      if (!initialized.current) {
        const first = initialRunId ? await client.get(initialRunId) : result.results[0];
        if (alive && selection.current === token) { initialized.current = true; if (first) choose(first); }
      }
    }).catch(e => { if (alive) setListError(animationError(e)); }).finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [client, page, refresh, initialRunId, choose]);

  useEffect(() => {
    if (!currentId || !activeId) return;
    let alive = true; let fetching = false;
    const reload = async () => {
      if (fetching) return; fetching = true;
      try {
        const value = await client.get(currentId);
        if (alive) {
          setSelected(value);
          if (animationTerminal(value.status) && !activeExport(value)) { setStage(''); setRefresh(n => n + 1); }
        }
      } catch (e) { if (alive) setConnectionError(animationError(e)); }
      finally { fetching = false; }
    };
    const stream = runtime.subscribeRun(activeId, {
      onEvent: async event => {
        if (!alive) return;
        if (event.type === 'progress.updated') setStage(String(event.payload.stage || ''));
        if (event.type.startsWith('run.') || event.type === 'artifact.created') await reload();
      }, onSnapshot: reload,
      onError: () => { if (alive) setConnectionError('实时连接中断，正在自动刷新任务状态。'); },
      onConnectionChange: connected => { if (alive && connected) setConnectionError(''); },
    });
    const timer = setInterval(() => void reload(), 5000);
    return () => { alive = false; stream.abort(); clearInterval(timer); };
  }, [client, runtime, currentId, activeId]);

  const open = async (id: string) => {
    const token = ++selection.current; setError('');
    try { const value = await client.get(id); if (mounted.current && selection.current === token) { choose(value); setTab('preview'); } }
    catch (e) { if (mounted.current && selection.current === token) setError(animationError(e)); }
  };
  const upload = async (file: File) => {
    if (uploadingRef.current) return;
    const image = /\.(png|jpe?g|webp)$/i.test(file.name);
    if (file.size > (image ? 20 : 50) * 1024 * 1024) { setError(image ? '图片不能超过 20 MB。' : '录音不能超过 50 MB。'); return; }
    if (assets.length >= 10) { setError('每部动画最多使用 10 个素材。'); return; }
    uploadingRef.current = true; setUploading(true); setError('');
    try {
      const asset = await client.upload(file);
      if (mounted.current) setAssets(current => [...(asset.duration === null ? current : current.filter(item => item.duration === null)), asset]);
    } catch (e) { if (mounted.current) setError(animationError(e)); }
    finally { uploadingRef.current = false; if (mounted.current) setUploading(false); }
  };
  const perform = async (body?: AnimationInput) => {
    if (submitting.current || uploadingRef.current) return;
    const target = selected;
    if (!body && !target) return;
    const fingerprint = JSON.stringify(body || { export: target!.id });
    if (pending.current?.fingerprint !== fingerprint) pending.current = { fingerprint, key: crypto.randomUUID() };
    submitting.current = true; setBusy(true); setError(''); const token = ++selection.current;
    try {
      if (body) {
        const run = await client.generate(body, pending.current.key);
        if (mounted.current && selection.current === token) { choose(run); setSource(undefined); setAssets([]); setPrompt(''); setTab('preview'); setPage(1); }
      } else {
        const run = await client.export(target!.id, pending.current.key);
        if (mounted.current && selection.current === token) { setSelected({ ...target!, exports: [run, ...target!.exports.filter(item => item.id !== run.id)] }); setStage(''); }
      }
      pending.current = undefined;
      if (mounted.current) setRefresh(n => n + 1);
    } catch (e) { if (mounted.current) setError(animationError(e)); }
    finally { submitting.current = false; if (mounted.current) setBusy(false); }
  };
  const generate = () => {
    if (!prompt.trim()) { setError('请填写动画内容或修改要求。'); inputRef.current?.focus(); return; }
    void perform({ prompt: prompt.trim(), aspect, duration, style, asset_ids: assets.map(item => item.id), ...(source ? { source_run_id: source.id } : {}) });
  };
  const edit = () => {
    if (!selected) return;
    setSource(selected); setPrompt(''); setAssets([]); setAspect(selected.input.aspect); setDuration(selected.input.duration); setStyle(selected.input.style); setTab('create'); inputRef.current?.focus();
  };
  const cancel = async () => {
    if (!active || !selected) return;
    const id = selected.id; const token = selection.current; setBusy(true); setError('');
    try {
      await runtime.sendCommand(active.id, { type: 'cancel', idempotency_key: crypto.randomUUID() });
      const value = await client.get(id); if (mounted.current && token === selection.current) setSelected(value);
    } catch (e) { if (mounted.current) setError(animationError(e)); }
    finally { if (mounted.current) setBusy(false); }
  };
  const download = async (run: AnimationRun, artifact: RunArtifact) => {
    try {
      const access = await runtime.getArtifactAccess(run.id, artifact.id);
      const response = await fetch(access.url); if (!response.ok) throw new Error('下载失败，请重试。');
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement('a'); link.href = url; link.download = String(artifact.metadata.filename || (artifact.kind === 'animation-video' ? 'animation.mp4' : 'animation-source.zip')); link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) { if (mounted.current) setError(animationError(e)); }
  };
  const exported = completedExport(selected);
  const video = animationArtifact(exported, 'animation-video');
  const sourceArtifact = animationArtifact(selected, 'animation-source');
  const lastExport = selected?.exports[0];
  const previewArtifact = animationArtifact(selected, 'animation-preview');
  const dimensions = previewArtifact?.metadata;
  const ready = selected?.status === 'succeeded' && Boolean(previewArtifact);
  return <section className="animation-workspace" data-tab={tab} aria-label="动画制作工作台">
    <header className="animation-header">
      <div className="animation-brand">{showHeader && <Link to="/apps" aria-label="返回应用"><ArrowLeft size={20} /></Link>}<span className="animation-logo"><Clapperboard size={23} /></span><div><h1>动画制作</h1><p>把想法，变成会动的画面</p></div></div>
      <span className="animation-pipeline"><span>01 创作</span><i /><span>02 HTML 预览</span><i /><span>03 MP4 导出</span></span>
    </header>
    <nav className="animation-mobile-tabs" aria-label="工作台面板">{[['create', '制作'], ['preview', '预览'], ['history', '作品']].map(([id, label]) => <button key={id} aria-current={tab === id ? 'page' : undefined} onClick={() => setTab(id)}>{label}</button>)}</nav>
    {error && <Alert className="animation-error" type="error" showIcon message={error} closable onClose={() => setError('')} />}
    <div className="animation-body">
      <aside className="animation-form">
        <div className="animation-section-title"><h2>{source ? '继续打磨' : '开始一个想法'}</h2><Sparkles size={18} /></div>
        {source && <div className="animation-editing"><Layers size={16} /><span>基于「{String(source.output_summary.title || source.input.prompt).slice(0, 40)}」修改，原版本保留</span><button aria-label="取消版本修改" onClick={() => setSource(undefined)}><X size={16} /></button></div>}
        <label htmlFor="animation-prompt">{source ? '想调整哪些地方？' : '动画内容'}</label>
        <textarea id="animation-prompt" ref={inputRef} value={prompt} onChange={e => setPrompt(e.target.value)} maxLength={16000} rows={7} placeholder={source ? '例如：让第二个场景更慢一些，把主色改成蓝色…' : '描述主题，或粘贴一段文案。AI 会为你编排画面、节奏和转场。'} />
        {!source && <div className="animation-examples">{EXAMPLES.map(item => <button key={item.title} onClick={() => setPrompt(item.text)}>{item.title}<ArrowUpRight size={12} /></button>)}</div>}
        <div className="animation-fields"><div><label htmlFor="animation-aspect">画面比例</label><Select id="animation-aspect" value={aspect} onChange={setAspect} options={[{ value: '16:9', label: '16:9 横版' }, { value: '9:16', label: '9:16 竖版' }, { value: '1:1', label: '1:1 方形' }]} /></div><div><label htmlFor="animation-duration">时长（秒）</label><InputNumber id="animation-duration" min={5} max={120} precision={0} value={duration} onChange={value => setDuration(value || 30)} /></div></div>
        <label htmlFor="animation-style">视觉风格</label><input id="animation-style" value={style} onChange={e => setStyle(e.target.value)} maxLength={1000} placeholder="例如：极简、科技感、温暖手绘" />
        <label className="animation-upload"><Upload size={19} /><strong>{uploading ? '正在上传素材…' : '添加图片或录音'}</strong><span>图片 ≤20 MB · 录音 ≤50 MB</span><input aria-label="上传动画素材" type="file" accept=".png,.jpg,.jpeg,.webp,.mp3,.wav,.m4a" disabled={uploading || busy} onChange={e => { const file = e.target.files?.[0]; if (file) void upload(file); e.target.value = ''; }} /></label>
        {assets.length > 0 && <ul className="animation-assets">{assets.map(item => <li key={item.id}><span>{item.name}{item.duration !== null ? ` · ${item.duration.toFixed(1)} 秒` : ''}</span><button aria-label={`移除 ${item.name}`} onClick={() => setAssets(items => items.filter(value => value.id !== item.id))}><X size={14} /></button></li>)}</ul>}
        <p className="animation-hint">默认无声。添加录音后按实测时长编排；修改版本会保留原素材，新录音替换旧录音。</p>
        <Button type="primary" size="large" icon={<Sparkles size={17} />} loading={busy} disabled={uploading || Boolean(generating)} onClick={generate}>{source ? '生成新版本' : '生成 HTML 预览'}</Button>
        <p className="animation-footnote"><Check size={13} />先看效果，满意后再导出 MP4</p>
      </aside>
      <main className="animation-results">
        <div className="animation-section-title animation-preview-heading"><div><span className="animation-eyebrow">YOUR ANIMATION</span><h2>{String(selected?.output_summary.title || '创作预览')}</h2></div><div className="animation-preview-tools"><span className={`animation-format ${video ? 'is-video' : ''}`}>{video ? 'MP4' : 'HTML'}</span>{ready && <Button type="primary" disabled={busy} onClick={edit}>继续修改</Button>}</div></div>
        {connectionError && <Alert type="warning" message={connectionError} />}
        {active && <div className="animation-progress" role="status"><Spin size="small" /><span>{animationStatus(active.status, stage || (exporting ? 'rendering' : ''))}</span><Button size="small" onClick={() => setDetailedRun(active)}>详情</Button><Button size="small" disabled={busy || active.status === 'cancelling'} onClick={() => void cancel()}>取消任务</Button></div>}
        <div className="animation-canvas" style={{ aspectRatio: dimensions ? `${dimensions.width} / ${dimensions.height}` : aspect.replace(':', ' / ') }}>
          {selected ? <AnimationPreview generation={selected} runtime={runtime} /> : <div className="animation-placeholder"><div className="animation-placeholder-mark"><Film size={40} strokeWidth={1.3} /></div><h3>从一句话，到一段动画</h3><p>知识、流程、数据，都可以有更生动的表达。</p><span>HTML 实时预览 · 自由修改 · 高清导出</span></div>}
        </div>
        {dimensions && <div className="animation-specs"><span>{String(dimensions.width)} × {String(dimensions.height)}</span><span>30 fps</span><span>{(Number(dimensions.durationInFrames) / 30).toFixed(1)} 秒</span><span>{dimensions.audioId ? '已有录音' : '无声动画'}</span></div>}
        {(selected?.error_message || lastExport?.error_message) && <Alert type="error" showIcon message={selected?.error_message || lastExport?.error_message} />}
        {lastExport?.status === 'cancelled' && <Alert type="info" message="导出已取消，HTML 预览与源码仍保留。" />}
        <div className="animation-actions">
          {selected && ['failed', 'cancelled'].includes(selected.status) && <Button disabled={busy} onClick={() => void perform(selected.input)}>重试生成</Button>}
          {selected && sourceArtifact && <Button icon={<Code2 size={16} />} onClick={() => void download(selected, sourceArtifact)}>下载源码</Button>}
          {video && exported ? <Button type="primary" icon={<Download size={16} />} onClick={() => void download(exported, video)}>下载 MP4</Button> : <Button type="primary" icon={<Film size={16} />} disabled={!ready || Boolean(exporting) || busy} onClick={() => void perform()}>导出 MP4</Button>}
        </div>
        {selected && <details className="animation-details"><summary>创作说明与版本</summary><p>{selected.input.prompt}</p>{selected.input.source_run_id && <Button type="link" onClick={() => void open(selected.input.source_run_id!)}>查看上一个版本</Button>}<p>{String(previewArtifact?.metadata.storyboard || '')}</p></details>}
      </main>
      <aside className="animation-history">
        <div className="animation-section-title"><h2>我的作品 <small>{total}</small></h2><Button type="text" aria-label="刷新作品" onClick={() => setRefresh(value => value + 1)}>刷新</Button></div>
        <button className="animation-new" onClick={() => { setSource(undefined); setPrompt(''); setAssets([]); setTab('create'); inputRef.current?.focus(); }}><Plus size={16} />新的灵感</button>
        {listError ? <Alert type="error" message={listError} action={<Button onClick={() => setRefresh(n => n + 1)}>重试</Button>} /> : loading ? <Spin /> : !records.length ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="你的动画将保存在这里" /> : <ul>{records.map(run => <li key={run.id}><button className={selected?.id === run.id ? 'is-selected' : ''} aria-current={selected?.id === run.id ? 'true' : undefined} onClick={() => void open(run.id)}><span className="animation-history-icon"><Film size={20} /></span><strong>{String(run.output_summary.title || run.input.prompt)}</strong><span>{run.input.source_run_id ? '修改版本 · ' : ''}{run.status === 'succeeded' ? completedExport(run) ? 'MP4 已导出' : 'HTML 可预览' : animationStatus(run.status)}</span><time>{new Date(run.created_at || '').toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</time></button></li>)}</ul>}
        <Pagination simple current={page} total={total} pageSize={20} showSizeChanger={false} hideOnSinglePage onChange={setPage} />
      </aside>
    </div>
    {detailedRun && <AnimationTaskDetails key={detailedRun.id} run={[selected, ...(selected?.exports || [])].find(run => run?.id === detailedRun.id) || detailedRun} runtime={runtime} onClose={() => setDetailedRun(undefined)} />}
  </section>;
}

export default function AnimationStudioPage() {
  const { applicationId } = useParams<{ applicationId: string }>();
  const organizationId = useOrganizationStore(state => state.currentOrganizationId);
  const userId = useAuthStore(state => state.user?.id);
  const [params, setParams] = useSearchParams();
  const initial = useRef(params.get('animation') || undefined);
  const onSelect = useCallback((id: string) => setParams(current => { const next = new URLSearchParams(current); next.set('animation', id); return next; }, { replace: true }), [setParams]);
  if (!applicationId || !organizationId || !userId) return <Empty description="请选择组织并登录后使用。" />;
  if (params.get('legacy') !== '1') return <AnimationStudioEditor key={`${organizationId}:${userId}:${applicationId}`} organizationId={organizationId} applicationId={applicationId} userId={String(userId)} initialRunId={initial.current} onSelect={onSelect} showHeader={resolveApplicationPresentation(params).showApplicationHeader} />;
  return <AnimationStudioWorkspace key={`${organizationId}:${userId}:${applicationId}`} organizationId={organizationId} applicationId={applicationId} initialRunId={initial.current} onSelect={onSelect} showHeader={resolveApplicationPresentation(params).showApplicationHeader} />;
}
