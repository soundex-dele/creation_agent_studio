import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { Alert, Button, Empty, Pagination, Select, Spin } from 'antd';
import { ArrowLeft, Download, ImagePlus, Palette, RefreshCw, Sparkles, X } from 'lucide-react';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { tenantApiRoot } from '@/services/tenantContext';
import { resolveApplicationPresentation } from '@/lib/applicationPresentation';
import { createApplicationRuntimeClient, type ApplicationRuntimeClient, type RunArtifact } from '@/services/applicationRuntime';
import { drawingApi, drawingError, drawingStatus, drawingTerminal, downloadDrawing, type DrawingInput, type DrawingOrientation, type DrawingPage, type DrawingRun } from '@/services/aiDrawing';
import './AIDrawingPage.css';

function DrawingImage({ runId, artifact, runtime, large = false }: { runId: string; artifact: RunArtifact; runtime: ApplicationRuntimeClient; large?: boolean }) {
  const [url, setUrl] = useState('');
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let alive = true; setError(''); setUrl('');
    void runtime.getArtifactAccess(runId, artifact.id).then((result) => { if (alive) setUrl(result.url); }).catch((e) => { if (alive) setError(drawingError(e)); });
    return () => { alive = false; };
  }, [runtime, runId, artifact.id, revision]);
  if (error) return <div className="drawing-image-error"><span>{large ? error : '图片加载失败'}</span><Button size="small" onClick={() => setRevision((n) => n + 1)}>重新加载</Button></div>;
  return url ? <img src={url} alt={large ? '当前生成作品' : '历史作品缩略图'} loading={large ? 'eager' : 'lazy'} onError={() => setError('图片链接已过期或文件不可用。')} /> : <Spin size={large ? 'default' : 'small'} />;
}

export function AIDrawingWorkspace({ organizationId, applicationId, showHeader = true, initialRunId, onSelect }: {
  organizationId: string; applicationId: string; showHeader?: boolean; initialRunId?: string; onSelect?: (id: string) => void;
}) {
  const base = `${tenantApiRoot(organizationId)}/applications/${applicationId}/ai-drawing`;
  const client = useMemo(() => drawingApi(base), [base]);
  const runtime = useMemo(() => createApplicationRuntimeClient({ organizationId, applicationId }), [organizationId, applicationId]);
  const [prompt, setPrompt] = useState('');
  const [orientation, setOrientation] = useState<DrawingOrientation>('auto');
  const [reference, setReference] = useState<{ reference_id?: string; source_artifact_id?: string; label: string }>();
  const [referencePreview, setReferencePreview] = useState('');
  const [selected, setSelected] = useState<DrawingRun>();
  const [listing, setListing] = useState<DrawingPage>({ count: 0, results: [] });
  const [page, setPage] = useState(1);
  const [refresh, setRefresh] = useState(0);
  const [loading, setLoading] = useState(true);
  const [opening, setOpening] = useState(false);
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState('');
  const [listError, setListError] = useState('');
  const [stage, setStage] = useState('');
  const [connectionError, setConnectionError] = useState('');
  const submitting = useRef(false);
  const pendingRequest = useRef<{ fingerprint: string; key: string }>();
  const openSequence = useRef(0);
  const initialized = useRef(false);
  const uploadSequence = useRef(0);
  const promptRef = useRef<HTMLTextAreaElement>(null);
  const active = selected && !drawingTerminal(selected.status);

  const choose = useCallback((run: DrawingRun) => { setSelected(run); setStage(''); setConnectionError(''); onSelect?.(run.id); }, [onSelect]);
  useEffect(() => {
    let alive = true; setLoading(true); setListError('');
    void client.list(page).then(async (value) => {
      if (!alive) return;
      setListing(value);
      if (!initialized.current) {
        initialized.current = true;
        const first = initialRunId ? await client.get(initialRunId) : value.results[0];
        if (alive && first) choose(first);
      }
    }).catch((e) => { if (alive) setListError(drawingError(e)); }).finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [client, page, refresh, initialRunId, choose]);

  const selectedId = selected?.id;
  useEffect(() => {
    if (!selectedId || !active) return;
    let alive = true; let fetching = false;
    const reload = async () => {
      if (fetching) return; fetching = true;
      try {
        const value = await client.get(selectedId);
        if (alive) { setSelected(value); if (drawingTerminal(value.status)) setRefresh((n) => n + 1); }
      } catch (e) { if (alive) setConnectionError(drawingError(e)); }
      finally { fetching = false; }
    };
    const stream = runtime.subscribeRun(selectedId, {
      onEvent: async (event) => {
        if (!alive) return;
        if (event.type === 'progress.updated') setStage(String(event.payload.stage || ''));
        if (event.type.startsWith('run.') || event.type === 'artifact.created') await reload();
      },
      onSnapshot: reload,
      onError: () => { if (alive) setConnectionError('实时连接中断，正在自动刷新任务状态。'); },
      onConnectionChange: (connected) => { if (alive && connected) setConnectionError(''); },
    });
    // Polling also covers missed terminal events and a reconnecting event stream.
    const timer = setInterval(() => void reload(), 5000);
    return () => { alive = false; stream.abort(); clearInterval(timer); };
  }, [client, runtime, selectedId, active]);

  useEffect(() => () => { if (referencePreview.startsWith('blob:')) URL.revokeObjectURL(referencePreview); }, [referencePreview]);
  useEffect(() => () => { uploadSequence.current += 1; openSequence.current += 1; }, []);

  const open = async (run: DrawingRun) => {
    const sequence = ++openSequence.current; setOpening(true); setError('');
    try { const fresh = await client.get(run.id); if (sequence === openSequence.current) choose(fresh); }
    catch (e) { if (sequence === openSequence.current) setError(drawingError(e)); }
    finally { if (sequence === openSequence.current) setOpening(false); }
  };
  const upload = async (file: File) => {
    if (file.size > 20 * 1024 * 1024) { setError('参考图不能超过 20 MB。'); return; }
    const sequence = ++uploadSequence.current; setUploading(true); setError('');
    try {
      const result = await client.upload(file);
      if (sequence === uploadSequence.current) { setReference({ reference_id: result.id, label: file.name }); setReferencePreview(URL.createObjectURL(file)); }
    } catch (e) { if (sequence === uploadSequence.current) setError(drawingError(e)); }
    finally { if (sequence === uploadSequence.current) setUploading(false); }
  };
  const generate = async (override?: DrawingInput) => {
    if (submitting.current) return;
    const body: DrawingInput = override || { prompt: prompt.trim(), orientation, ...(reference?.reference_id ? { reference_id: reference.reference_id } : {}), ...(reference?.source_artifact_id ? { source_artifact_id: reference.source_artifact_id } : {}) };
    if (!body.prompt.trim()) { setError('请先描述想生成或修改的画面。'); promptRef.current?.focus(); return; }
    submitting.current = true; setBusy(true); setError(''); ++openSequence.current; setOpening(false);
    const fingerprint = JSON.stringify(body);
    if (pendingRequest.current?.fingerprint !== fingerprint) pendingRequest.current = { fingerprint, key: crypto.randomUUID() };
    try { const run = await client.generate(body, pendingRequest.current.key); choose(run); pendingRequest.current = undefined; setPage(1); setRefresh((n) => n + 1); }
    catch (e) { setError(drawingError(e)); }
    finally { submitting.current = false; setBusy(false); }
  };
  const cancel = async () => {
    if (!selected) return; setBusy(true); setError('');
    try { await runtime.sendCommand(selected.id, { type: 'cancel', idempotency_key: crypto.randomUUID() }); setSelected(await client.get(selected.id)); }
    catch (e) { setError(drawingError(e)); }
    finally { setBusy(false); }
  };
  const edit = async (artifact: RunArtifact) => {
    if (!selected) return;
    const sequence = ++uploadSequence.current; setUploading(true); setError('');
    try {
      const access = await runtime.getArtifactAccess(selected.id, artifact.id);
      if (sequence !== uploadSequence.current) return;
      setReference({ source_artifact_id: artifact.id, label: '历史作品 · 作为修改原图' }); setReferencePreview(access.url);
      setPrompt(''); promptRef.current?.focus();
    } catch (e) { setError(drawingError(e)); }
    finally { if (sequence === uploadSequence.current) setUploading(false); }
  };
  const download = async (artifact: RunArtifact) => {
    if (!selected) return;
    try { const access = await runtime.getArtifactAccess(selected.id, artifact.id); await downloadDrawing(access.url, `ai-drawing-${selected.id}.${artifact.mime_type.split('/')[1] || 'png'}`); }
    catch (e) { setError(drawingError(e)); }
  };
  const artifact = selected?.artifacts[0];
  return <section className="drawing-workspace" aria-label="AI 绘图工作台">
    <aside className="drawing-form">
      {showHeader && <Link to="/apps" className="drawing-back"><ArrowLeft size={15} />返回应用</Link>}
      <header><span className="drawing-app-icon"><Palette size={25} /></span><div><h1>AI 绘图</h1><p>把想象变成画面</p></div></header>
      <label htmlFor="drawing-prompt">{reference ? '描述你想修改的内容' : '描述你想看见的画面'}</label>
      <textarea id="drawing-prompt" ref={promptRef} value={prompt} maxLength={8000} rows={8} placeholder={reference ? '例如：把背景换成落日下的海边，保留主体和构图…' : '例如：一间阳光洒入的木屋书房，窗外是山林，温暖的电影质感…'} onChange={(event) => setPrompt(event.target.value)} />
      <div className="drawing-prompt-count">{prompt.length} / 8000</div>
      <label htmlFor="drawing-orientation">画面方向</label>
      <Select id="drawing-orientation" value={orientation} onChange={setOrientation} options={[{ value: 'auto', label: '自动选择' }, { value: 'square', label: '方形' }, { value: 'landscape', label: '横向' }, { value: 'portrait', label: '纵向' }]} />
      <p className="drawing-hint">作为构图偏好，实际尺寸以生成结果为准。</p>
      <div className="drawing-reference-title">参考图<span>可选 · 每次一张</span></div>
      {reference ? <div className="drawing-reference">{referencePreview && <img src={referencePreview} alt="参考原图" />}<span>{reference.label}</span><Button aria-label="移除参考图" type="text" disabled={uploading} icon={<X size={16} />} onClick={() => { ++uploadSequence.current; setReference(undefined); setReferencePreview(''); }} /></div> : <label className="drawing-upload"><ImagePlus size={24} /><strong>{uploading ? '正在上传…' : '上传一张参考图'}</strong><span>PNG / JPEG / WebP，最大 20 MB</span><input aria-label="上传参考图" type="file" accept="image/png,image/jpeg,image/webp" disabled={uploading} onChange={(event) => { const file = event.target.files?.[0]; if (file) void upload(file); event.target.value = ''; }} /></label>}
      <Button type="primary" size="large" icon={<Sparkles size={18} />} loading={busy} disabled={uploading || Boolean(active)} onClick={() => void generate()}>生成图片</Button>
      <p className="drawing-hint">每次生成一张。修改会保存为新作品，原图会保留。</p>
      {error && <Alert type="error" showIcon message={error} closable onClose={() => setError('')} />}
    </aside>
    <main className="drawing-results">
      <div className="drawing-preview-header"><div><h2>{selected ? '创作预览' : '等待你的第一个灵感'}</h2><p aria-live="polite">{selected ? drawingStatus(selected.status, stage) : '从一段描述开始，也可以上传原图继续创作'}</p></div>{active && <Button disabled={busy || selected.status === 'cancelling'} onClick={() => void cancel()}>取消生成</Button>}</div>
      {connectionError && <Alert type="warning" message={connectionError} />}
      <div className="drawing-canvas" aria-busy={Boolean(active) || opening}>
        {artifact && selected ? <DrawingImage key={artifact.id} runId={selected.id} artifact={artifact} runtime={runtime} large /> : active || opening ? <div className="drawing-empty"><Spin /><p>{opening ? '正在打开作品' : drawingStatus(selected?.status || 'queued', stage)}</p><span>图片生成需要一些时间，你可以离开页面，稍后回来查看。</span></div> : <div className="drawing-empty"><Palette size={48} strokeWidth={1} /><h3>{selected?.status === 'failed' ? '这次没有生成图片' : selected?.status === 'cancelled' ? '生成已取消' : '让想象，有迹可循'}</h3><p>写下主体、场景、风格和光线，开始创作。</p></div>}
      </div>
      {selected?.error_message && <Alert type="error" showIcon message={selected.error_message} />}
      {selected && <div className="drawing-result-info"><p>{selected.input.prompt}</p><div className="drawing-actions">{artifact && <><span>{String(artifact.metadata.width)} × {String(artifact.metadata.height)}</span><Button icon={<Download size={15} />} onClick={() => void download(artifact)}>下载原图</Button><Button disabled={Boolean(active) || uploading} onClick={() => void edit(artifact)}>继续修改</Button></>}<Button icon={<RefreshCw size={15} />} disabled={Boolean(active) || busy || uploading} onClick={() => void generate(selected.input)}>再生成一张</Button></div></div>}
      <div className="drawing-history-header"><h2>我的作品 <span>{listing.count}</span></h2><Button type="text" onClick={() => setRefresh((n) => n + 1)}>刷新</Button></div>
      {listError ? <Alert type="error" message={listError} action={<Button onClick={() => setRefresh((n) => n + 1)}>重试</Button>} /> : loading ? <Spin /> : listing.results.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="生成的作品会保存在这里" /> : <ul className="drawing-gallery">{listing.results.map((run) => <li key={run.id} className={selected?.id === run.id ? 'is-selected' : ''}><button className="drawing-history-select" onClick={() => void open(run)} aria-label={`打开作品：${run.input.prompt}`} aria-current={selected?.id === run.id ? 'true' : undefined}><span>{run.input.prompt}</span><time>{new Date(run.created_at || '').toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })} · {drawingStatus(run.status)}</time></button><div className="drawing-thumb">{run.artifacts[0] ? <DrawingImage runId={run.id} artifact={run.artifacts[0]} runtime={runtime} /> : <Palette size={30} strokeWidth={1} />}</div></li>)}</ul>}
      <Pagination current={page} total={listing.count} pageSize={20} showSizeChanger={false} hideOnSinglePage onChange={setPage} />
    </main>
  </section>;
}

export default function AIDrawingPage() {
  const { applicationId } = useParams<{ applicationId: string }>();
  const organizationId = useOrganizationStore((state) => state.currentOrganizationId);
  const userId = useAuthStore((state) => state.user?.id);
  const [params, setParams] = useSearchParams();
  const initialRunId = useRef(params.get('drawing') || undefined);
  const onSelect = useCallback((id: string) => { setParams((current) => { const next = new URLSearchParams(current); next.set('drawing', id); return next; }, { replace: true }); }, [setParams]);
  if (!organizationId || !applicationId || !userId) return <Empty description="请选择组织并登录后使用。" />;
  return <AIDrawingWorkspace key={`${organizationId}:${applicationId}:${userId}`} organizationId={organizationId} applicationId={applicationId} initialRunId={initialRunId.current} onSelect={onSelect} showHeader={resolveApplicationPresentation(params).showApplicationHeader} />;
}
