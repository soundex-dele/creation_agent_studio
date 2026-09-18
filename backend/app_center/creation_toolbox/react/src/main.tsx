import {
  ArrowLeft,
  AudioLines,
  Check,
  ChevronRight,
  CircleStop,
  Clapperboard,
  Download,
  FileAudio,
  FileText,
  Folder,
  FolderPlus,
  Gauge,
  Image,
  LayoutDashboard,
  LoaderCircle,
  Menu,
  Mic,
  Pause,
  PenLine,
  Play,
  Plus,
  RefreshCw,
  Save,
  Settings,
  Sparkles,
  Trash2,
  Upload,
  Video,
  WandSparkles,
  X,
} from 'lucide-react';
import {
  FormEvent,
  ReactNode,
  CSSProperties,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';

import './styles.css';

type ViewKey = 'overview' | 'projects' | 'recordings' | 'copywriting' | 'scripts' | 'settings';
type CopyStyle = 'funny' | 'emotional' | 'informative' | 'science' | 'marketing';
type Requester = <T>(path: string, init?: RequestInit) => Promise<T>;

interface Workspace {
  id: number;
  name: string;
  storage_mode: string;
  audio_sample_rate: number;
  transcription_language: string;
  project_count: number;
  asset_count: number;
  recording_count: number;
  copywriting_count: number;
  script_count: number;
}

interface Project {
  id: string;
  name: string;
  description: string;
  asset_count: number;
  recording_count: number;
  script_count: number;
  updated_at: string;
}

interface FolderItem {
  id: string;
  parent_id: string | null;
  name: string;
  item_count: number;
}

interface Asset {
  id: string;
  folder_id: string | null;
  name: string;
  kind: 'image' | 'video' | 'audio' | 'document' | 'other';
  mime_type: string;
  size: number;
  file_url: string;
  created_at: string;
}

interface Recording {
  id: string;
  project_id: string | null;
  project_name: string;
  name: string;
  audio_url: string;
  duration_ms: number;
  transcription: string;
  created_at: string;
}

interface Copywriting {
  id: string;
  project_id: string | null;
  title: string;
  content: string;
  style: CopyStyle;
  style_label: string;
  updated_at: string;
}

interface Scene {
  id: string;
  title: string;
  description: string;
  image_url: string;
  duration_seconds: number;
  order: number;
}

interface Script {
  id: string;
  project_id: string | null;
  title: string;
  description: string;
  scenes: Scene[];
  total_duration_seconds: number;
  updated_at: string;
}

interface CreationToolboxAppProps {
  apiBasePath: string;
  requester: Requester;
  showHeader?: boolean;
  onBack?: () => void;
}

const navItems: { key: ViewKey; label: string; icon: typeof LayoutDashboard }[] = [
  { key: 'overview', label: '工作台', icon: LayoutDashboard },
  { key: 'projects', label: '工程与素材', icon: Folder },
  { key: 'recordings', label: '录音', icon: Mic },
  { key: 'copywriting', label: '文案生成', icon: PenLine },
  { key: 'scripts', label: '脚本创作', icon: Clapperboard },
  { key: 'settings', label: '设置', icon: Settings },
];

const styleLabels: Record<CopyStyle, string> = {
  funny: '搞笑', emotional: '情感', informative: '干货', science: '科普', marketing: '营销',
};

const jsonInit = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
});

const formatDate = (value: string) => new Intl.DateTimeFormat('zh-CN', {
  month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
}).format(new Date(value));

const formatSize = (bytes: number) => {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(1)} GB`;
};

const formatDuration = (milliseconds: number) => {
  const totalSeconds = Math.floor(milliseconds / 1000);
  const minutes = Math.floor(totalSeconds / 60).toString().padStart(2, '0');
  const seconds = (totalSeconds % 60).toString().padStart(2, '0');
  return `${minutes}:${seconds}`;
};

function Modal({ title, children, onClose }: { title: string; children: ReactNode; onClose: () => void }) {
  useEffect(() => {
    const close = (event: KeyboardEvent) => event.key === 'Escape' && onClose();
    window.addEventListener('keydown', close);
    return () => window.removeEventListener('keydown', close);
  }, [onClose]);
  return (
    <div className="ct-modal-mask" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section className="ct-modal" role="dialog" aria-modal="true" aria-labelledby="ct-modal-title">
        <header><h2 id="ct-modal-title">{title}</h2><button className="ct-icon-button" aria-label="关闭" onClick={onClose}><X /></button></header>
        {children}
      </section>
    </div>
  );
}

function EmptyState({ icon: Icon, title, detail, action }: {
  icon: typeof Folder; title: string; detail: string; action?: ReactNode;
}) {
  return <div className="ct-empty"><Icon aria-hidden="true" /><strong>{title}</strong><span>{detail}</span>{action}</div>;
}

export function CreationToolboxApp({ apiBasePath, requester, showHeader = true, onBack }: CreationToolboxAppProps) {
  const [view, setView] = useState<ViewKey>('overview');
  const [mobileNav, setMobileNav] = useState(false);
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [recordings, setRecordings] = useState<Recording[]>([]);
  const [copywritings, setCopywritings] = useState<Copywriting[]>([]);
  const [scripts, setScripts] = useState<Script[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [folders, setFolders] = useState<FolderItem[]>([]);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [toast, setToast] = useState('');
  const [error, setError] = useState('');
  const [modal, setModal] = useState<'project' | 'folder' | null>(null);
  const [folderStack, setFolderStack] = useState<FolderItem[]>([]);
  const currentFolder = folderStack[folderStack.length - 1] ?? null;

  const notify = useCallback((message: string) => {
    setToast(message);
    window.setTimeout(() => setToast(''), 3200);
  }, []);

  const errorText = (reason: unknown, fallback: string) => {
    if (reason && typeof reason === 'object' && 'response' in reason) {
      const data = (reason as { response?: { data?: { detail?: string } } }).response?.data;
      if (data?.detail) return data.detail;
    }
    return reason instanceof Error ? reason.message : fallback;
  };

  const refreshAll = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [workspaceData, projectData, recordingData, copyData, scriptData] = await Promise.all([
        requester<Workspace>(`${apiBasePath}/workspace`),
        requester<Project[]>(`${apiBasePath}/projects`),
        requester<Recording[]>(`${apiBasePath}/recordings`),
        requester<Copywriting[]>(`${apiBasePath}/copywritings`),
        requester<Script[]>(`${apiBasePath}/scripts`),
      ]);
      setWorkspace(workspaceData);
      setProjects(projectData);
      setRecordings(recordingData);
      setCopywritings(copyData);
      setScripts(scriptData);
      setSelectedProjectId((current) => current && projectData.some((item) => item.id === current)
        ? current : projectData[0]?.id ?? null);
    } catch (reason) {
      setError(errorText(reason, '创作工作区加载失败'));
    } finally {
      setLoading(false);
    }
  }, [apiBasePath, requester]);

  const loadAssets = useCallback(async (projectId: string | null, folderId: string | null = null) => {
    if (!projectId) {
      setFolders([]);
      setAssets([]);
      return;
    }
    try {
      const [folderData, assetData] = await Promise.all([
        requester<FolderItem[]>(`${apiBasePath}/projects/${projectId}/folders${folderId ? `?parent=${folderId}` : ''}`),
        requester<Asset[]>(`${apiBasePath}/projects/${projectId}/assets${folderId ? `?folder=${folderId}` : ''}`),
      ]);
      setFolders(folderData);
      setAssets(assetData);
    } catch (reason) {
      notify(errorText(reason, '素材加载失败'));
    }
  }, [apiBasePath, notify, requester]);

  useEffect(() => { void refreshAll(); }, [refreshAll]);
  useEffect(() => { void loadAssets(selectedProjectId, currentFolder?.id ?? null); }, [currentFolder?.id, loadAssets, selectedProjectId]);

  const createProject = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const name = String(form.get('name') || '').trim();
    if (!name) return;
    setBusy('project');
    try {
      const project = await requester<Project>(`${apiBasePath}/projects`, jsonInit('POST', {
        name, description: String(form.get('description') || '').trim(),
      }));
      setModal(null);
      await refreshAll();
      setFolderStack([]);
      setSelectedProjectId(project.id);
      setView('projects');
      notify('工程已创建');
    } catch (reason) { notify(errorText(reason, '创建工程失败')); }
    finally { setBusy(''); }
  };

  const createFolder = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selectedProjectId) return;
    const name = String(new FormData(event.currentTarget).get('name') || '').trim();
    if (!name) return;
    setBusy('folder');
    try {
      await requester(`${apiBasePath}/projects/${selectedProjectId}/folders`, jsonInit('POST', {
        name, parent_id: currentFolder?.id ?? null,
      }));
      setModal(null);
      await loadAssets(selectedProjectId, currentFolder?.id ?? null);
      notify('文件夹已创建');
    } catch (reason) { notify(errorText(reason, '创建文件夹失败')); }
    finally { setBusy(''); }
  };

  const uploadAssets = async (files: FileList | null) => {
    if (!selectedProjectId || !files?.length) return;
    setBusy('assets');
    try {
      for (const file of Array.from(files)) {
        const data = new FormData();
        data.append('file', file);
        if (currentFolder) data.append('folder_id', currentFolder.id);
        await requester(`${apiBasePath}/projects/${selectedProjectId}/assets`, { method: 'POST', body: data });
      }
      await Promise.all([loadAssets(selectedProjectId, currentFolder?.id ?? null), refreshAll()]);
      notify(`已上传 ${files.length} 个素材`);
    } catch (reason) { notify(errorText(reason, '上传素材失败')); }
    finally { setBusy(''); }
  };

  const removeAsset = async (asset: Asset) => {
    if (!selectedProjectId || !window.confirm(`删除素材“${asset.name}”？`)) return;
    try {
      await requester(`${apiBasePath}/projects/${selectedProjectId}/assets/${asset.id}`, { method: 'DELETE' });
      await Promise.all([loadAssets(selectedProjectId, currentFolder?.id ?? null), refreshAll()]);
      notify('素材已删除');
    } catch (reason) { notify(errorText(reason, '删除素材失败')); }
  };

  if (loading && !workspace) {
    return <div className="ct-app ct-loading"><LoaderCircle className="ct-spin" /><span>正在打开创作工作区…</span></div>;
  }

  return (
    <div className="ct-app">
      <aside className={`ct-sidebar ${mobileNav ? 'is-open' : ''}`}>
        <div className="ct-brand"><span className="ct-brand-mark"><Clapperboard /></span><div><strong>创作工具箱</strong><small>SHORT VIDEO STUDIO</small></div><button className="ct-icon-button ct-mobile-close" aria-label="关闭导航" onClick={() => setMobileNav(false)}><X /></button></div>
        <nav aria-label="创作工具导航">
          {navItems.map(({ key, label, icon: Icon }) => <button key={key} className={view === key ? 'active' : ''} onClick={() => { setView(key); setMobileNav(false); }}><Icon aria-hidden="true" /><span>{label}</span>{key === 'projects' && projects.length > 0 && <b>{projects.length}</b>}</button>)}
        </nav>
        <div className="ct-sidebar-status"><span><i /> 服务已连接</span><small>数据由 Agent Studio 安全托管</small></div>
      </aside>
      {mobileNav && <button className="ct-nav-scrim" aria-label="关闭导航" onClick={() => setMobileNav(false)} />}
      <main className="ct-main">
        <div className="ct-mobile-bar"><button className="ct-icon-button" aria-label="打开导航" onClick={() => setMobileNav(true)}><Menu /></button><span>创作工具箱</span></div>
        {showHeader && <header className="ct-app-header"><button className="ct-back" onClick={onBack}><ArrowLeft />应用中心</button><div /><button className="ct-icon-button" aria-label="刷新" onClick={() => void refreshAll()}><RefreshCw /></button></header>}
        <div className="ct-content">
          {error ? <EmptyState icon={Gauge} title="工作区暂时不可用" detail={error} action={<button className="ct-button primary" onClick={() => void refreshAll()}>重新加载</button>} /> : <>
            {view === 'overview' && <Overview workspace={workspace} projects={projects} recordings={recordings} scripts={scripts} setView={setView} openProject={() => setModal('project')} />}
            {view === 'projects' && <ProjectsView projects={projects} selectedProjectId={selectedProjectId} selectProject={(id) => { setSelectedProjectId(id); setFolderStack([]); }} folderStack={folderStack} enterFolder={(folder) => setFolderStack((items) => [...items, folder])} goUp={() => setFolderStack((items) => items.slice(0, -1))} folders={folders} assets={assets} busy={busy === 'assets'} openProject={() => setModal('project')} openFolder={() => setModal('folder')} uploadAssets={uploadAssets} removeAsset={removeAsset} />}
            {view === 'recordings' && <RecordingsView apiBasePath={apiBasePath} requester={requester} projects={projects} recordings={recordings} refresh={refreshAll} notify={notify} errorText={errorText} />}
            {view === 'copywriting' && <CopywritingView apiBasePath={apiBasePath} requester={requester} projects={projects} items={copywritings} refresh={refreshAll} notify={notify} errorText={errorText} />}
            {view === 'scripts' && <ScriptsView apiBasePath={apiBasePath} requester={requester} projects={projects} scripts={scripts} refresh={refreshAll} notify={notify} errorText={errorText} />}
            {view === 'settings' && workspace && <SettingsView apiBasePath={apiBasePath} requester={requester} workspace={workspace} refresh={refreshAll} notify={notify} errorText={errorText} />}
          </>}
        </div>
      </main>
      {modal === 'project' && <Modal title="创建视频工程" onClose={() => setModal(null)}><form className="ct-form" onSubmit={createProject}><label><span>工程名称 <b>*</b></span><input name="name" autoFocus required maxLength={120} placeholder="例如：秋日新品发布" /></label><label><span>工程说明</span><textarea name="description" rows={4} maxLength={1000} placeholder="记录主题、目标平台或制作要求" /></label><footer><button type="button" className="ct-button ghost" onClick={() => setModal(null)}>取消</button><button className="ct-button primary" disabled={busy === 'project'}>{busy === 'project' ? <LoaderCircle className="ct-spin" /> : <Plus />}创建工程</button></footer></form></Modal>}
      {modal === 'folder' && <Modal title="新建素材文件夹" onClose={() => setModal(null)}><form className="ct-form" onSubmit={createFolder}><label><span>文件夹名称 <b>*</b></span><input name="name" autoFocus required maxLength={120} placeholder="例如：封面素材" /></label><footer><button type="button" className="ct-button ghost" onClick={() => setModal(null)}>取消</button><button className="ct-button primary" disabled={busy === 'folder'}>创建</button></footer></form></Modal>}
      <div className={`ct-toast ${toast ? 'show' : ''}`} role="status" aria-live="polite"><Check />{toast}</div>
    </div>
  );
}

function PageTitle({ eyebrow, title, detail, actions }: { eyebrow: string; title: string; detail: string; actions?: ReactNode }) {
  return <header className="ct-page-title"><div><span>{eyebrow}</span><h1>{title}</h1><p>{detail}</p></div>{actions && <div className="ct-page-actions">{actions}</div>}</header>;
}

function Overview({ workspace, projects, recordings, scripts, setView, openProject }: {
  workspace: Workspace | null; projects: Project[]; recordings: Recording[]; scripts: Script[]; setView: (view: ViewKey) => void; openProject: () => void;
}) {
  const stats = [
    { label: '视频工程', value: workspace?.project_count ?? projects.length, icon: Folder, tone: 'pink' },
    { label: '素材文件', value: workspace?.asset_count ?? 0, icon: Image, tone: 'blue' },
    { label: '录音片段', value: workspace?.recording_count ?? recordings.length, icon: AudioLines, tone: 'green' },
    { label: '分镜脚本', value: workspace?.script_count ?? scripts.length, icon: Clapperboard, tone: 'amber' },
  ];
  return <>
    <PageTitle eyebrow="CREATOR DESK" title="让每个灵感都有落点" detail="从素材整理、现场录音到文案和分镜，在一个工作台完成短视频前期创作。" actions={<button className="ct-button primary" onClick={openProject}><Plus />新建工程</button>} />
    <section className="ct-stat-grid">{stats.map(({ label, value, icon: Icon, tone }) => <button key={label} className={`ct-stat-card ${tone}`} onClick={() => setView(label === '录音片段' ? 'recordings' : label === '分镜脚本' ? 'scripts' : 'projects')}><span><Icon /></span><strong>{value}</strong><small>{label}</small><ChevronRight /></button>)}</section>
    <section className="ct-overview-grid">
      <div className="ct-panel ct-workflow"><header><div><span className="ct-kicker">QUICK START</span><h2>今天从哪里开始？</h2></div></header><div className="ct-quick-grid">
        <button onClick={openProject}><FolderPlus /><strong>建立工程</strong><span>整理同一条视频的所有素材</span></button>
        <button onClick={() => setView('recordings')}><Mic /><strong>录一段旁白</strong><span>在浏览器内录制并转写</span></button>
        <button onClick={() => setView('copywriting')}><WandSparkles /><strong>生成文案</strong><span>按内容风格快速起稿</span></button>
        <button onClick={() => setView('scripts')}><Clapperboard /><strong>设计分镜</strong><span>拆解场景、画面与时长</span></button>
      </div></div>
      <div className="ct-panel ct-recent"><header><div><span className="ct-kicker">RECENT</span><h2>最近工程</h2></div><button className="ct-text-button" onClick={() => setView('projects')}>查看全部</button></header>{projects.length ? <div className="ct-recent-list">{projects.slice(0, 4).map((project) => <button key={project.id} onClick={() => setView('projects')}><span><Folder /></span><div><strong>{project.name}</strong><small>{project.asset_count} 个素材 · {formatDate(project.updated_at)}</small></div><ChevronRight /></button>)}</div> : <EmptyState icon={Folder} title="还没有工程" detail="创建第一个工程，开始收集素材。" />}</div>
    </section>
  </>;
}

function AssetIcon({ kind }: { kind: Asset['kind'] }) {
  const Icon = kind === 'image' ? Image : kind === 'video' ? Video : kind === 'audio' ? FileAudio : FileText;
  return <Icon aria-hidden="true" />;
}

function ProjectsView({ projects, selectedProjectId, selectProject, folderStack, enterFolder, goUp, folders, assets, busy, openProject, openFolder, uploadAssets, removeAsset }: {
  projects: Project[]; selectedProjectId: string | null; selectProject: (id: string) => void; folderStack: FolderItem[]; enterFolder: (folder: FolderItem) => void; goUp: () => void; folders: FolderItem[]; assets: Asset[]; busy: boolean; openProject: () => void; openFolder: () => void; uploadAssets: (files: FileList | null) => void; removeAsset: (asset: Asset) => void;
}) {
  const selected = projects.find((item) => item.id === selectedProjectId);
  return <>
    <PageTitle eyebrow="PROJECT LIBRARY" title="工程与素材" detail="按项目归档图片、视频、音频和创作文档。" actions={<><button className="ct-button ghost" onClick={openFolder} disabled={!selected}><FolderPlus />新建文件夹</button><label className={`ct-button ghost ${busy || !selected ? 'disabled' : ''}`}><Upload />{busy ? '上传中…' : '上传素材'}<input type="file" multiple hidden disabled={busy || !selected} onChange={(event) => { void uploadAssets(event.target.files); event.target.value = ''; }} /></label><button className="ct-button primary" onClick={openProject}><Plus />新建工程</button></>} />
    {!projects.length ? <div className="ct-panel"><EmptyState icon={Folder} title="建立你的第一个视频工程" detail="工程会把素材、录音、文案和脚本组织在一起。" action={<button className="ct-button primary" onClick={openProject}>创建工程</button>} /></div> : <div className="ct-project-layout">
      <aside className="ct-project-list"><span className="ct-kicker">PROJECTS · {projects.length}</span>{projects.map((project) => <button key={project.id} className={project.id === selectedProjectId ? 'active' : ''} onClick={() => selectProject(project.id)}><span><Folder /></span><div><strong>{project.name}</strong><small>{project.asset_count} 素材 · {project.script_count} 脚本</small></div><ChevronRight /></button>)}</aside>
      <section className="ct-panel ct-assets"><header><div><span className="ct-kicker">MATERIALS</span><h2>{selected?.name}</h2><p className="ct-breadcrumb">{folderStack.length ? <><button onClick={goUp}>返回上一级</button><span>/</span>{folderStack.map((folder) => <span key={folder.id}>{folder.name}</span>)}</> : selected?.description || '这个工程还没有说明。'}</p></div><b>{folders.length + assets.length} 项</b></header>{!folders.length && !assets.length ? <EmptyState icon={Upload} title="素材区还是空的" detail="上传图片、视频、音频或文档，开始搭建内容素材库。" /> : <div className="ct-asset-grid">{folders.map((folder) => <button className="ct-folder-card" key={folder.id} onClick={() => enterFolder(folder)}><span><Folder /></span><strong>{folder.name}</strong><small>{folder.item_count} 项</small></button>)}{assets.map((asset) => <article className="ct-asset-card" key={asset.id}>{asset.kind === 'image' ? <div className="ct-asset-preview"><img src={asset.file_url} alt={asset.name} loading="lazy" /></div> : <div className={`ct-asset-preview ${asset.kind}`}><AssetIcon kind={asset.kind} /></div>}<div><strong title={asset.name}>{asset.name}</strong><small>{formatSize(asset.size)} · {formatDate(asset.created_at)}</small></div><button aria-label={`删除 ${asset.name}`} onClick={() => void removeAsset(asset)}><Trash2 /></button></article>)}</div>}</section>
    </div>}
  </>;
}

function RecordingsView({ apiBasePath, requester, projects, recordings, refresh, notify, errorText }: {
  apiBasePath: string; requester: Requester; projects: Project[]; recordings: Recording[]; refresh: () => Promise<void>; notify: (message: string) => void; errorText: (reason: unknown, fallback: string) => string;
}) {
  const [status, setStatus] = useState<'idle' | 'recording' | 'paused'>('idle');
  const [elapsed, setElapsed] = useState(0);
  const [projectId, setProjectId] = useState(projects[0]?.id ?? '');
  const [transcribing, setTranscribing] = useState('');
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const startedRef = useRef(0);
  const elapsedBeforePause = useRef(0);

  useEffect(() => {
    if (status !== 'recording') return;
    const timer = window.setInterval(() => setElapsed(elapsedBeforePause.current + Date.now() - startedRef.current), 100);
    return () => window.clearInterval(timer);
  }, [status]);
  useEffect(() => () => streamRef.current?.getTracks().forEach((track) => track.stop()), []);

  const start = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (event) => event.data.size && chunksRef.current.push(event.data);
      recorder.onstop = async () => {
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || 'audio/webm' });
        const data = new FormData();
        const stamp = new Date().toISOString().replace(/[:.]/g, '-');
        data.append('audio', blob, `recording-${stamp}.webm`);
        data.append('name', `录音 ${new Date().toLocaleString('zh-CN')}`);
        data.append('duration_ms', String(elapsedBeforePause.current));
        if (projectId) data.append('project_id', projectId);
        try {
          await requester(`${apiBasePath}/recordings`, { method: 'POST', body: data });
          await refresh();
          notify('录音已保存');
        } catch (reason) { notify(errorText(reason, '录音保存失败')); }
      };
      recorder.start(250);
      recorderRef.current = recorder;
      streamRef.current = stream;
      elapsedBeforePause.current = 0;
      startedRef.current = Date.now();
      setElapsed(0);
      setStatus('recording');
    } catch (reason) { notify(errorText(reason, '无法使用麦克风，请检查权限')); }
  };

  const pause = () => {
    recorderRef.current?.pause();
    elapsedBeforePause.current += Date.now() - startedRef.current;
    setElapsed(elapsedBeforePause.current);
    setStatus('paused');
  };
  const resume = () => { recorderRef.current?.resume(); startedRef.current = Date.now(); setStatus('recording'); };
  const stop = () => {
    if (status === 'recording') elapsedBeforePause.current += Date.now() - startedRef.current;
    setElapsed(elapsedBeforePause.current);
    recorderRef.current?.stop();
    streamRef.current?.getTracks().forEach((track) => track.stop());
    setStatus('idle');
  };
  const transcribe = async (recording: Recording) => {
    setTranscribing(recording.id);
    try { await requester(`${apiBasePath}/recordings/${recording.id}/transcribe`, { method: 'POST' }); await refresh(); notify('转写完成'); }
    catch (reason) { notify(errorText(reason, '转写失败')); }
    finally { setTranscribing(''); }
  };
  const remove = async (recording: Recording) => {
    if (!window.confirm(`删除录音“${recording.name}”？`)) return;
    try { await requester(`${apiBasePath}/recordings/${recording.id}`, { method: 'DELETE' }); await refresh(); notify('录音已删除'); }
    catch (reason) { notify(errorText(reason, '删除录音失败')); }
  };

  return <>
    <PageTitle eyebrow="VOICE CAPTURE" title="录音与转写" detail="直接在浏览器录制口播、采访或灵感语音，并归档到视频工程。" />
    <section className="ct-recorder">
      <div className={`ct-record-orb ${status}`}><Mic /><i /></div>
      <strong>{formatDuration(elapsed)}</strong><span>{status === 'recording' ? '正在录音' : status === 'paused' ? '录音已暂停' : '准备就绪'}</span>
      <div className={`ct-wave ${status}`}>{Array.from({ length: 24 }, (_, index) => <i key={index} style={{ '--bar': `${22 + ((index * 37) % 72)}%` } as CSSProperties} />)}</div>
      <div className="ct-record-controls">{status === 'idle' ? <button className="ct-button record" onClick={() => void start()}><Mic />开始录音</button> : <>{status === 'recording' ? <button className="ct-button ghost" onClick={pause}><Pause />暂停</button> : <button className="ct-button ghost" onClick={resume}><Play />继续</button>}<button className="ct-button stop" onClick={stop}><CircleStop />结束并保存</button></>}</div>
      <label className="ct-inline-select"><span>归档工程</span><select value={projectId} onChange={(event) => setProjectId(event.target.value)}><option value="">未分配工程</option>{projects.map((project) => <option value={project.id} key={project.id}>{project.name}</option>)}</select></label>
    </section>
    <section className="ct-panel ct-recording-list"><header><div><span className="ct-kicker">RECORDINGS</span><h2>录音库</h2></div><b>{recordings.length} 段</b></header>{recordings.length ? recordings.map((recording) => <article key={recording.id}><button className="ct-play" aria-label={`播放 ${recording.name}`} onClick={() => new Audio(recording.audio_url).play()}><Play /></button><div><strong>{recording.name}</strong><small>{formatDuration(recording.duration_ms)} · {recording.project_name || '未分配工程'} · {formatDate(recording.created_at)}</small>{recording.transcription && <p>{recording.transcription}</p>}</div><div className="ct-row-actions"><button className="ct-button tiny" disabled={transcribing === recording.id} onClick={() => void transcribe(recording)}>{transcribing === recording.id ? <LoaderCircle className="ct-spin" /> : <FileText />}转写</button><button className="ct-icon-button danger" aria-label="删除录音" onClick={() => void remove(recording)}><Trash2 /></button></div></article>) : <EmptyState icon={AudioLines} title="还没有录音" detail="点击上方按钮，录制你的第一段声音素材。" />}</section>
  </>;
}

function CopywritingView({ apiBasePath, requester, projects, items, refresh, notify, errorText }: {
  apiBasePath: string; requester: Requester; projects: Project[]; items: Copywriting[]; refresh: () => Promise<void>; notify: (message: string) => void; errorText: (reason: unknown, fallback: string) => string;
}) {
  const [style, setStyle] = useState<CopyStyle>('informative');
  const [topic, setTopic] = useState('');
  const [projectId, setProjectId] = useState('');
  const [current, setCurrent] = useState<Copywriting | null>(items[0] ?? null);
  const [draft, setDraft] = useState(items[0]?.content ?? '');
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (!current && items[0]) { setCurrent(items[0]); setDraft(items[0].content); } }, [current, items]);
  const select = (item: Copywriting) => { setCurrent(item); setDraft(item.content); };
  const generate = async (event: FormEvent) => {
    event.preventDefault(); if (!topic.trim()) return; setBusy(true);
    try {
      const item = await requester<Copywriting>(`${apiBasePath}/copywritings/generate`, jsonInit('POST', { topic: topic.trim(), style, project_id: projectId || null }));
      await refresh(); select(item); notify('文案已生成');
    } catch (reason) { notify(errorText(reason, '文案生成失败')); }
    finally { setBusy(false); }
  };
  const save = async () => {
    if (!current) return; setBusy(true);
    try { const item = await requester<Copywriting>(`${apiBasePath}/copywritings/${current.id}`, jsonInit('PATCH', { content: draft })); await refresh(); setCurrent(item); notify('文案已保存'); }
    catch (reason) { notify(errorText(reason, '保存文案失败')); }
    finally { setBusy(false); }
  };
  const remove = async () => {
    if (!current || !window.confirm(`删除文案“${current.title}”？`)) return;
    try { await requester(`${apiBasePath}/copywritings/${current.id}`, { method: 'DELETE' }); setCurrent(null); setDraft(''); await refresh(); notify('文案已删除'); }
    catch (reason) { notify(errorText(reason, '删除文案失败')); }
  };
  return <>
    <PageTitle eyebrow="AI COPY DESK" title="文案生成" detail="用主题和内容风格快速起稿，再在编辑区打磨成可发布版本。" />
    <div className="ct-copy-layout"><form className="ct-panel ct-generator" onSubmit={generate}><span className="ct-kicker">BRIEF</span><h2>描述你的创作主题</h2><label><span>主题 <b>*</b></span><textarea value={topic} onChange={(event) => setTopic(event.target.value)} required rows={4} placeholder="例如：用 60 秒讲清楚普通人如何建立个人知识库" /></label><fieldset><legend>内容风格</legend><div className="ct-style-grid">{(Object.keys(styleLabels) as CopyStyle[]).map((key) => <label key={key}><input type="radio" name="style" checked={style === key} onChange={() => setStyle(key)} /><span>{styleLabels[key]}</span></label>)}</div></fieldset><label><span>关联工程</span><select value={projectId} onChange={(event) => setProjectId(event.target.value)}><option value="">不关联工程</option>{projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label><button className="ct-button primary wide" disabled={busy}>{busy ? <LoaderCircle className="ct-spin" /> : <Sparkles />}生成文案</button></form>
      <section className="ct-panel ct-editor"><header><div><span className="ct-kicker">EDITOR</span><h2>{current?.title || '文案编辑器'}</h2></div>{current && <div><button className="ct-icon-button danger" aria-label="删除文案" onClick={() => void remove()}><Trash2 /></button><button className="ct-button small" onClick={() => void save()} disabled={busy}><Save />保存</button></div>}</header>{current ? <><div className="ct-editor-meta"><span>{current.style_label}</span><small>更新于 {formatDate(current.updated_at)}</small></div><textarea aria-label="文案内容" value={draft} onChange={(event) => setDraft(event.target.value)} /></> : <EmptyState icon={PenLine} title="生成结果会出现在这里" detail="选择风格并输入主题，开始第一版创作。" />}</section>
      <aside className="ct-panel ct-copy-history"><header><div><span className="ct-kicker">LIBRARY</span><h2>文案库</h2></div><b>{items.length}</b></header>{items.length ? items.map((item) => <button key={item.id} className={item.id === current?.id ? 'active' : ''} onClick={() => select(item)}><span>{styleLabels[item.style]}</span><strong>{item.title}</strong><small>{formatDate(item.updated_at)}</small></button>) : <EmptyState icon={FileText} title="暂无文案" detail="生成后会自动保存在这里。" />}</aside>
    </div>
  </>;
}

function ScriptsView({ apiBasePath, requester, projects, scripts, refresh, notify, errorText }: {
  apiBasePath: string; requester: Requester; projects: Project[]; scripts: Script[]; refresh: () => Promise<void>; notify: (message: string) => void; errorText: (reason: unknown, fallback: string) => string;
}) {
  const [selectedId, setSelectedId] = useState(scripts[0]?.id ?? '');
  const [creating, setCreating] = useState(false);
  const [sceneOpen, setSceneOpen] = useState(false);
  const current = scripts.find((item) => item.id === selectedId) ?? scripts[0];
  useEffect(() => { if (!selectedId && scripts[0]) setSelectedId(scripts[0].id); }, [scripts, selectedId]);
  const createScript = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); const form = new FormData(event.currentTarget); setCreating(true);
    try { const script = await requester<Script>(`${apiBasePath}/scripts`, jsonInit('POST', { title: form.get('title'), description: form.get('description'), project_id: form.get('project_id') || null })); await refresh(); setSelectedId(script.id); (event.target as HTMLFormElement).reset(); notify('脚本已创建'); }
    catch (reason) { notify(errorText(reason, '创建脚本失败')); }
    finally { setCreating(false); }
  };
  const addScene = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); if (!current) return; const form = new FormData(event.currentTarget); setCreating(true);
    try { await requester(`${apiBasePath}/scripts/${current.id}/scenes`, jsonInit('POST', { title: form.get('title'), description: form.get('description'), duration_seconds: Number(form.get('duration_seconds') || 5) })); setSceneOpen(false); await refresh(); notify('场景已添加'); }
    catch (reason) { notify(errorText(reason, '添加场景失败')); }
    finally { setCreating(false); }
  };
  const deleteScene = async (scene: Scene) => {
    if (!current || !window.confirm(`删除场景“${scene.title}”？`)) return;
    try { await requester(`${apiBasePath}/scripts/${current.id}/scenes/${scene.id}`, { method: 'DELETE' }); await refresh(); notify('场景已删除'); }
    catch (reason) { notify(errorText(reason, '删除场景失败')); }
  };
  const exportScript = async () => {
    if (!current) return;
    try { const result = await requester<{ filename: string; content: string }>(`${apiBasePath}/scripts/${current.id}/export`); const url = URL.createObjectURL(new Blob([result.content], { type: 'text/plain;charset=utf-8' })); const link = document.createElement('a'); link.href = url; link.download = result.filename; link.click(); URL.revokeObjectURL(url); notify('脚本已导出'); }
    catch (reason) { notify(errorText(reason, '导出脚本失败')); }
  };
  return <>
    <PageTitle eyebrow="STORYBOARD" title="脚本创作" detail="用场景、画面说明和时长搭建可执行的短视频分镜。" actions={current && <><button className="ct-button ghost" onClick={() => void exportScript()}><Download />导出脚本</button><button className="ct-button primary" onClick={() => setSceneOpen(true)}><Plus />添加场景</button></>} />
    <div className="ct-script-layout"><aside className="ct-panel ct-script-list"><header><div><span className="ct-kicker">SCRIPTS</span><h2>脚本库</h2></div><b>{scripts.length}</b></header>{scripts.map((script) => <button key={script.id} className={current?.id === script.id ? 'active' : ''} onClick={() => setSelectedId(script.id)}><Clapperboard /><div><strong>{script.title}</strong><small>{script.scenes.length} 个场景 · {script.total_duration_seconds} 秒</small></div></button>)}<form className="ct-new-script" onSubmit={createScript}><input name="title" required maxLength={200} placeholder="新脚本标题" /><select name="project_id"><option value="">不关联工程</option>{projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select><textarea name="description" rows={2} placeholder="脚本说明（可选）" /><button className="ct-button small wide" disabled={creating}><Plus />创建脚本</button></form></aside>
      <section className="ct-script-canvas">{current ? <><div className="ct-script-hero"><span>脚本</span><h2>{current.title}</h2><p>{current.description || '还没有脚本说明。'}</p><div><b>{current.scenes.length}</b><small>场景</small><b>{current.total_duration_seconds}s</b><small>总时长</small></div></div>{current.scenes.length ? <div className="ct-timeline">{current.scenes.map((scene, index) => <article key={scene.id}><div className="ct-timeline-index"><span>{String(index + 1).padStart(2, '0')}</span><i /></div><div className="ct-scene-card">{scene.image_url ? <img src={scene.image_url} alt="" /> : <div className="ct-scene-placeholder"><Image /></div>}<div><header><span>SCENE {index + 1}</span><b>{scene.duration_seconds} 秒</b></header><h3>{scene.title}</h3><p>{scene.description || '暂无画面说明'}</p></div><button className="ct-icon-button danger" aria-label={`删除场景 ${scene.title}`} onClick={() => void deleteScene(scene)}><Trash2 /></button></div></article>)}</div> : <div className="ct-panel"><EmptyState icon={Clapperboard} title="脚本还没有场景" detail="添加第一个场景，写下画面、台词或镜头动作。" action={<button className="ct-button primary" onClick={() => setSceneOpen(true)}>添加场景</button>} /></div>}</> : <div className="ct-panel"><EmptyState icon={Clapperboard} title="先创建一个脚本" detail="给脚本命名后，就可以逐场景搭建分镜。" /></div>}</section></div>
    {sceneOpen && current && <Modal title={`为“${current.title}”添加场景`} onClose={() => setSceneOpen(false)}><form className="ct-form" onSubmit={addScene}><label><span>场景标题 <b>*</b></span><input name="title" required autoFocus maxLength={200} placeholder="例如：清晨街道空镜" /></label><label><span>画面与台词</span><textarea name="description" rows={5} placeholder="描述景别、动作、旁白或台词" /></label><label><span>预计时长（秒）</span><input name="duration_seconds" type="number" min="1" max="3600" defaultValue="5" required /></label><footer><button type="button" className="ct-button ghost" onClick={() => setSceneOpen(false)}>取消</button><button className="ct-button primary" disabled={creating}>添加场景</button></footer></form></Modal>}
  </>;
}

function SettingsView({ apiBasePath, requester, workspace, refresh, notify, errorText }: {
  apiBasePath: string; requester: Requester; workspace: Workspace; refresh: () => Promise<void>; notify: (message: string) => void; errorText: (reason: unknown, fallback: string) => string;
}) {
  const [busy, setBusy] = useState(false);
  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); const form = new FormData(event.currentTarget); setBusy(true);
    try { await requester(`${apiBasePath}/workspace`, jsonInit('PATCH', { name: form.get('name'), audio_sample_rate: Number(form.get('audio_sample_rate')), transcription_language: form.get('transcription_language') })); await refresh(); notify('设置已保存'); }
    catch (reason) { notify(errorText(reason, '保存设置失败')); }
    finally { setBusy(false); }
  };
  return <><PageTitle eyebrow="PREFERENCES" title="工作区设置" detail="管理创作工作区名称、录音质量和语音识别语言。" /><form className="ct-settings-grid" onSubmit={save}><section className="ct-panel"><span className="ct-kicker">GENERAL</span><h2>基本信息</h2><label><span>工作区名称</span><input name="name" defaultValue={workspace.name} maxLength={120} required /></label><div className="ct-readonly"><span>存储方式</span><strong>Agent Studio 托管存储</strong><small>素材按组织与工程隔离保存</small></div></section><section className="ct-panel"><span className="ct-kicker">AUDIO</span><h2>录音与转写</h2><label><span>录音采样率</span><select name="audio_sample_rate" defaultValue={workspace.audio_sample_rate}><option value="16000">16 kHz · 语音</option><option value="22050">22.05 kHz</option><option value="44100">44.1 kHz · 标准</option><option value="48000">48 kHz · 高质量</option></select></label><label><span>识别语言</span><select name="transcription_language" defaultValue={workspace.transcription_language}><option value="zh-CN">简体中文</option><option value="zh-TW">繁体中文</option><option value="en-US">English</option><option value="ja-JP">日本語</option></select></label></section><footer><button className="ct-button primary" disabled={busy}>{busy ? <LoaderCircle className="ct-spin" /> : <Save />}保存设置</button></footer></form></>;
}

export default CreationToolboxApp;
