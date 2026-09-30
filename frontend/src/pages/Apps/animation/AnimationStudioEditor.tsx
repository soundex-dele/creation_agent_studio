import { StudioSelect } from './StudioControls';
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { Alert, Button, Drawer, Empty, Modal, Spin } from 'antd';
import { ArrowLeft, Clapperboard, Plus, FolderOpen, Film, AudioLines, Captions, Images, Palette, Layers, Play, Settings, Menu, Sparkles, Clock3, Copy, Save, LockKeyhole } from 'lucide-react';
import useMediaQuery from '@/hooks/useMediaQuery';
import { tenantApiRoot } from '@/services/tenantContext';
import { createApplicationRuntimeClient, type RunArtifact } from '@/services/applicationRuntime';
import { animationApi, animationError, animationStatus, animationTerminal, type AnimationRun, type AnimationGeneration } from '@/services/animationStudio';
import { defaultExport, newScene, withScenes, projectApi, type LibraryAsset, type SpeechConfig, type StudioDocument, type StudioPreset, type StudioProject, type StudioScene } from '@/services/animationProjects';
import { AnimationPreview } from '../AnimationStudioPage';
import { AssetPanel, BatchPanel, ExportFields, PresetPanel, SpeechSettings } from './StudioPanels';
import { useStudioDraft } from './useStudioDraft';
import AnimationTaskDetails from './AnimationTaskDetails';
import './StudioEditor.css';

const navigation = [
  { id: 'history', title: '我的作品', icon: FolderOpen },
  { id: 'scenes', title: '分镜制作', icon: Film },
  { id: 'audio', title: '配音与音轨', icon: AudioLines },
  { id: 'subtitles', title: '字幕', icon: Captions },
  { id: 'assets', title: '素材库', icon: Images },
  { id: 'presets', title: '模板与品牌', icon: Palette },
  { id: 'batch', title: '批量制作', icon: Layers },
  { id: 'preview', title: '预览与版本', icon: Play },
  { id: 'settings', title: '配音配置', icon: Settings },
] as const;
type StudioPage = typeof navigation[number]['id'];

const pageDescriptions: Record<StudioPage, string> = {
  history: '每一个灵感，都有继续创作的可能。',
  scenes: '从一句灵感开始，把故事变成生动的画面。',
  audio: '为每一幕配上声音，调整旁白、音乐与节奏。',
  subtitles: '校对每一句表达，让信息清晰呈现。',
  assets: '管理图片与声音，为你的故事添加细节。',
  presets: '保存常用风格，让系列作品保持一致。',
  batch: '用同一套模板，高效制作一组动画。',
  preview: '回看每次创作，比较版本并导出成片。',
  settings: '连接配音服务，设置团队常用的音色。',
};

const taskNames: Record<string, string> = { generate: '生成动画', storyboard: '生成分镜', scene: '修改场景', speech: '合成配音', transcribe: '识别字幕', export: '导出动画' };
const taskError = (message?: string) => message?.startsWith('Invalid control character')
  ? 'AI 返回的内容格式不正确，请返回制作页面重新生成。'
  : message || '请调整后重试。';

export default function AnimationStudioEditor({ organizationId, applicationId, userId, initialRunId, initialProjectId, showHeader, onSelect, onProjectSelect }: { organizationId: string; applicationId: string; userId: string; initialRunId?: string; initialProjectId?: string; showHeader: boolean; onSelect: (id: string) => void; onProjectSelect?: (id: string) => void }) {
  const base = `${tenantApiRoot(organizationId)}/applications/${applicationId}/animation-studio`;
  const client = useMemo(() => projectApi(base), [base]); const legacy = useMemo(() => animationApi(base), [base]);
  const runtime = useMemo(() => createApplicationRuntimeClient({ organizationId, applicationId }), [organizationId, applicationId]);
  const draft = useStudioDraft(client, `${organizationId}:${applicationId}:${userId}`); const { project, doc } = draft;
  const [projects, setProjects] = useState<StudioProject[]>([]); const [total, setTotal] = useState(0); const [page, setPage] = useState(1); const [query, setQuery] = useState(''); const [archived, setArchived] = useState(false);
  const [assets, setAssets] = useState<LibraryAsset[]>([]); const [presets, setPresets] = useState<StudioPreset[]>([]); const [fonts, setFonts] = useState(['Noto Sans SC']); const [speech, setSpeech] = useState<SpeechConfig>();
  const [mode, setMode] = useState<StudioPage>(initialRunId ? 'preview' : 'scenes'); const [sceneId, setSceneId] = useState(''); const [selectedId, setSelectedId] = useState(initialRunId || ''); const [compareId, setCompareId] = useState('');
  const [deleteTarget, setDeleteTarget] = useState<{ projectId: string; versionId: string; label: string }>();
  const [versionNotice, setVersionNotice] = useState('');
  const versionEpoch = useRef(0);
  const isMobile = useMediaQuery('(max-width: 767px)');
  const [menuOpen, setMenuOpen] = useState(false);
  const [detailedRun, setDetailedRun] = useState<AnimationRun>();
  const menuButton = useRef<HTMLButtonElement>(null);
  const contentHeading = useRef<HTMLHeadingElement>(null);
  const navigate = (next: StudioPage) => {
    setMode(next);
    setMenuOpen(false);
    if (!isMobile) contentHeading.current?.focus();
  };
  useEffect(() => { if (!isMobile) setMenuOpen(false); }, [isMobile]);
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false); const [loading, setLoading] = useState(true); const [instruction, setInstruction] = useState(''); const [voice, setVoice] = useState(''); const [speed, setSpeed] = useState(1); const [options, setOptions] = useState(defaultExport);
  const requestKey = useRef<{ fingerprint: string; key: string }>(); const mounted = useRef(true); const initialized = useRef(false); const selecting = useRef(0); const busyRef = useRef(false);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const report = useCallback((e: unknown) => { if (mounted.current) setError(animationError(e)); }, []);
  const runSafe = useCallback(async (work: () => Promise<void>) => { if (busyRef.current) return; busyRef.current = true; setBusy(true); setError(''); try { await work(); } catch (e) { report(e); } finally { busyRef.current = false; if (mounted.current) setBusy(false); } }, [report]);
  const refreshAssets = useCallback(async () => { const [a, b] = await Promise.all([client.assets(), client.assets(true)]); if (mounted.current) setAssets([...a.results, ...b.results]); }, [client]);
  const refreshPresets = useCallback(async () => { const p = await client.presets(); if (mounted.current) { setPresets(p.results); setFonts(p.fonts); } }, [client]);
  const refreshList = useCallback(async () => { const result = await client.list(query, archived, page); if (mounted.current) { setProjects(result.results); setTotal(result.count); } }, [client, query, archived, page]);
  useEffect(() => { const timer = setTimeout(() => { void refreshList().catch(report); }, 200); return () => clearTimeout(timer); }, [refreshList, report]);
  useEffect(() => { void refreshAssets().catch(report); void refreshPresets().catch(report); void client.speech().then(v => { if (mounted.current) { setSpeech(v); setVoice(current => v.voices.some(voice => voice.id === current) ? current : v.voices[0]?.id || ''); } }).catch(report); }, [client, refreshAssets, refreshPresets, report, mode]);
  const adopt = draft.adopt;
  useEffect(() => {
    let alive = true;
    if (initialized.current) return;
    void (async () => {
      if (initialProjectId) {
        const p = await client.get(initialProjectId);
        if (alive) { initialized.current = true; adopt(p); setSceneId(p.draft.scenes?.[0]?.id || ''); }
        return;
      }
      const list = await client.list();
      if (!alive) return;
      let id: string | undefined = list.results[0]?.id;
      if (initialRunId) {
        const run = await legacy.get(initialRunId) as AnimationRun & { project_id?: string };
        id = run.project_id;
      }
      const p = id ? await client.get(id) : await client.create();
      if (alive) { initialized.current = true; adopt(p); setProjects(list.results); setSceneId(p.draft.scenes?.[0]?.id || ''); }
    })().catch(report).finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [client, legacy, initialRunId, initialProjectId, adopt, report]);
  const refreshProject = draft.refresh; const projectId = project?.id;
  useEffect(() => { if (projectId) onProjectSelect?.(projectId); }, [projectId, onProjectSelect]);
  useEffect(() => { setDetailedRun(undefined); }, [projectId]);
  useEffect(() => {
    if (!projectId) return;
    let alive = true; let fetching = false;
    const id = projectId;
    const timer = setInterval(() => { if (fetching || busyRef.current) return; fetching = true; const epoch = versionEpoch.current; void client.get(id).then(p => { if (alive && epoch === versionEpoch.current) refreshProject(p); }).catch(report).finally(() => { fetching = false; }); }, 3000);
    return () => { alive = false; clearInterval(timer); };
  }, [projectId, client, refreshProject, report]);
  const versions = project?.versions || [];
  const selected = versions.find(v => v.run.id === selectedId) || versions[0]; const compare = versions.find(v => v.run.id === compareId && v.run.id !== selected?.run.id);
  const deleteBlockedReason = selected?.can_delete === false ? '这是其他作品引用的版本，请在原作品中删除。'
    : selected && !animationTerminal(selected.run.status) ? '请等待生成完成或取消任务后再删除。'
    : selected?.run.exports.some(run => !animationTerminal(run.status)) ? '请等待导出完成或取消导出后再删除。' : '';
  const scene = doc?.scenes?.find(s => s.id === sceneId) || doc?.scenes?.[0];
  const tasks = [...(project?.tasks || []), ...versions.flatMap(v => [v.run, ...v.run.exports])]; const active = tasks.filter(t => !animationTerminal(t.status));
  const change = draft.change;
  const chooseProject = async (id: string) => {
    if (!await draft.flush()) return;
    const token = ++selecting.current; const p = await client.get(id);
    if (mounted.current && token === selecting.current) { adopt(p); setSceneId(p.draft.scenes?.[0]?.id || ''); setSelectedId(''); setCompareId(''); navigate('scenes'); }
  };
  const task = (action: string, extra: Record<string, unknown> = {}) => void runSafe(async () => {
    if (!await draft.flush()) return;
    const c = draft.current.current; if (!c) return;
    const body = { action, revision: c.project.revision, ...extra }; const fingerprint = JSON.stringify({ id: c.project.id, body });
    if (requestKey.current?.fingerprint !== fingerprint) requestKey.current = { fingerprint, key: crypto.randomUUID() };
    const run = await client.task(c.project.id, body, requestKey.current.key); requestKey.current = undefined;
    const p = await client.get(c.project.id); refreshProject(p);
    if (action === 'generate') { setSelectedId(run.id); onSelect(run.id); navigate('preview'); }
  });
  const editScene = (patch: Partial<StudioScene>) => { if (doc && scene) change(withScenes(doc, doc.scenes.map(s => s.id === scene.id ? { ...s, ...patch, ...(patch.description !== undefined && patch.description !== s.description ? { source: '' } : {}) } : s))); };
  const attachAsset = (a: LibraryAsset) => {
    if (!doc || !scene) { report(new Error('请先创建并选择一个场景。')); return; }
    if (scene.locked) { report(new Error('请先解锁场景。')); return; }
    if (a.duration === null) editScene({ assets: [...new Set([...scene.assets, a.id])] });
    else change({ ...doc, scenes: doc.scenes.map(s => s.id === scene.id ? { ...s, frames: Math.max(s.frames, Math.ceil(a.duration! * 30)) } : s), audio: [...doc.audio, { asset_id: a.id, role: 'narration', scene_id: scene.id, start: 0, frames: Math.ceil(a.duration * 30), volume: 1 }] });
  };
  const download = async (run: AnimationRun, artifact?: RunArtifact) => {
    const item = artifact || run.artifacts[0]; if (!item) return;
    const access = await runtime.getArtifactAccess(run.id, item.id); const response = await fetch(access.url);
    if (!response.ok) throw new Error('下载失败，请重试。');
    const url = URL.createObjectURL(await response.blob()); const a = document.createElement('a'); a.href = url; a.download = String(item.metadata.filename || item.kind); a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const pickVersion = (id: string) => { setSelectedId(id); if (id) onSelect(id); };
  const deleteVersion = () => void runSafe(async () => {
    if (!deleteTarget) return;
    const target = deleteTarget;
    versionEpoch.current += 1;
    await client.deleteVersion(target.projectId, target.versionId);
    versionEpoch.current += 1;
    if (!mounted.current) return;
    setDeleteTarget(undefined);
    const current = draft.current.current?.project;
    if (current?.id !== target.projectId) return;
    const remaining = (current.versions || []).filter(v => v.id !== target.versionId);
    refreshProject({ ...current, versions: remaining });
    const next = remaining.find(v => v.run.id === selectedId) || remaining[0];
    setSelectedId(next?.run.id || '');
    setCompareId(id => remaining.some(v => v.run.id === id) && id !== next?.run.id ? id : '');
    onSelect(next?.run.id || '');
    setVersionNotice(`${target.label}已删除`);
  });
  const refresh = async () => { if (project) refreshProject(await client.get(project.id)); await refreshList(); };
  const menu = <StudioNavigation current={mode} onSelect={navigate} />;
  const editing = mode !== 'history' && mode !== 'preview';
  const title = navigation.find(item => item.id === mode)!.title;
  return <section className="animation-workspace studio-workspace" data-page={mode} aria-label="动画制作工作台">
    <Modal title={`删除${deleteTarget?.label || '版本'}？`} open={!!deleteTarget} onOk={deleteVersion}
      onCancel={() => { if (!busy) setDeleteTarget(undefined); }} okText="确认删除" cancelText="取消"
      okButtonProps={{ danger: true }} cancelButtonProps={{ disabled: busy, autoFocus: true }} confirmLoading={busy}
      closable={!busy} maskClosable={!busy} keyboard={!busy}>
      <p>删除后，该版本将从版本列表移除，无法在这里恢复。当前草稿、素材和关联文件会保留。</p>
      {deleteTarget && error && <Alert type="error" showIcon message={error} />}
    </Modal>
    <header className="animation-header"><div className="animation-brand">{isMobile && <Button ref={menuButton} type="text" icon={<Menu size={20} aria-hidden="true" />} aria-label="打开动画制作菜单" aria-expanded={menuOpen} aria-haspopup="dialog" onClick={() => setMenuOpen(true)} />}{showHeader && <Link to="/apps" aria-label="返回应用"><ArrowLeft size={20} aria-hidden="true" /></Link>}<span className="animation-logo"><Clapperboard size={23} aria-hidden="true" /></span><div><h1>动画制作</h1><p>分镜创作 · 有声动画 · 批量出片</p></div></div><span className="studio-save-status" role="status"><Save size={14} aria-hidden="true" />{draft.status}</span></header>
    {isMobile && <Drawer title="动画制作菜单" placement="left" width="min(88vw, 320px)" open={menuOpen}
      onClose={() => setMenuOpen(false)} rootClassName="studio-menu-drawer"
      afterOpenChange={open => { if (!open) menuButton.current?.focus(); }}>
      {menu}
    </Drawer>}
    <div className="studio-notices" aria-label="工作台提示">
    {error && <Alert className="animation-error" type="error" showIcon message={error} closable onClose={() => setError('')} />}
    {draft.conflict && <Alert className="animation-error" type="warning" message="草稿保存冲突，本地内容已保留。" action={<div className="studio-buttons"><Button onClick={() => void runSafe(() => draft.resolve(true))}>保留本地草稿</Button><Button onClick={() => void runSafe(() => draft.resolve(false))}>加载服务器草稿</Button></div>} />}
        {active.map(t => <div className="studio-task" key={t.id}><Spin size="small" /><span>{animationStatus(t.status)} · {taskNames[String(t.input.action)] || '制作任务'}</span><Button onClick={() => setDetailedRun(t)}>详情</Button><Button disabled={t.status === 'cancelling'} onClick={() => void runtime.sendCommand(t.id, { type: 'cancel', idempotency_key: crypto.randomUUID() }).then(refresh).catch(report)}>取消</Button></div>)}
        {(project?.tasks || []).filter(t => t.status === 'succeeded' && t.output_summary.draft_applied === false).map(t => <Alert key={t.id} type="info" message="任务结果已保存；为保留你的后续修改，没有自动替换当前草稿。" action={<Button onClick={() => void runSafe(async () => { if (!await draft.flush()) return; const c = draft.current.current!; const p = await client.action(c.project.id, 'apply-result', { run_id: t.id, revision: c.project.revision }); adopt({ ...p, versions: c.project.versions, tasks: c.project.tasks }); })}>应用这次结果</Button>} />)}
        {(project?.tasks || []).filter(t => t.status === 'failed').slice(0, 2).map(t => <Alert key={t.id} type="error" message={`上次${taskNames[String(t.input.action)] || '制作任务'}失败`} description={taskError(t.error_message)} />)}
    </div>
    <div className="studio-body">
      {!isMobile && <aside className="studio-sidebar">{menu}<div className="studio-sidebar-note"><Clapperboard size={22} aria-hidden="true" /><strong>让想法动起来</strong><p>构思、分镜、配音到成片，专注每一步创作。</p></div></aside>}
      <div className="studio-content">
        <div className="studio-page-heading"><div><h2 ref={contentHeading} tabIndex={-1} className="studio-page-title">{title}</h2><p>{pageDescriptions[mode]}</p></div>{doc?.schema_version === 2 && <div className="studio-project-meta" aria-label="作品概览"><span><Film size={14} aria-hidden="true" />{doc.scenes.length} 个场景</span><span><Clock3 size={14} aria-hidden="true" />{(doc.scenes.reduce((n, s) => n + s.frames, 0) / 30).toFixed(1)} 秒</span><span>{doc.aspect}</span></div>}</div>
      <section className="studio-projects" hidden={mode !== 'history'} aria-label="我的作品">{loading && <Spin aria-label="正在加载作品" />}<div className="animation-section-title"><span>共 {total} 个作品</span><Button aria-label="刷新作品" onClick={() => void refreshList().catch(report)}>刷新</Button></div><Button icon={<Plus size={16} />} disabled={busy || loading} onClick={() => void runSafe(async () => { if (!await draft.flush()) return; const p = await client.create(); adopt(p); setSelectedId(''); setCompareId(''); setSceneId(''); navigate('scenes'); await refreshList(); })}>新的作品</Button><label>搜索作品<input value={query} onChange={e => { setQuery(e.target.value); setPage(1); }} /></label><label><input type="checkbox" checked={archived} onChange={e => { setArchived(e.target.checked); setPage(1); }} />查看归档</label>
        <div className="studio-project-grid">{projects.map(p => <button className={`studio-project ${p.id === project?.id ? 'is-selected' : ''}`} aria-current={p.id === project?.id ? 'true' : undefined} key={p.id} onClick={() => void runSafe(() => chooseProject(p.id))}><span className="studio-project-art" aria-hidden="true"><Clapperboard size={32} /></span><strong>{p.title}</strong><small>{new Date(p.updated_at).toLocaleString('zh-CN')}</small>{p.id === project?.id && <span className="studio-project-tag">当前作品</span>}</button>)}</div>{!loading && !projects.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={query ? '没有找到相关作品，试试其他关键词' : archived ? '暂无归档作品' : '还没有作品，开始记录第一个灵感吧'} />}<div className="studio-buttons"><Button disabled={page <= 1} onClick={() => setPage(page - 1)}>上一页</Button><Button disabled={page * 20 >= total} onClick={() => setPage(page + 1)}>下一页</Button></div>
      </section>
      <section className="studio-editor-pane" hidden={!editing} aria-label="制作功能">{loading ? <Spin /> : !project || !doc ? <Empty description="作品加载失败，请刷新页面重试" /> : <>
        <div className="studio-project-toolbar"><label>作品名称<input key={project.id + project.title} defaultValue={project.title} onBlur={e => { const title = e.target.value; if (title !== project.title) void runSafe(async () => { await client.update(project.id, { title }); await refresh(); }); }} /></label><div className="studio-buttons"><Button icon={<Copy size={15} aria-hidden="true" />} onClick={() => void runSafe(async () => { if (!await draft.flush()) return; const p = await client.action(project.id, 'copy'); adopt(p); await refreshList(); })}>复制作品</Button><Button onClick={() => void runSafe(async () => { await client.update(project.id, { archived: !project.archived }); await refresh(); })}>{project.archived ? '恢复作品' : '归档作品'}</Button><Button icon={<Save size={15} aria-hidden="true" />} onClick={() => void draft.flush()}>保存草稿</Button></div></div>
        {doc.schema_version !== 2 && !['assets', 'settings', 'batch'].includes(mode) && <div className="studio-card"><h3>历史动画</h3><p>原作品可以预览、下载和导出。复制为分镜工程后，可编辑场景、配音和字幕；转换会重新生成画面，原版本保持不变。</p><Button disabled={!selected} onClick={() => void runSafe(async () => { const p = await client.action(project.id, 'convert', { version_id: selected!.id }); adopt(p); setSelectedId(''); await refreshList(); })}>复制并转换为分镜工程</Button><Button onClick={() => { if (selected) window.location.assign(`${window.location.pathname}?${new URLSearchParams({ entry: 'apps', standalone: '1', animation: selected.run.id, legacy: '1' })}`); }}>原版继续修改</Button></div>}
          {doc.schema_version === 2 && <RetainedPanel active={mode === 'scenes'} name="scenes">
            <div className="studio-card studio-brief">
              <div className="studio-section-heading"><span className="studio-step">01</span><div><h3>描述你的灵感</h3><p>写下主题与内容，让 AI 帮你搭建故事。</p></div><Sparkles size={22} aria-hidden="true" /></div>
              <label>动画内容<textarea rows={4} placeholder="例如：用 30 秒讲清楚番茄工作法，用时钟和进度动画展示专注与休息的节奏。" value={doc.prompt} onChange={e => change({ ...doc, prompt: e.target.value })} /></label><div className="studio-fields"><label>画幅<StudioSelect value={doc.aspect} disabled={doc.scenes.some(s => s.locked)} onChange={e => change({ ...doc, aspect: e.target.value as StudioDocument['aspect'], scenes: doc.scenes.map(s => ({ ...s, source: '' })) })}>{['16:9', '9:16', '1:1'].map(v => <option key={v}>{v}</option>)}</StudioSelect></label><label>视觉风格<input value={doc.style} onChange={e => change({ ...doc, style: e.target.value, scenes: doc.scenes.map(s => s.locked ? s : { ...s, source: '' }) })} /></label></div><p className="studio-hint">更改画幅后生成新版本预览；锁定场景须先解锁。</p>
              <div className="studio-buttons"><Button className="studio-generate-button" icon={<Sparkles size={16} aria-hidden="true" />} disabled={busy || !!active.length || !doc.prompt.trim()} onClick={() => task('storyboard')}>生成分镜</Button><Button icon={<Play size={16} aria-hidden="true" />} disabled={busy || !!active.length || !doc.prompt.trim()} onClick={() => task('generate')}>一键生成动画</Button></div>
            </div>
            <div className="studio-section-heading"><span className="studio-step">02</span><div><h3>编排你的故事</h3><p>选择场景，打磨画面、文字与节奏。</p></div></div>
            <div className="studio-storyboard-layout"><div className="studio-scene-list"><div className="animation-section-title"><h4>分镜</h4><small>{doc.scenes.length} / 30 场景</small></div><div className="studio-scenes">{doc.scenes.map((s, i) => <button type="button" key={s.id} aria-pressed={scene?.id === s.id} className={scene?.id === s.id ? 'is-selected' : ''} onClick={() => setSceneId(s.id)}><span className="studio-scene-number">{String(i + 1).padStart(2, '0')}</span><span className="studio-scene-info"><strong>{s.title}</strong><small>{(s.frames / 30).toFixed(1)} 秒 {s.locked ? '· 已锁定' : ''}</small></span>{s.locked && <LockKeyhole size={14} aria-hidden="true" />}</button>)}</div>{!doc.scenes.length && <p className="studio-hint">生成分镜后，场景会显示在这里。也可以手动添加。</p>}<Button icon={<Plus size={16} aria-hidden="true" />} disabled={doc.scenes.length >= 30} onClick={() => { const s = newScene(); change({ ...doc, scenes: [...doc.scenes, s] }); setSceneId(s.id); }}>添加场景</Button></div>
            {scene ? <article className="studio-card studio-scene-editor"><div className="studio-section-heading"><Film size={19} aria-hidden="true" /><h4>场景 {String(doc.scenes.indexOf(scene) + 1).padStart(2, '0')} · 编辑细节</h4></div><div className="studio-buttons"><Button onClick={() => editScene({ locked: !scene.locked })}>{scene.locked ? '解锁场景' : '锁定场景'}</Button><Button disabled={scene.locked} onClick={() => { const s = { ...structuredClone(scene), id: crypto.randomUUID(), title: scene.title + ' · 副本' }; change({ ...doc, scenes: [...doc.scenes, s] }); setSceneId(s.id); }}>复制</Button><Button danger disabled={scene.locked} onClick={() => { change(withScenes(doc, doc.scenes.filter(s => s.id !== scene.id))); setSceneId(''); }}>删除</Button>{[-1, 1].map(delta => <Button key={delta} disabled={scene.locked || doc.scenes.indexOf(scene) + delta < 0 || doc.scenes.indexOf(scene) + delta >= doc.scenes.length} onClick={() => { const list = [...doc.scenes]; const i = list.indexOf(scene); [list[i], list[i + delta]] = [list[i + delta], list[i]]; change(withScenes(doc, list)); }}>{delta < 0 ? '上移' : '下移'}</Button>)}</div>
              <fieldset disabled={scene.locked}><label>标题<input value={scene.title} onChange={e => editScene({ title: e.target.value })} /></label><label>正文<textarea rows={4} value={scene.body} onChange={e => editScene({ body: e.target.value })} /></label><label>旁白<textarea value={scene.narration} onChange={e => editScene({ narration: e.target.value })} /></label><label>画面描述<textarea value={scene.description} onChange={e => editScene({ description: e.target.value })} /></label><div className="studio-fields"><label>时长（秒）<input type="number" min={1 / 30} max={120} step={1 / 30} value={scene.frames / 30} onChange={e => editScene({ frames: Math.max(1, Math.round(Number(e.target.value) * 30)) })} /></label><label>文字颜色<input type="color" value={scene.style.color} onChange={e => editScene({ style: { ...scene.style, color: e.target.value } })} /></label><label>背景颜色<input type="color" value={scene.style.background} onChange={e => editScene({ style: { ...scene.style, background: e.target.value } })} /></label><label>字体<StudioSelect disabled={scene.locked} value={scene.style.font} onChange={e => editScene({ style: { ...scene.style, font: e.target.value } })}>{fonts.map(f => <option key={f}>{f}</option>)}</StudioSelect></label></div><label>添加图片<StudioSelect disabled={scene.locked} value="" onChange={e => { const a = assets.find(a => a.id === e.target.value); if (a) attachAsset(a); }}><option value="">选择素材库图片</option>{assets.filter(a => a.duration === null && !a.archived).map(a => <option key={a.id} value={a.id}>{a.name}</option>)}</StudioSelect></label>{scene.assets.map(id => <div className="studio-buttons" key={id}><span>{assets.find(a => a.id === id)?.name || id}</span><Button onClick={() => editScene({ assets: scene.assets.filter(a => a !== id) })}>移除</Button></div>)}</fieldset>
              <div className="studio-scene-assist"><label>只修改这一幕<textarea value={instruction} onChange={e => setInstruction(e.target.value)} placeholder="例如：用柱状图展示数据，保留标题" /></label><Button icon={<Sparkles size={16} aria-hidden="true" />} disabled={busy || !!active.length || scene.locked || !instruction.trim()} onClick={() => task('scene', { scene_id: scene.id, instruction })}>AI 修改当前场景</Button></div></article> : <div className="studio-scene-empty"><Film size={36} strokeWidth={1.25} aria-hidden="true" /><h4>故事，从第一幕开始</h4><p>在上方描述灵感生成分镜，<br />或添加一个场景，自由创作。</p></div>}</div>
            <div className="studio-card studio-publish"><div className="studio-section-heading"><span className="studio-step">03</span><div><h3>让故事动起来</h3><p>确认分镜后，生成可预览的动画版本。</p></div></div><label>本次版本说明（可选）<input maxLength={1000} placeholder="记录这次创作的调整，方便之后比较版本" value={doc.note || ''} onChange={e => change({ ...doc, note: e.target.value })} /></label>
            <Button type="primary" icon={<Play size={16} aria-hidden="true" />} disabled={busy || !!active.length || !doc.scenes.length} onClick={() => task('generate')}>确认分镜并生成预览</Button></div>
          </RetainedPanel>}
          {doc.schema_version === 2 && <RetainedPanel active={mode === 'audio'} name="audio"><h3>场景配音</h3><label>场景<StudioSelect value={scene?.id || ''} onChange={e => setSceneId(e.target.value)}>{doc.scenes.map(s => <option key={s.id} value={s.id}>{s.title}</option>)}</StudioSelect></label>{scene && <label>旁白文案<textarea disabled={scene.locked} value={scene.narration} onChange={e => editScene({ narration: e.target.value })} /></label>}<div className="studio-fields"><label>音色<StudioSelect value={voice} onChange={e => setVoice(e.target.value)}><option value="">选择音色</option>{speech?.voices.map(v => <option key={v.id} value={v.id}>{v.name}</option>)}</StudioSelect></label><label>语速<input type="number" min={0.5} max={2} step={0.1} value={speed} onChange={e => setSpeed(Number(e.target.value))} /></label></div>{!speech?.enabled && <p>尚未启用豆包配音，可在“配音配置”中设置，或直接上传录音。</p>}<Button disabled={!speech?.enabled || !scene || scene.locked || !voice || busy || !!active.length} onClick={() => task('speech', { scene_id: scene?.id, voice, speed })}>合成当前场景配音与字幕</Button>
            <label>添加录音、音乐或音效<StudioSelect value="" onChange={e => { const a = assets.find(a => a.id === e.target.value); if (a) attachAsset(a); }}><option value="">选择音频素材</option>{assets.filter(a => a.duration !== null && !a.archived).map(a => <option value={a.id} key={a.id}>{a.name}</option>)}</StudioSelect></label>
            {doc.audio.map((t, i) => <article className="studio-card" key={i}><strong>{assets.find(a => a.id === t.asset_id)?.name || '音轨'}</strong><div className="studio-fields">{[['role', '用途'], ['scene_id', '所属场景']].map(([field, label]) => <label key={field}>{label}<StudioSelect value={t[field as 'role' | 'scene_id'] || ''} onChange={e => change({ ...doc, audio: doc.audio.map((a, j) => i === j ? { ...a, [field]: e.target.value } : a) })}>{field === 'role' ? <><option value="narration">旁白</option><option value="music">背景音乐</option><option value="effect">音效</option></> : <><option value="">整个工程</option>{doc.scenes.map(s => <option key={s.id} value={s.id}>{s.title}</option>)}</>}</StudioSelect></label>)}{([['start', '开始时间'], ['trim_start', '素材裁剪起点'], ['frames', '播放长度'], ['fade_in', '淡入'], ['fade_out', '淡出']] as const).map(([field, label]) => <label key={field}>{label}（秒）<input type="number" min={0} step={0.1} value={(t[field] || 0) / 30} onChange={e => change({ ...doc, audio: doc.audio.map((a, j) => i === j ? { ...a, [field]: Math.round(Number(e.target.value) * 30) } : a) })} /></label>)}<label>音量<input type="number" min={0} max={2} step={0.1} value={t.volume} onChange={e => change({ ...doc, audio: doc.audio.map((a, j) => i === j ? { ...a, volume: Number(e.target.value) } : a) })} /></label></div><label><input type="checkbox" checked={!!t.loop} onChange={e => change({ ...doc, audio: doc.audio.map((a, j) => i === j ? { ...a, loop: e.target.checked } : a) })} />循环播放</label><div className="studio-buttons"><Button onClick={() => { navigate('assets'); }}>在素材库试听</Button><Button disabled={busy || !!active.length} onClick={() => task('transcribe', { asset_id: t.asset_id })}>识别为字幕</Button><Button onClick={() => change({ ...doc, audio: doc.audio.filter((_, j) => j !== i) })}>移除音轨</Button></div></article>)}
          </RetainedPanel>}
          {doc.schema_version === 2 && <RetainedPanel active={mode === 'subtitles'} name="subtitles"><h3>字幕校对</h3><label><input type="checkbox" checked={doc.subtitle_style.enabled} onChange={e => change({ ...doc, subtitle_style: { ...doc.subtitle_style, enabled: e.target.checked } })} />在画面中显示字幕</label><div className="studio-fields"><label>字体<StudioSelect value={doc.subtitle_style.font} onChange={e => change({ ...doc, subtitle_style: { ...doc.subtitle_style, font: e.target.value } })}>{fonts.map(f => <option key={f}>{f}</option>)}</StudioSelect></label><label>字号<input type="number" min={12} max={120} value={doc.subtitle_style.size} onChange={e => change({ ...doc, subtitle_style: { ...doc.subtitle_style, size: Number(e.target.value) } })} /></label><label>颜色<input type="color" value={doc.subtitle_style.color} onChange={e => change({ ...doc, subtitle_style: { ...doc.subtitle_style, color: e.target.value } })} /></label><label>位置<StudioSelect value={doc.subtitle_style.position} onChange={e => change({ ...doc, subtitle_style: { ...doc.subtitle_style, position: e.target.value as 'top' | 'center' | 'bottom' } })}><option value="top">顶部</option><option value="center">居中</option><option value="bottom">底部</option></StudioSelect></label></div>{doc.subtitles.map((s, i) => <article className="studio-card" key={i}><div className="studio-fields">{(['start', 'end'] as const).map(field => <label key={field}>{field === 'start' ? '开始' : '结束'}（秒）<input type="number" min={0} step={1 / 30} value={s[field] / 30} onChange={e => change({ ...doc, subtitles: doc.subtitles.map((c, j) => i === j ? { ...c, [field]: Math.round(Number(e.target.value) * 30) } : c) })} /></label>)}</div><textarea aria-label={`字幕 ${i + 1}`} value={s.text} onChange={e => change({ ...doc, subtitles: doc.subtitles.map((c, j) => i === j ? { ...c, text: e.target.value } : c) })} /><Button onClick={() => change({ ...doc, subtitles: doc.subtitles.filter((_, j) => j !== i) })}>删除字幕</Button></article>)}<Button onClick={() => change({ ...doc, subtitles: [...doc.subtitles, { start: 0, end: Math.min(90, doc.scenes.reduce((n, s) => n + s.frames, 0)), text: '字幕文字' }] })}>添加字幕</Button><Button type="primary" disabled={!doc.scenes.length || busy || !!active.length} onClick={() => task('generate')}>生成含字幕的新版本</Button></RetainedPanel>}
          <RetainedPanel active={mode === 'assets'} name="assets"><AssetPanel client={client} assets={assets} refresh={refreshAssets} upload={async file => { await runSafe(async () => { await legacy.upload(file); await refreshAssets(); }); }} onUse={attachAsset} report={report} /></RetainedPanel>
          {doc.schema_version === 2 && <RetainedPanel key={project.id} active={mode === 'presets'} name="presets"><PresetPanel presets={presets} doc={doc} change={change} client={client} refresh={refreshPresets} fonts={fonts} assets={assets} report={report} /></RetainedPanel>}
          <RetainedPanel active={mode === 'batch'} name="batch"><BatchPanel client={client} presets={presets} report={report} download={(run, artifact) => void download(run, artifact).catch(report)} /></RetainedPanel>
          <RetainedPanel active={mode === 'settings'} name="settings"><SpeechSettings client={client} report={report} /></RetainedPanel>
      </>}</section>
      <section className="studio-preview-pane" hidden={mode !== 'preview'} aria-label="预览与版本"><div className="animation-section-title animation-preview-heading"><span>预览、比较与导出</span>{selected && <div className="studio-buttons"><Button danger disabled={busy || !!deleteBlockedReason} title={deleteBlockedReason || undefined} onClick={() => { if (project) { setError(''); setVersionNotice(''); setDeleteTarget({ projectId: project.id, versionId: selected.id, label: `版本 ${versions.length - versions.indexOf(selected)}` }); } }}>删除当前版本</Button><Button type="primary" onClick={() => { navigate('scenes'); }}>继续修改</Button></div>}</div>
        {versionNotice && <p role="status">{versionNotice}</p>}
        <div className="studio-version-strip" aria-label="版本缩略图">{versions.map((v, i) => <button key={v.id} aria-pressed={selected?.id === v.id} className={selected?.id === v.id ? 'is-selected' : ''} onClick={() => pickVersion(v.run.id)}><VersionThumbnail run={v.run} runtime={runtime} /><span>版本 {versions.length - i}</span></button>)}</div>
        <label>查看版本<StudioSelect value={selected?.run.id || ''} onChange={e => pickVersion(e.target.value)}><option value="">选择版本</option>{versions.map((v, i) => <option key={v.id} value={v.run.id}>版本 {versions.length - i} · {animationStatus(v.run.status)} · {new Date(v.created_at).toLocaleString('zh-CN')}</option>)}</StudioSelect></label>
        {selected ? <><div className={compare ? "studio-comparison-grid" : undefined}><div className="animation-canvas" style={{ aspectRatio: (selected.run.input.aspect || '16:9').replace(':', '/') }}>{mode === 'preview' && <AnimationPreview generation={selected.run} runtime={runtime} />}</div>{compare && <div className="animation-canvas" style={{ aspectRatio: (compare.run.input.aspect || '16:9').replace(':', '/') }}>{mode === 'preview' && <AnimationPreview generation={compare.run} runtime={runtime} />}</div>}</div>{selected.run.error_message && <Alert type="error" message="此版本生成失败" description={taskError(selected.run.error_message)} />}<p>{selected.note || '首次生成'}</p><Button disabled={busy} onClick={() => void runSafe(async () => { if (!project || !await draft.flush()) return; const c = draft.current.current!; const p = await client.action(project.id, 'restore', { version_id: selected.id, revision: c.project.revision }); adopt({ ...p, versions: project.versions }); navigate('scenes'); })}>复制此版本为草稿</Button>
          <label>对比版本<StudioSelect value={compare?.run.id || ''} onChange={e => setCompareId(e.target.value)}><option value="">不对比</option>{versions.filter(v => v.id !== selected.id).map(v => <option key={v.id} value={v.run.id}>{v.note || v.created_at}</option>)}</StudioSelect></label>{compare && <><div className="studio-diff"><h4>内容差异</h4>{(selected.document.scenes || []).map(s => { const old = compare.document.scenes?.find(o => o.id === s.id); return <p key={s.id}><strong>{s.title}</strong>：{!old ? '新增场景' : JSON.stringify(old) === JSON.stringify(s) ? '未变化' : `${old.body} → ${s.body}；${old.frames / 30}s → ${s.frames / 30}s`}</p>; })}{(compare.document.scenes || []).filter(s => !selected.document.scenes?.some(n => n.id === s.id)).map(s => <p key={s.id}>已移除：{s.title}</p>)}{selected.document.schema_version === 1 && <p>{String(compare.run.input.prompt)} → {String(selected.run.input.prompt)}</p>}</div></>}
          <h3>导出当前版本</h3><ExportFields value={options} onChange={setOptions} doc={selected.document} /><Button type="primary" disabled={busy || selected.run.status !== 'succeeded'} onClick={() => void runSafe(async () => { const fingerprint = JSON.stringify({ run: selected.run.id, options }); if (requestKey.current?.fingerprint !== fingerprint) requestKey.current = { fingerprint, key: crypto.randomUUID() }; await client.export(selected.run.id, options, requestKey.current.key); requestKey.current = undefined; await refresh(); })}>导出 {options.format.toUpperCase()}</Button>
          {selected.run.artifacts.filter(a => a.kind === 'animation-source').map(a => <Button key={a.id} onClick={() => void download(selected.run, a).catch(report)}>下载源码</Button>)}
          {selected.run.exports.map(e => <article className="studio-card" key={e.id}><small>{animationStatus(e.status)} · {String((e.input.export_options as { format?: string } | undefined)?.format || 'mp4').toUpperCase()}</small>{e.error_message && <p>{e.error_message}</p>}{!animationTerminal(e.status) && <Button onClick={() => void runtime.sendCommand(e.id, { type: 'cancel', idempotency_key: crypto.randomUUID() }).then(refresh).catch(report)}>取消导出</Button>}{e.artifacts.map(a => <Button key={a.id} onClick={() => void download(e, a).catch(report)}>下载 {String(a.metadata.filename || a.kind)}</Button>)}</article>)}
        </> : loading ? <Spin aria-label="正在加载作品" /> : <Empty description={project ? "确认分镜并生成预览后，版本将保存在这里" : "作品加载失败，请刷新页面重试"} />}
      </section>
      </div>
    </div>
    {detailedRun && <AnimationTaskDetails key={detailedRun.id} run={tasks.find(t => t.id === detailedRun.id) || detailedRun} runtime={runtime} onClose={() => setDetailedRun(undefined)} />}
  </section>;
}

function StudioNavigation({ current, onSelect }: { current: StudioPage; onSelect: (page: StudioPage) => void }) {
  return <nav className="studio-navigation" aria-label="动画制作功能">
    {([
      { title: '工作空间', pages: ['history'] },
      { title: '创作工具', pages: ['scenes', 'audio', 'subtitles', 'preview'] },
      { title: '资源与设置', pages: ['assets', 'presets', 'batch', 'settings'] },
    ] as const).map(group => <div className="studio-nav-group" key={group.title}><p className="studio-nav-label">{group.title}</p>
      {group.pages.map(page => {
        const { id, title, icon: Icon } = navigation.find(item => item.id === page)!;
        return <button type="button" key={id} data-page={id} aria-current={current === id ? 'page' : undefined} onClick={() => onSelect(id)}>
          <Icon size={19} aria-hidden="true" /><span>{title}</span>
        </button>;
      })}
    </div>)}
  </nav>;
}

/** Keep local form state after first visit, while hidden controls leave the tab order. */
function RetainedPanel({ active, name, children }: { active: boolean; name: string; children: ReactNode }) {
  const [visited, setVisited] = useState(active);
  const element = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (active) setVisited(true);
    else element.current?.querySelectorAll<HTMLMediaElement>('audio, video').forEach(media => media.pause());
  }, [active]);
  return visited || active ? <div ref={element} className="studio-panel" data-panel={name} hidden={!active}>{children}</div> : null;
}

function VersionThumbnail({ run, runtime }: { run: AnimationGeneration; runtime: ReturnType<typeof createApplicationRuntimeClient> }) {
  const artifactId = run.artifacts.find(a => a.kind === 'animation-cover')?.id; const [url, setUrl] = useState('');
  useEffect(() => {
    if (!artifactId) return;
    let active = true; let objectUrl = '';
    void runtime.getArtifactAccess(run.id, artifactId).then(a => fetch(a.url)).then(r => { if (!r.ok) throw new Error('thumbnail'); return r.blob(); }).then(blob => { objectUrl = URL.createObjectURL(blob); if (active) setUrl(objectUrl); else URL.revokeObjectURL(objectUrl); }).catch(() => {});
    return () => { active = false; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [runtime, run.id, artifactId]);
  return url ? <img src={url} alt="版本画面" /> : <Clapperboard size={24} aria-hidden="true" />;
}
