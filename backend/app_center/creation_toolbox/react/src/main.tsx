import {
  ArrowLeft,
  Archive,
  AudioLines,
  BarChart3,
  BookOpen,
  Check,
  CheckCircle2,
  ChevronRight,
  CircleStop,
  Clapperboard,
  ClipboardCopy,
  Download,
  ExternalLink,
  FileAudio,
  FileText,
  Folder,
  FolderPlus,
  Gauge,
  GitBranch,
  Image,
  LayoutDashboard,
  Lightbulb,
  LoaderCircle,
  Menu,
  Mic,
  Pause,
  PenLine,
  Play,
  Plus,
  RefreshCw,
  Save,
  Search,
  Send,
  Settings,
  Tags,
  Trash2,
  Upload,
  Video,
  X,
} from 'lucide-react';
import {
  FormEvent,
  ReactNode,
  CSSProperties,
  useCallback,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
} from 'react';

import './styles.css';
import {
  prependCreatedTopic,
  restoreTopicFilters,
  retainVisibleTopicSelection,
  toggleTopicSelection,
  topicFilterReducer,
  topicMatchesFilters,
  topicRowStateClassName,
} from './topicDomain';

type ViewKey = 'overview' | 'topics' | 'projects' | 'capture' | 'content' | 'publishing' | 'analytics' | 'settings';
type CopyStyle = 'funny' | 'emotional' | 'informative' | 'science' | 'marketing';
type TopicStatus = 'pending' | 'ready' | 'adopted' | 'postponed' | 'archived';
type ProjectStage = 'planning' | 'scripting' | 'materials' | 'producing' | 'review' | 'published' | 'retrospective';
type WorkType = 'image_text' | 'long_article' | 'short_video';
type Platform = 'douyin' | 'kuaishou' | 'wechat_channels' | 'xiaohongshu' | 'bilibili' | 'other';
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
  topic_count: number;
  publication_count: number;
}

interface TopicIdea {
  id: string; title: string; notes: string; source_name: string; source_url: string;
  target_platforms: Platform[]; tags: string[]; status: TopicStatus; status_label: string;
  project_count: number; publication_count: number; created_by_name: string; updated_at: string;
  projects?: Project[];
}

interface Project {
  id: string;
  name: string;
  description: string;
  topic: string | null;
  topic_title: string;
  work_type: WorkType;
  work_type_label: string;
  stage: ProjectStage;
  stage_label: string;
  owner_name: string;
  reviewer_name: string;
  planned_publish_at: string | null;
  target_platforms: Platform[];
  tags: string[];
  archived_at: string | null;
  deliverable_count: number;
  publication_count: number;
  asset_count: number;
  copywriting_count: number;
  recording_count: number;
  script_count: number;
  updated_at: string;
}

interface Deliverable {
  id: string; project: string; name: string; version_label: string; platform: Platform | '';
  platform_label: string; file_url: string; download_url: string; external_url: string; duration_ms: number;
  review_status: 'draft' | 'pending' | 'approved' | 'changes_requested';
  review_status_label: string; review_note: string; updated_at: string;
}

interface Metrics {
  id: string; observed_on: string; impressions: number; views: number; completions: number;
  likes: number; comments: number; shares: number; saves: number; followers_gained: number;
  conversions: number; play_rate: number | null; completion_rate: number | null;
  engagement_rate: number | null;
  follow_rate?: number | null; conversion_rate?: number | null; average_watch_seconds?: number;
}

interface StageEvent {
  id: string; from_stage: ProjectStage; from_stage_label: string; to_stage: ProjectStage;
  to_stage_label: string; note: string; changed_by_name: string; created_at: string;
}

interface Publication {
  id: string; project: string; project_name: string; deliverable: string | null;
  platform: Platform; platform_label: string; platform_name: string; account_name: string;
  title: string; external_post_id: string; post_url: string; published_at: string;
  latest_metrics: Metrics | null;
}

interface AnalyticsData {
  summary: Record<string, number | null>;
  stage_distribution: Array<{ stage: ProjectStage; label: string; count: number }>;
  trend: Array<Record<string, string | number>>;
  platforms: Array<Record<string, string | number | null>>;
  topics: { total: number; adopted: number; adoption_rate: number | null; performance: Array<{ topic_id: string; title: string; project_count: number; first_project_hours?: number | null; views: number; engagement_rate: number | null; tags: string[]; source_name: string }>; tag_performance: Array<{ tag: string; topic_count: number; project_count: number; views: number; engagement_rate: number | null }>; source_performance: Array<{ source_name: string; topic_count: number; project_count: number; views: number; engagement_rate: number | null }> };
  insights: Array<{ kind: string; level: string; title: string; detail: string; resource_id: string }>;
  formulas: Record<string, string>;
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
  download_url: string;
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
  { key: 'topics', label: '选题库', icon: Lightbulb },
  { key: 'projects', label: '项目流程', icon: GitBranch },
  { key: 'capture', label: '素材与录音', icon: Folder },
  { key: 'content', label: '内容资料', icon: BookOpen },
  { key: 'publishing', label: '成片与发布', icon: Send },
  { key: 'analytics', label: '数据分析', icon: BarChart3 },
  { key: 'settings', label: '设置', icon: Settings },
];

const styleLabels: Record<CopyStyle, string> = {
  funny: '搞笑', emotional: '情感', informative: '干货', science: '科普', marketing: '营销',
};

const topicStatusLabels: Record<TopicStatus, string> = { pending: '待评估', ready: '待创作', adopted: '已采用', postponed: '暂缓', archived: '已归档' };
const projectStages: Array<{ key: ProjectStage; label: string }> = [
  { key: 'planning', label: '策划' }, { key: 'scripting', label: '脚本' },
  { key: 'materials', label: '素材' }, { key: 'producing', label: '制作中' },
  { key: 'review', label: '待审核' }, { key: 'published', label: '已发布' },
  { key: 'retrospective', label: '复盘完成' },
];
const platformLabels: Record<Platform, string> = { douyin: '抖音', kuaishou: '快手', wechat_channels: '视频号', xiaohongshu: '小红书', bilibili: 'B站', other: '其他' };
const workTypeOptions: Array<{ key: WorkType; label: string; detail: string; icon: typeof Image }> = [
  { key: 'image_text', label: '图文', detail: '多张配图 + 平台文案', icon: Image },
  { key: 'long_article', label: '长图文（公众号）', detail: '长文案 + 段落配图', icon: BookOpen },
  { key: 'short_video', label: '短视频', detail: '文案 + 可选脚本 + 视频', icon: Video },
];
const workTypeLabels = Object.fromEntries(workTypeOptions.map((item) => [item.key, item.label])) as Record<WorkType, string>;

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

async function copyText(value: string) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value);
    return;
  }
  const textarea = document.createElement('textarea');
  textarea.value = value;
  textarea.style.position = 'fixed';
  textarea.style.opacity = '0';
  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand('copy');
  textarea.remove();
}

function Modal({ title, children, onClose }: { title: string; children: ReactNode; onClose: () => void }) {
  const dialogRef = useRef<HTMLElement>(null);
  useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const dialog = dialogRef.current;
    const focusable = () => Array.from(dialog?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), textarea:not(:disabled), select:not(:disabled), [href]') || []);
    window.setTimeout(() => focusable()[0]?.focus(), 0);
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
      if (event.key !== 'Tab') return;
      const items = focusable(); if (!items.length) return;
      const first = items[0]; const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    window.addEventListener('keydown', handleKey);
    return () => { window.removeEventListener('keydown', handleKey); previous?.focus(); };
  }, [onClose]);
  return (
    <div className="ct-modal-mask" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section ref={dialogRef} className="ct-modal" role="dialog" aria-modal="true" aria-labelledby="ct-modal-title">
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
  const [topics, setTopics] = useState<TopicIdea[]>([]);
  const [topicTags, setTopicTags] = useState<string[]>([]);
  const [deliverables, setDeliverables] = useState<Deliverable[]>([]);
  const [publications, setPublications] = useState<Publication[]>([]);
  const [analytics, setAnalytics] = useState<AnalyticsData | null>(null);
  const [recordings, setRecordings] = useState<Recording[]>([]);
  const [copywritings, setCopywritings] = useState<Copywriting[]>([]);
  const [scripts, setScripts] = useState<Script[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [folders, setFolders] = useState<FolderItem[]>([]);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [uploadStatus, setUploadStatus] = useState('');
  const [toast, setToast] = useState('');
  const [error, setError] = useState('');
  const [modal, setModal] = useState<'folder' | null>(null);
  const [folderStack, setFolderStack] = useState<FolderItem[]>([]);
  const currentFolder = folderStack[folderStack.length - 1] ?? null;
  const activeProjects = useMemo(() => projects.filter((item) => !item.archived_at), [projects]);

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
      const [workspaceData, projectData, topicData, tagData, recordingData, copyData, scriptData, deliverableData, publicationData, analyticsData] = await Promise.all([
        requester<Workspace>(`${apiBasePath}/workspace`),
        requester<Project[]>(`${apiBasePath}/projects?include_archived=true`),
        requester<TopicIdea[]>(`${apiBasePath}/topics`),
        requester<string[]>(`${apiBasePath}/topics/tags`),
        requester<Recording[]>(`${apiBasePath}/recordings`),
        requester<Copywriting[]>(`${apiBasePath}/copywritings`),
        requester<Script[]>(`${apiBasePath}/scripts`),
        requester<Deliverable[]>(`${apiBasePath}/deliverables`),
        requester<Publication[]>(`${apiBasePath}/publications`),
        requester<AnalyticsData>(`${apiBasePath}/analytics`),
      ]);
      setWorkspace(workspaceData);
      setProjects(projectData);
      setTopics(topicData);
      setTopicTags(tagData);
      setRecordings(recordingData);
      setCopywritings(copyData);
      setScripts(scriptData);
      setDeliverables(deliverableData);
      setPublications(publicationData);
      setAnalytics(analyticsData);
      setSelectedProjectId((current) => current && projectData.some((item) => item.id === current)
        ? current : projectData[0]?.id ?? null);
    } catch (reason) {
      setError(errorText(reason, '创作工作区加载失败'));
    } finally {
      setLoading(false);
    }
  }, [apiBasePath, requester]);

  const registerCreatedTopic = useCallback((topic: TopicIdea) => {
    setTopics((current) => prependCreatedTopic(current, topic));
    setTopicTags((current) => [...new Set([...topic.tags, ...current])].slice(0, 30));
    setWorkspace((current) => current ? { ...current, topic_count: current.topic_count + 1 } : current);
  }, []);

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
    const selectedFiles = Array.from(files);
    setBusy('assets');
    try {
      for (const [index, file] of selectedFiles.entries()) {
        setUploadStatus(`正在上传 ${index + 1} / ${selectedFiles.length}：${file.name}`);
        const data = new FormData();
        data.append('file', file);
        if (currentFolder) data.append('folder_id', currentFolder.id);
        await requester(`${apiBasePath}/projects/${selectedProjectId}/assets`, { method: 'POST', body: data });
      }
      await Promise.all([loadAssets(selectedProjectId, currentFolder?.id ?? null), refreshAll()]);
      notify(`已上传 ${selectedFiles.length} 个素材`);
    } catch (reason) { notify(errorText(reason, '上传素材失败')); }
    finally { setBusy(''); setUploadStatus(''); }
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
        <div className="ct-brand"><span className="ct-brand-mark"><Clapperboard /></span><div><strong>创作工具箱</strong><small>CREATION STUDIO</small></div><button className="ct-icon-button ct-mobile-close" aria-label="关闭导航" onClick={() => setMobileNav(false)}><X /></button></div>
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
            {view === 'overview' && <Overview projects={activeProjects} topics={topics} deliverables={deliverables} publications={publications} analytics={analytics} setView={setView} />}
            {view === 'topics' && <TopicsView apiBasePath={apiBasePath} requester={requester} topics={topics} recentTags={topicTags} projects={projects} publications={publications} refresh={refreshAll} onCreated={registerCreatedTopic} notify={notify} errorText={errorText} onProject={(id) => { setSelectedProjectId(id); setView('projects'); }} />}
            {view === 'projects' && <ProjectFlowView apiBasePath={apiBasePath} requester={requester} projects={projects} recordings={recordings} copywritings={copywritings} scripts={scripts} deliverables={deliverables} publications={publications} selectedProjectId={selectedProjectId} selectProject={setSelectedProjectId} openSection={setView} refresh={refreshAll} notify={notify} errorText={errorText} startCreation={() => setView('topics')} />}
            {view === 'capture' && <CaptureView projectsView={<ProjectsView projects={activeProjects} selectedProjectId={selectedProjectId} selectProject={(id) => { setSelectedProjectId(id); setFolderStack([]); }} folderStack={folderStack} enterFolder={(folder) => setFolderStack((items) => [...items, folder])} goUp={() => setFolderStack((items) => items.slice(0, -1))} folders={folders} assets={assets} busy={busy === 'assets'} uploadStatus={uploadStatus} startCreation={() => setView('topics')} openFolder={() => setModal('folder')} uploadAssets={uploadAssets} removeAsset={removeAsset} />} recordingsView={<RecordingsView apiBasePath={apiBasePath} requester={requester} projects={activeProjects} recordings={recordings} refresh={refreshAll} notify={notify} errorText={errorText} />} />}
            {view === 'content' && <ContentView copyView={<CopywritingView apiBasePath={apiBasePath} requester={requester} projects={activeProjects} items={copywritings} selectedProjectId={selectedProjectId} refresh={refreshAll} notify={notify} errorText={errorText} />} scriptsView={<ScriptsView apiBasePath={apiBasePath} requester={requester} projects={activeProjects} scripts={scripts} assets={assets} selectedProjectId={selectedProjectId} refresh={refreshAll} notify={notify} errorText={errorText} />} />}
            {view === 'publishing' && <PublishingView apiBasePath={apiBasePath} requester={requester} projects={activeProjects} selectedProjectId={selectedProjectId} deliverables={deliverables} publications={publications} refresh={refreshAll} notify={notify} errorText={errorText} />}
            {view === 'analytics' && <AnalyticsView apiBasePath={apiBasePath} requester={requester} data={analytics} notify={notify} errorText={errorText} />}
            {view === 'settings' && workspace && <SettingsView apiBasePath={apiBasePath} requester={requester} workspace={workspace} refresh={refreshAll} notify={notify} errorText={errorText} />}
          </>}
        </div>
      </main>
      {modal === 'folder' && <Modal title="新建素材文件夹" onClose={() => setModal(null)}><form className="ct-form" onSubmit={createFolder}><label><span>文件夹名称 <b>*</b></span><input name="name" autoFocus required maxLength={120} placeholder="例如：封面素材" /></label><footer><button type="button" className="ct-button ghost" onClick={() => setModal(null)}>取消</button><button className="ct-button primary" disabled={busy === 'folder'}>创建</button></footer></form></Modal>}
      <div className={`ct-toast ${toast ? 'show' : ''}`} role="status" aria-live="polite"><Check />{toast}</div>
    </div>
  );
}

function PageTitle({ eyebrow, title, detail, actions }: { eyebrow: string; title: string; detail: string; actions?: ReactNode }) {
  return <header className="ct-page-title"><div><span>{eyebrow}</span><h1>{title}</h1><p>{detail}</p></div>{actions && <div className="ct-page-actions">{actions}</div>}</header>;
}

function Overview({ projects, topics, deliverables, publications, analytics, setView }: {
  projects: Project[]; topics: TopicIdea[]; deliverables: Deliverable[]; publications: Publication[]; analytics: AnalyticsData | null; setView: (view: ViewKey) => void;
}) {
  const stats = [
    { label: '待评估选题', value: topics.filter((item) => item.status === 'pending').length, icon: Lightbulb, tone: 'pink', view: 'topics' as ViewKey },
    { label: '待创作选题', value: topics.filter((item) => item.status === 'ready').length, icon: PenLine, tone: 'blue', view: 'topics' as ViewKey },
    { label: '待审核成片', value: deliverables.filter((item) => item.review_status === 'pending').length, icon: CheckCircle2, tone: 'amber', view: 'publishing' as ViewKey },
    { label: '待补发布数据', value: publications.filter((item) => !item.latest_metrics).length, icon: Gauge, tone: 'green', view: 'publishing' as ViewKey },
  ];
  return <>
    <PageTitle eyebrow="CREATOR DESK" title="创作数据中枢" detail="从选题沉淀到发布复盘，用真实记录推动每一个创作环节。" actions={<><button className="ct-button ghost" onClick={() => setView('topics')}><Lightbulb />记录选题</button><button className="ct-button primary" onClick={() => setView('topics')}><Plus />选择选题创作</button></>} />
    <section className="ct-stat-grid">{stats.map(({ label, value, icon: Icon, tone, view }) => <button key={label} className={`ct-stat-card ${tone}`} onClick={() => setView(view)}><span><Icon /></span><strong>{value}</strong><small>{label}</small><ChevronRight /></button>)}</section>
    <section className="ct-overview-grid">
      <div className="ct-panel ct-workflow"><header><div><span className="ct-kicker">WORKFLOW</span><h2>项目阶段分布</h2></div><button className="ct-text-button" onClick={() => setView('projects')}>进入项目流程</button></header><div className="ct-stage-summary">{projectStages.map((stage) => { const count = analytics?.stage_distribution.find((item) => item.stage === stage.key)?.count ?? projects.filter((item) => item.stage === stage.key).length; return <div key={stage.key}><span>{stage.label}</span><strong>{count}</strong><i style={{ width: `${projects.length ? Math.max(4, count / projects.length * 100) : 0}%` }} /></div>; })}</div></div>
      <div className="ct-panel ct-recent"><header><div><span className="ct-kicker">RECENT</span><h2>最近工程</h2></div><button className="ct-text-button" onClick={() => setView('projects')}>查看全部</button></header>{projects.length ? <div className="ct-recent-list">{projects.slice(0, 4).map((project) => <button key={project.id} onClick={() => setView('projects')}><span><Folder /></span><div><strong>{project.name}</strong><small>{project.asset_count} 个素材 · {formatDate(project.updated_at)}</small></div><ChevronRight /></button>)}</div> : <EmptyState icon={Folder} title="还没有工程" detail="创建第一个工程，开始收集素材。" />}</div>
    </section>
  </>;
}

function TopicsView({ apiBasePath, requester, topics, recentTags, projects, publications, refresh, onCreated, notify, errorText, onProject }: {
  apiBasePath: string; requester: Requester; topics: TopicIdea[]; recentTags: string[]; projects: Project[]; publications: Publication[];
  refresh: () => Promise<void>; onCreated: (topic: TopicIdea) => void; notify: (message: string) => void; errorText: (reason: unknown, fallback: string) => string; onProject: (id: string) => void;
}) {
  const [filters, dispatchFilters] = useReducer(
    topicFilterReducer,
    undefined,
    () => restoreTopicFilters(sessionStorage.getItem('ct-topic-filters')),
  );
  const { search, status, tag, layout } = filters;
  const [selected, setSelected] = useState<string[]>([]);
  const [currentId, setCurrentId] = useState(topics[0]?.id ?? '');
  const [expanded, setExpanded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [workType, setWorkType] = useState<WorkType>('image_text');
  const current = topics.find((item) => item.id === currentId) ?? topics[0];
  const filtered = useMemo(() => topics.filter((item) => topicMatchesFilters(item, filters)), [filters, topics]);
  useEffect(() => { sessionStorage.setItem('ct-topic-filters', JSON.stringify(filters)); }, [filters]);
  useEffect(() => { if (!currentId && topics[0]) setCurrentId(topics[0].id); }, [currentId, topics]);
  useEffect(() => { setWorkType('image_text'); }, [current?.id]);
  useEffect(() => {
    setSelected((current) => retainVisibleTopicSelection(current, filtered.map((topic) => topic.id)));
  }, [filtered]);

  const postTopic = async (payload: Record<string, unknown>, allowDuplicate = false) => {
    try { return await requester<TopicIdea>(`${apiBasePath}/topics`, jsonInit('POST', { ...payload, allow_duplicate: allowDuplicate })); }
    catch (reason) {
      const response = (reason as { response?: { status?: number; data?: { code?: string } } })?.response;
      if (!allowDuplicate && response?.status === 409 && response.data?.code === 'duplicate_topic' && window.confirm('选题库中已有完全相同的标题，仍要保存吗？')) return postTopic(payload, true);
      notify(errorText(reason, '保存选题失败')); return null;
    }
  };
  const create = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    // SyntheticEvent.currentTarget is cleared after the synchronous handler phase.
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    setBusy(true);
    const payload = { title: String(form.get('title') || '').trim(), notes: String(form.get('notes') || '').trim(), source_name: String(form.get('source_name') || '').trim(), source_url: String(form.get('source_url') || '').trim(), tags: String(form.get('tags') || '').split(/[，,]/).map((item) => item.trim()).filter(Boolean), target_platforms: form.getAll('platforms') };
    const created = await postTopic(payload);
    if (created) {
      formElement.reset();
      setExpanded(false);
      dispatchFilters({ type: 'reveal-created' });
      onCreated(created);
      setCurrentId(created.id);
      notify('选题已记录');
    }
    setBusy(false);
  };
  const update = async (topic: TopicIdea, payload: Record<string, unknown>, message: string) => {
    try { await requester(`${apiBasePath}/topics/${topic.id}`, jsonInit('PATCH', payload)); await refresh(); notify(message); }
    catch (reason) { notify(errorText(reason, '更新选题失败')); }
  };
  const bulk = async (payload: Record<string, unknown>) => {
    if (!selected.length) return;
    try { await requester(`${apiBasePath}/topics/bulk`, jsonInit('POST', { ids: selected, ...payload })); setSelected([]); await refresh(); notify(`已更新 ${selected.length} 个选题`); }
    catch (reason) { notify(errorText(reason, '批量更新失败')); }
  };
  const remove = async (topic: TopicIdea) => {
    if (topic.project_count) { await update(topic, { status: 'archived' }, '已归档选题'); return; }
    if (!window.confirm(`永久删除未关联工程的选题“${topic.title}”？`)) return;
    try { await requester(`${apiBasePath}/topics/${topic.id}`, { method: 'DELETE' }); setCurrentId(''); await refresh(); notify('选题已删除'); }
    catch (reason) { notify(errorText(reason, '删除选题失败')); }
  };
  const createProject = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); if (!current) return; const form = new FormData(event.currentTarget); setBusy(true);
    try { const project = await requester<Project>(`${apiBasePath}/topics/${current.id}/create-project`, jsonInit('POST', { work_type: workType, description: form.get('description'), target_platforms: form.getAll('target_platforms') })); await refresh(); notify('项目已创建，可以开始保存文案和素材'); onProject(project.id); }
    catch (reason) { notify(errorText(reason, '创建工程失败')); }
    finally { setBusy(false); }
  };
  const copyTopic = async () => {
    if (!current) return;
    const details = [current.title, current.notes, current.target_platforms.length ? `目标平台：${current.target_platforms.map((item) => platformLabels[item]).join('、')}` : '', current.tags.length ? `标签：${current.tags.join('、')}` : ''].filter(Boolean).join('\n\n');
    try { await copyText(details); notify('选题信息已复制，可粘贴到外部工具补充细节'); }
    catch { notify('复制失败，请手动选择文字'); }
  };
  const relatedProjects = current ? projects.filter((item) => item.topic === current.id) : [];
  const relatedPublications = publications.filter((item) => relatedProjects.some((project) => project.id === item.project));
  return <>
    <PageTitle eyebrow="TOPIC LIBRARY" title="选题库" detail="先沉淀值得做的方向，再选择图文、长图文或短视频创建项目。" />
    <form className="ct-panel ct-quick-topic" onSubmit={create}><div><Lightbulb /><input name="title" required maxLength={240} aria-label="选题标题" placeholder="快速记录一个有价值的选题…" /><button type="button" className="ct-text-button" onClick={() => setExpanded((value) => !value)} aria-expanded={expanded}>{expanded ? '收起' : '补充详情'}</button><button className="ct-button primary" disabled={busy}><Plus />记录</button></div>{expanded && <section><label><span>创作角度 / 备注</span><textarea name="notes" rows={3} /></label><label><span>来源名称</span><input name="source_name" /></label><label><span>来源链接</span><input name="source_url" type="url" /></label><label><span>标签（逗号分隔）</span><input name="tags" list="ct-recent-tags" /><datalist id="ct-recent-tags">{recentTags.map((item) => <option key={item} value={item} />)}</datalist></label><fieldset><legend>目标平台</legend><div className="ct-check-grid">{(Object.keys(platformLabels) as Platform[]).map((key) => <label key={key}><input type="checkbox" name="platforms" value={key} />{platformLabels[key]}</label>)}</div></fieldset></section>}</form>
    <div className="ct-filterbar"><label><Search /><input list="ct-topic-suggestions" value={search} onChange={(event) => dispatchFilters({ type: 'search', value: event.target.value })} placeholder="搜索标题、来源、备注或标签" /><datalist id="ct-topic-suggestions">{topics.slice(0, 20).map((item) => <option key={item.id} value={item.title} />)}</datalist></label><select aria-label="按状态筛选" value={status} onChange={(event) => dispatchFilters({ type: 'status', value: event.target.value as TopicStatus | '' })}><option value="">全部状态</option>{Object.entries(topicStatusLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select><select aria-label="按标签筛选" value={tag} onChange={(event) => dispatchFilters({ type: 'tag', value: event.target.value })}><option value="">全部标签</option>{recentTags.map((item) => <option key={item}>{item}</option>)}</select><div className="ct-segmented"><button className={layout === 'list' ? 'active' : ''} onClick={() => dispatchFilters({ type: 'layout', value: 'list' })}>列表</button><button className={layout === 'cards' ? 'active' : ''} onClick={() => dispatchFilters({ type: 'layout', value: 'cards' })}>卡片</button></div></div>
    {selected.length > 0 && <div className="ct-bulkbar"><strong>已选 {selected.length} 项</strong><select defaultValue="" aria-label="批量更改状态" onChange={(event) => { if (event.target.value) void bulk({ status: event.target.value }); }}><option value="">更改状态…</option>{Object.entries(topicStatusLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select><form onSubmit={(event) => { event.preventDefault(); const value = String(new FormData(event.currentTarget).get('tag') || '').trim(); if (value) void bulk({ add_tags: [value] }); }}><input name="tag" placeholder="添加标签" /><button className="ct-button small"><Tags />添加</button></form><button className="ct-text-button" onClick={() => setSelected([])}>取消选择</button></div>}
    <div className="ct-topic-layout"><section className={`ct-topic-results ${layout}`}>{filtered.length ? filtered.map((item) => <article key={item.id} className={topicRowStateClassName(item.id, current?.id || '', selected)}><label className="ct-check"><input type="checkbox" aria-label={`选择选题：${item.title}`} checked={selected.includes(item.id)} onChange={(event) => setSelected((ids) => toggleTopicSelection(ids, item.id, event.target.checked))} /><span aria-hidden="true" /></label><button className="ct-topic-main" onClick={() => setCurrentId(item.id)}><div><span className={`ct-status ${item.status}`}>{item.status_label}</span><strong>{item.title}</strong></div><p>{item.notes || '暂无创作角度或备注'}</p><footer><span>{item.source_name || '自主选题'}</span><span>{item.project_count} 个工程</span><span>{formatDate(item.updated_at)}</span></footer><div className="ct-tags">{item.tags.map((value) => <i key={value}>{value}</i>)}</div></button></article>) : <div className="ct-panel"><EmptyState icon={Search} title="没有符合条件的选题" detail="调整搜索或筛选条件后重试。" /></div>}</section>
      <aside className="ct-panel ct-topic-detail">{current ? <>
        <header><div><span className="ct-kicker">TOPIC DETAIL</span><h2>{current.title}</h2></div><button className="ct-icon-button danger" aria-label={current.project_count ? '归档选题' : '删除选题'} onClick={() => void remove(current)}>{current.project_count ? <Archive /> : <Trash2 />}</button></header>
        <div className="ct-detail-body">
          <label><span>状态</span><select value={current.status} onChange={(event) => void update(current, { status: event.target.value }, '状态已更新')}>{Object.entries(topicStatusLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
          <p>{current.notes || '暂无创作角度或备注。'}</p>
          {current.source_url ? <a href={current.source_url} target="_blank" rel="noreferrer">{current.source_name || '查看来源'} ↗</a> : <small>来源：{current.source_name || '未记录'}</small>}
          <div className="ct-tags">{current.tags.map((value) => <i key={value}>{value}</i>)}</div>
          <button type="button" className="ct-button ghost wide" onClick={() => void copyTopic()}><ClipboardCopy />复制选题信息到外部工具</button>
          <section><h3>已创建的项目</h3>{relatedProjects.length ? relatedProjects.map((project) => <button className="ct-linked-row" key={project.id} onClick={() => onProject(project.id)}><span>{project.name}<small>{project.work_type_label} · {project.stage_label} · {project.publication_count} 次发布</small></span><ChevronRight /></button>) : <small>还没有项目</small>}<p className="ct-performance">累计 {relatedPublications.reduce((sum, item) => sum + (item.latest_metrics?.views || 0), 0).toLocaleString()} 播放 · {relatedPublications.length} 条发布记录</p></section>
          <form key={current.id} className="ct-convert-form" onSubmit={createProject}>
            <div><span className="ct-kicker">START CREATION</span><h3>选择作品类型</h3><small>项目名将自动生成为“选题-作品类型”</small></div>
            <div className="ct-work-type-grid">{workTypeOptions.map(({ key, label, detail, icon: Icon }) => <label key={key} className={workType === key ? 'active' : ''}><input type="radio" name="work_type" value={key} checked={workType === key} onChange={() => setWorkType(key)} /><Icon /><span><strong>{label}</strong><small>{detail}</small></span><Check /></label>)}</div>
            <p className="ct-project-name-preview">项目名：<strong>{current.title}-{workTypeLabels[workType]}</strong></p>
            <textarea name="description" rows={3} defaultValue={current.notes} aria-label="项目简报" placeholder="可选：补充创作要求" />
            <div className="ct-check-grid">{(Object.keys(platformLabels) as Platform[]).map((key) => <label key={key}><input type="checkbox" name="target_platforms" value={key} defaultChecked={current.target_platforms.includes(key)} />{platformLabels[key]}</label>)}</div>
            <button className="ct-button primary wide" disabled={busy}><GitBranch />创建项目</button>
          </form>
        </div>
      </> : <EmptyState icon={Lightbulb} title="选择一个选题" detail="在这里查看详情、关联项目和最终表现。" />}</aside>
    </div>
  </>;
}

function ProjectFlowView({ apiBasePath, requester, projects, recordings, copywritings, scripts, deliverables, publications, selectedProjectId, selectProject, openSection, refresh, notify, errorText, startCreation }: {
  apiBasePath: string; requester: Requester; projects: Project[]; recordings: Recording[]; copywritings: Copywriting[]; scripts: Script[]; deliverables: Deliverable[]; publications: Publication[]; selectedProjectId: string | null; selectProject: (id: string) => void; openSection: (view: ViewKey) => void; refresh: () => Promise<void>; notify: (message: string) => void; errorText: (reason: unknown, fallback: string) => string; startCreation: () => void;
}) {
  const [showArchived, setShowArchived] = useState(false);
  const visibleProjects = projects.filter((item) => showArchived || !item.archived_at);
  const current = visibleProjects.find((item) => item.id === selectedProjectId) ?? visibleProjects[0];
  const [events, setEvents] = useState<StageEvent[]>([]);
  const [allAssets, setAllAssets] = useState<Asset[]>([]);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!current) { setEvents([]); setAllAssets([]); return; }
    Promise.all([
      requester<StageEvent[]>(`${apiBasePath}/projects/${current.id}/stage-transitions`),
      requester<Asset[]>(`${apiBasePath}/projects/${current.id}/assets?all=true`),
    ]).then(([nextEvents, nextAssets]) => { setEvents(nextEvents); setAllAssets(nextAssets); })
      .catch(() => { setEvents([]); setAllAssets([]); });
  }, [apiBasePath, current?.id, requester]);
  const currentCopy = copywritings.filter((item) => item.project_id === current?.id);
  const currentScripts = scripts.filter((item) => item.project_id === current?.id);
  const currentDeliverables = deliverables.filter((item) => item.project === current?.id);
  const releaseAssets = allAssets.filter((item) => item.kind === 'image' || item.kind === 'video');
  const expectedKind = current?.work_type === 'short_video' ? 'video' : 'image';
  const mediaReady = releaseAssets.some((item) => item.kind === expectedKind) || (expectedKind === 'video' && currentDeliverables.some((item) => item.download_url || item.external_url));
  const transition = async (stage: ProjectStage) => {
    if (!current || stage === current.stage) return; setBusy(true);
    try { await requester(`${apiBasePath}/projects/${current.id}/stage-transitions`, jsonInit('POST', { to_stage: stage, note })); setNote(''); await refresh(); setEvents(await requester<StageEvent[]>(`${apiBasePath}/projects/${current.id}/stage-transitions`)); notify('项目阶段已更新'); }
    catch (reason) { notify(errorText(reason, '阶段流转失败')); }
    finally { setBusy(false); }
  };
  const toggleArchive = async () => { if (!current) return; const restoring = Boolean(current.archived_at); if (!restoring && !window.confirm(`归档项目“${current.name}”？`)) return; try { await requester(`${apiBasePath}/projects/${current.id}/archive`, jsonInit('POST', { restore: restoring })); await refresh(); notify(restoring ? '项目已恢复' : '项目已归档'); } catch (reason) { notify(errorText(reason, restoring ? '恢复项目失败' : '归档项目失败')); } };
  const copyMaterial = async (item: Copywriting) => { try { await copyText(item.content); notify(`已复制《${item.title}》`); } catch { notify('复制失败，请手动选择文字'); } };
  const checklist = [
    { label: '保存文案', detail: currentCopy.length ? `${currentCopy.length} 份文案` : '粘贴外部工具生成的文案', done: currentCopy.length > 0, icon: FileText, view: 'content' as ViewKey },
    { label: '保存脚本（可选）', detail: currentScripts.length ? `${currentScripts.length} 份脚本` : '短视频可保存脚本和分镜', done: currentScripts.length > 0, optional: true, icon: Clapperboard, view: 'content' as ViewKey },
    { label: current?.work_type === 'short_video' ? '上传视频与配图' : '上传配图', detail: `${releaseAssets.length} 个可发布素材`, done: mediaReady, icon: Image, view: 'capture' as ViewKey },
    { label: '移动端发布准备', detail: currentCopy.length && mediaReady ? '文案和素材已齐全' : '需要至少一份文案和主素材', done: currentCopy.length > 0 && mediaReady, icon: Send, view: 'publishing' as ViewKey },
  ];
  return <>
    <PageTitle eyebrow="PROJECT PIPELINE" title="项目流程" detail="按作品类型保存文案、可选脚本和发布素材。" actions={<><label className="ct-toggle"><input type="checkbox" checked={showArchived} onChange={(event) => setShowArchived(event.target.checked)} />显示已归档</label><button className="ct-button primary" onClick={startCreation}><Lightbulb />选择选题创作</button></>} />
    {!visibleProjects.length ? <div className="ct-panel"><EmptyState icon={GitBranch} title={projects.length ? '没有未归档项目' : '还没有项目'} detail="先从选题库选择选题，再选择作品类型创建项目。" action={<button className="ct-button primary" onClick={startCreation}>选择选题创作</button>} /></div> : <div className="ct-flow-layout">
      <aside className="ct-project-list"><span className="ct-kicker">PROJECTS · {visibleProjects.length}</span>{visibleProjects.map((project) => <button key={project.id} className={project.id === current?.id ? 'active' : ''} onClick={() => selectProject(project.id)}><span><Clapperboard /></span><div><strong>{project.name}</strong><small>{project.work_type_label} · {project.archived_at ? '已归档' : project.stage_label}</small></div><ChevronRight /></button>)}</aside>
      <section className="ct-flow-main">
        <div className="ct-panel ct-project-brief"><header><div><span className="ct-kicker">PROJECT BRIEF</span><h2>{current?.name}</h2><p>{current?.description || '暂无项目简报。'}</p></div><span className={`ct-status ${current?.stage}`}>{current?.archived_at ? '已归档' : current?.stage_label}</span><button className="ct-button tiny" onClick={() => void toggleArchive()}><Archive />{current?.archived_at ? '恢复' : '归档'}</button></header><div className="ct-project-meta"><span>作品类型<strong>{current?.work_type_label}</strong></span><span>来源选题<strong>{current?.topic_title || '独立创建'}</strong></span><span>目标平台<strong>{current?.target_platforms.map((item) => platformLabels[item]).join('、') || '未指定'}</strong></span><span>计划发布<strong>{current?.planned_publish_at ? formatDate(current.planned_publish_at) : '未设置'}</strong></span></div></div>
        <section className="ct-panel ct-creation-checklist"><header><div><span className="ct-kicker">CREATION CHECKLIST</span><h2>制作清单</h2><p>外部工具负责生成，创作工具箱负责归档与发布交付。</p></div><b>{checklist.filter((item) => item.done || item.optional).length} / {checklist.length}</b></header><div className="ct-checklist-grid">{checklist.map(({ label, detail, done, optional, icon: Icon, view }) => <button key={label} className={done ? 'done' : ''} onClick={() => openSection(view)}><i>{done ? <Check /> : <Icon />}</i><span><strong>{label}</strong><small>{done ? '已完成' : optional ? '可选' : detail}</small></span><ChevronRight /></button>)}</div></section>
        <section className="ct-panel ct-release-kit"><header><div><span className="ct-kicker">MOBILE RELEASE KIT</span><h2>移动发布包</h2><p>在手机上复制文案，下载配图或视频后发布到各平台。</p></div><span className={`ct-ready-badge ${currentCopy.length && mediaReady ? 'ready' : ''}`}>{currentCopy.length && mediaReady ? '可发布' : '待补充'}</span></header>
          <div className="ct-release-section"><h3>文案 <small>{currentCopy.length}</small></h3>{currentCopy.length ? currentCopy.map((item) => <article className="ct-release-copy" key={item.id}><div><strong>{item.title}</strong><p>{item.content}</p></div><button className="ct-button ghost" onClick={() => void copyMaterial(item)}><ClipboardCopy />复制文案</button></article>) : <p className="ct-release-empty">还没有关联文案，请先在“内容资料”中保存。</p>}</div>
          <div className="ct-release-section"><h3>配图与视频 <small>{releaseAssets.length + currentDeliverables.length}</small></h3><div className="ct-release-assets">{releaseAssets.map((asset) => <article key={asset.id}>{asset.kind === 'image' ? <img src={asset.file_url} alt={asset.name} loading="lazy" /> : <span><Video /></span>}<div><strong>{asset.name}</strong><small>{asset.kind === 'image' ? '配图' : '视频'} · {formatSize(asset.size)}</small></div><a className="ct-button ghost" href={asset.download_url} download={asset.name}><Download />下载</a></article>)}{currentDeliverables.map((item) => <article key={item.id}><span><Video /></span><div><strong>{item.name}</strong><small>成片 · {item.version_label}</small></div>{item.download_url ? <a className="ct-button ghost" href={item.download_url} download={item.name}><Download />下载</a> : item.external_url ? <a className="ct-button ghost" href={item.external_url} target="_blank" rel="noreferrer"><ExternalLink />打开</a> : null}</article>)}</div>{!releaseAssets.length && !currentDeliverables.length && <p className="ct-release-empty">还没有可下载的配图或视频。</p>}</div>
        </section>
        <section className="ct-project-sections" aria-label="项目内容概览"><button onClick={() => openSection('content')}><FileText /><span>文案 / 脚本<strong>{currentCopy.length} / {currentScripts.length}</strong></span><ChevronRight /></button><button onClick={() => openSection('capture')}><Folder /><span>素材 / 录音<strong>{current?.asset_count || 0} / {recordings.filter((item) => item.project_id === current?.id).length}</strong></span><ChevronRight /></button><button onClick={() => openSection('publishing')}><Video /><span>成片审核<strong>{currentDeliverables.length}</strong></span><ChevronRight /></button><button onClick={() => openSection('publishing')}><Send /><span>发布数据<strong>{publications.filter((item) => item.project === current?.id).length}</strong></span><ChevronRight /></button></section>
        {!current?.archived_at && <section className="ct-panel ct-stage-panel"><header><div><span className="ct-kicker">SEVEN STAGES</span><h2>阶段进度</h2><p>点击任意阶段进行推进或返工，备注会写入历史。</p></div></header><div className="ct-stage-stepper">{projectStages.map((stage, index) => { const activeIndex = projectStages.findIndex((item) => item.key === current?.stage); return <button key={stage.key} className={`${stage.key === current?.stage ? 'active' : ''} ${index < activeIndex ? 'done' : ''}`} disabled={busy} onClick={() => void transition(stage.key)}><i>{index < activeIndex ? <Check /> : index + 1}</i><span>{stage.label}</span></button>; })}</div><label className="ct-stage-note"><span>本次流转备注（可选）</span><input value={note} onChange={(event) => setNote(event.target.value)} placeholder="例如：封面需要调整，退回制作" /></label></section>}
        <section className="ct-panel ct-stage-history"><header><div><span className="ct-kicker">HISTORY</span><h2>阶段记录</h2></div><b>{events.length}</b></header>{events.length ? events.map((event) => <article key={event.id}><i /><div><strong>{event.from_stage_label} → {event.to_stage_label}</strong><p>{event.note || '无备注'}</p><small>{event.changed_by_name || '系统'} · {formatDate(event.created_at)}</small></div></article>) : <EmptyState icon={GitBranch} title="暂无阶段变化" detail="当前项目从策划阶段开始。" />}</section>
      </section>
    </div>}
  </>;
}

function CaptureView({ projectsView, recordingsView }: { projectsView: ReactNode; recordingsView: ReactNode }) {
  const [tab, setTab] = useState<'assets' | 'recordings'>('assets');
  return <><div className="ct-tabs" role="tablist"><button role="tab" aria-selected={tab === 'assets'} className={tab === 'assets' ? 'active' : ''} onClick={() => setTab('assets')}><Folder />素材管理</button><button role="tab" aria-selected={tab === 'recordings'} className={tab === 'recordings' ? 'active' : ''} onClick={() => setTab('recordings')}><Mic />录音与转写</button></div>{tab === 'assets' ? projectsView : recordingsView}</>;
}

function ContentView({ copyView, scriptsView }: { copyView: ReactNode; scriptsView: ReactNode }) {
  const [tab, setTab] = useState<'copy' | 'scripts'>('copy');
  return <><div className="ct-tabs" role="tablist"><button role="tab" aria-selected={tab === 'copy'} className={tab === 'copy' ? 'active' : ''} onClick={() => setTab('copy')}><FileText />文案资料</button><button role="tab" aria-selected={tab === 'scripts'} className={tab === 'scripts' ? 'active' : ''} onClick={() => setTab('scripts')}><Clapperboard />脚本与分镜</button></div>{tab === 'copy' ? copyView : scriptsView}</>;
}

function PublishingView({ apiBasePath, requester, projects, selectedProjectId, deliverables, publications, refresh, notify, errorText }: {
  apiBasePath: string; requester: Requester; projects: Project[]; selectedProjectId: string | null; deliverables: Deliverable[]; publications: Publication[]; refresh: () => Promise<void>; notify: (message: string) => void; errorText: (reason: unknown, fallback: string) => string;
}) {
  const [busy, setBusy] = useState(false);
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [csvPreview, setCsvPreview] = useState<{ valid: boolean; row_count: number; errors: Array<{ row?: number; field?: string; detail?: string; message?: string }>; preview: Array<Record<string, unknown>> } | null>(null);
  const submitDeliverable = async (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); const formElement = event.currentTarget; const form = new FormData(formElement); const duration = Number(form.get('duration_seconds') || 0); const file = form.get('file'); if (file instanceof File && !file.size) form.delete('file'); form.delete('duration_seconds'); form.set('duration_ms', String(duration * 1000)); setBusy(true); try { await requester(`${apiBasePath}/deliverables`, { method: 'POST', body: form }); formElement.reset(); await refresh(); notify('成片版本已添加'); } catch (reason) { notify(errorText(reason, '添加成片失败')); } finally { setBusy(false); } };
  const submitPublication = async (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); const formElement = event.currentTarget; const form = new FormData(formElement); const payload = Object.fromEntries(form.entries()); setBusy(true); try { await requester(`${apiBasePath}/publications`, jsonInit('POST', { ...payload, deliverable: payload.deliverable || null, published_at: new Date(String(payload.published_at)).toISOString() })); formElement.reset(); await refresh(); notify('发布记录已添加，工程已进入已发布阶段'); } catch (reason) { notify(errorText(reason, '添加发布记录失败')); } finally { setBusy(false); } };
  const submitMetrics = async (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); const formElement = event.currentTarget; const form = new FormData(formElement); const publicationId = String(form.get('publication')); const numeric = ['impressions', 'views', 'completions', 'likes', 'comments', 'shares', 'saves', 'followers_gained', 'conversions', 'average_watch_seconds']; const payload: Record<string, string | number> = { observed_on: String(form.get('observed_on')) }; numeric.forEach((key) => { payload[key] = Number(form.get(key) || 0); }); setBusy(true); try { await requester(`${apiBasePath}/publications/${publicationId}/metrics`, jsonInit('POST', payload)); formElement.reset(); await refresh(); notify('指标快照已保存'); } catch (reason) { notify(errorText(reason, '保存指标失败')); } finally { setBusy(false); } };
  const review = async (item: Deliverable, review_status: Deliverable['review_status']) => { const review_note = review_status === 'changes_requested' ? window.prompt('请输入修改意见', item.review_note || '') : item.review_note; if (review_status === 'changes_requested' && review_note === null) return; try { await requester(`${apiBasePath}/deliverables/${item.id}`, jsonInit('PATCH', { review_status, review_note })); await refresh(); notify('审核状态已更新'); } catch (reason) { notify(errorText(reason, '审核失败')); } };
  const importCsv = async (commit: boolean) => { if (!csvFile) return; const form = new FormData(); form.append('file', csvFile); if (commit) form.append('commit', 'true'); setBusy(true); try { const result = await requester<typeof csvPreview>(`${apiBasePath}/metrics-csv/import`, { method: 'POST', body: form }); setCsvPreview(result); if (commit) { await refresh(); notify('CSV 数据已导入'); } else notify('预检完成'); } catch (reason) { const data = (reason as { response?: { data?: typeof csvPreview } })?.response?.data; if (data) setCsvPreview(data); else notify(errorText(reason, 'CSV 预检失败')); } finally { setBusy(false); } };
  const downloadCsv = async (kind: 'template' | 'export') => { try { const content = await requester<string>(`${apiBasePath}/metrics-csv/${kind}`); const url = URL.createObjectURL(new Blob([content], { type: 'text/csv;charset=utf-8' })); const link = document.createElement('a'); link.href = url; link.download = kind === 'template' ? 'creation-metrics-template.csv' : 'creation-metrics-export.csv'; link.click(); URL.revokeObjectURL(url); } catch (reason) { notify(errorText(reason, '下载 CSV 失败')); } };
  return <><PageTitle eyebrow="DELIVERY & RELEASE" title="成片与发布" detail="管理成片版本、审核结论、发布记录和可追溯的累计指标快照。" actions={<button className="ct-button ghost" onClick={() => void downloadCsv('export')}><Download />导出 CSV</button>} />
    <div className="ct-publish-forms"><form key={`deliverable-${selectedProjectId ?? 'none'}`} className="ct-panel ct-data-form" onSubmit={submitDeliverable}><span className="ct-kicker">DELIVERABLE</span><h2>添加成片版本</h2><label><span>项目</span><select name="project" required defaultValue={selectedProjectId ?? ''}><option value="">选择项目</option>{projects.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><div className="ct-form-row"><label><span>名称</span><input name="name" required /></label><label><span>版本</span><input name="version_label" defaultValue="v1" required /></label></div><div className="ct-form-row"><label><span>适配平台</span><select name="platform"><option value="">通用</option>{Object.entries(platformLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label><label><span>时长（秒）</span><input name="duration_seconds" type="number" min="0" /></label></div><label><span>成片文件（与外链二选一）</span><input name="file" type="file" accept="video/*" /></label><label><span>外部链接</span><input name="external_url" type="url" /></label><button className="ct-button primary" disabled={busy}><Video />保存成片</button></form>
      <form key={`publication-${selectedProjectId ?? 'none'}`} className="ct-panel ct-data-form" onSubmit={submitPublication}><span className="ct-kicker">PUBLICATION</span><h2>登记发布作品</h2><label><span>项目</span><select name="project" required defaultValue={selectedProjectId ?? ''}><option value="">选择项目</option>{projects.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><div className="ct-form-row"><label><span>平台</span><select name="platform" required>{Object.entries(platformLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label><label><span>其他平台名称</span><input name="platform_name" placeholder="选择其他时填写" /></label></div><label><span>账号</span><input name="account_name" required /></label><label><span>作品标题</span><input name="title" required /></label><div className="ct-form-row"><label><span>作品 ID</span><input name="external_post_id" /></label><label><span>发布时间</span><input name="published_at" type="datetime-local" required /></label></div><label><span>作品链接（与作品 ID 至少一项）</span><input name="post_url" type="url" /></label><label><span>关联成片</span><select name="deliverable"><option value="">不关联</option>{deliverables.filter((item) => !selectedProjectId || item.project === selectedProjectId).map((item) => <option key={item.id} value={item.id}>{item.name} · {item.version_label}</option>)}</select></label><button className="ct-button primary" disabled={busy}><Send />登记发布</button></form>
      <form className="ct-panel ct-data-form" onSubmit={submitMetrics}><span className="ct-kicker">METRICS</span><h2>补充指标快照</h2><label><span>发布作品</span><select name="publication" required><option value="">选择作品</option>{publications.map((item) => <option key={item.id} value={item.id}>{item.platform_label} · {item.title}</option>)}</select></label><label><span>统计日期</span><input name="observed_on" type="date" required /></label><div className="ct-metric-grid">{[['impressions','曝光'],['views','播放'],['completions','完播'],['likes','点赞'],['comments','评论'],['shares','分享'],['saves','收藏'],['followers_gained','涨粉'],['conversions','转化'],['average_watch_seconds','平均观看秒数']].map(([name, label]) => <label key={name}><span>{label}</span><input name={name} type="number" min="0" step={name === 'average_watch_seconds' ? '0.01' : '1'} defaultValue="0" /></label>)}</div><button className="ct-button primary" disabled={busy}><Gauge />保存快照</button></form></div>
    <section className="ct-panel ct-deliverable-list"><header><div><span className="ct-kicker">REVIEW QUEUE</span><h2>成片审核</h2></div><b>{deliverables.length}</b></header>{deliverables.length ? deliverables.map((item) => <article key={item.id}><Video /><div><strong>{item.name} · {item.version_label}</strong><small>{projects.find((project) => project.id === item.project)?.name} · {item.platform_label || '通用版本'}{item.review_note ? ` · ${item.review_note}` : ''}</small></div><span className={`ct-status ${item.review_status}`}>{item.review_status_label}</span><div className="ct-row-actions">{item.download_url ? <a className="ct-button tiny" href={item.download_url} download={item.name}><Download />下载视频</a> : item.external_url ? <a className="ct-button tiny" href={item.external_url} target="_blank" rel="noreferrer"><ExternalLink />打开外链</a> : null}{item.review_status === 'draft' && <button className="ct-button tiny" onClick={() => void review(item, 'pending')}><Send />送审</button>}<button className="ct-button tiny" onClick={() => void review(item, 'approved')}><Check />通过</button><button className="ct-button tiny" onClick={() => void review(item, 'changes_requested')}>退回</button></div></article>) : <EmptyState icon={Video} title="还没有成片" detail="上传成片文件或记录外部成片链接。" />}</section>
    <section className="ct-panel ct-publication-table"><header><div><span className="ct-kicker">RELEASES</span><h2>发布记录</h2></div><b>{publications.length}</b></header><div className="ct-table-wrap"><table><thead><tr><th>作品</th><th>平台 / 账号</th><th>发布时间</th><th>曝光</th><th>播放</th><th>互动率</th></tr></thead><tbody>{publications.map((item) => <tr key={item.id}><td><strong>{item.title}</strong><small>{item.project_name}</small></td><td>{item.platform_label}<small>{item.account_name}</small></td><td>{formatDate(item.published_at)}</td><td>{item.latest_metrics?.impressions?.toLocaleString() ?? '待补'}</td><td>{item.latest_metrics?.views?.toLocaleString() ?? '—'}</td><td>{item.latest_metrics?.engagement_rate == null ? '—' : `${(item.latest_metrics.engagement_rate * 100).toFixed(2)}%`}</td></tr>)}</tbody></table></div>{!publications.length && <EmptyState icon={Send} title="还没有发布记录" detail="登记真实发布作品后，工程会自动进入已发布阶段。" />}</section>
    <section className="ct-panel ct-csv-panel"><header><div><span className="ct-kicker">CSV IMPORT</span><h2>批量导入发布数据</h2><p>先逐行预检，确认无误后再提交；同作品同一天的数据会覆盖更新。</p></div><button className="ct-button tiny" onClick={() => void downloadCsv('template')}><Download />下载模板</button></header><div className="ct-csv-controls"><input type="file" accept=".csv,text/csv" onChange={(event) => { setCsvFile(event.target.files?.[0] ?? null); setCsvPreview(null); }} /><button className="ct-button ghost" disabled={!csvFile || busy} onClick={() => void importCsv(false)}>预检</button><button className="ct-button primary" disabled={!csvPreview?.valid || busy} onClick={() => void importCsv(true)}>确认导入</button></div>{csvPreview && <div className={`ct-csv-result ${csvPreview.valid ? 'valid' : 'invalid'}`}><strong>{csvPreview.valid ? `预检通过：${csvPreview.row_count} 行` : `发现 ${csvPreview.errors.length} 个错误`}</strong>{csvPreview.errors.map((error, index) => <p key={index}>第 {error.row ?? '?'} 行 · {error.field || '数据'}：{error.detail || error.message || '格式错误'}</p>)}</div>}</section>
  </>;
}

function AnalyticsView({ apiBasePath, requester, data, notify, errorText }: { apiBasePath: string; requester: Requester; data: AnalyticsData | null; notify: (message: string) => void; errorText: (reason: unknown, fallback: string) => string }) {
  const [shown, setShown] = useState(data);
  const [loading, setLoading] = useState(false);
  useEffect(() => setShown(data), [data]);
  const applyFilters = async (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); const form = new FormData(event.currentTarget); const query = new URLSearchParams(); ['start', 'end', 'platform'].forEach((key) => { const value = String(form.get(key) || ''); if (value) query.set(key, value); }); setLoading(true); try { setShown(await requester<AnalyticsData>(`${apiBasePath}/analytics?${query}`)); } catch (reason) { notify(errorText(reason, '分析数据加载失败')); } finally { setLoading(false); } };
  const percent = (value: number | null | undefined) => value == null ? '—' : `${(value * 100).toFixed(2)}%`;
  const summary = shown?.summary ?? {};
  return <><PageTitle eyebrow="MEASUREMENT" title="数据分析" detail="仅使用所选范围内每条作品的最新累计快照，所有公式和规则均可解释。" />
    <form className="ct-analysis-filters" onSubmit={applyFilters}><label><span>开始日期</span><input name="start" type="date" /></label><label><span>结束日期</span><input name="end" type="date" /></label><label><span>平台</span><select name="platform"><option value="">全部平台</option>{Object.entries(platformLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label><button className="ct-button ghost" disabled={loading}>{loading ? <LoaderCircle className="ct-spin" /> : <RefreshCw />}应用筛选</button></form>
    <section className="ct-analytics-kpis">{[['累计播放', Number(summary.views || 0).toLocaleString()], ['播放率', percent(summary.play_rate)], ['完播率', percent(summary.completion_rate)], ['互动率', percent(summary.engagement_rate)], ['选题采用率', percent(shown?.topics.adoption_rate)]].map(([label, value]) => <article className="ct-panel" key={label}><span>{label}</span><strong>{value}</strong></article>)}</section>
    <section className="ct-panel ct-publication-table"><header><div><span className="ct-kicker">PUBLICATION TREND</span><h2>发布数据趋势</h2><p>{shown?.trend.length ? `基于相邻累计快照计算，共 ${shown.trend.length} 个增量日期。` : '添加同一作品的多日累计快照后，将按相邻快照计算增量。'}</p></div></header><div className="ct-table-wrap"><table><thead><tr><th>日期</th><th>新增曝光</th><th>新增播放</th><th>新增完播</th><th>新增互动</th><th>新增涨粉</th><th>新增转化</th></tr></thead><tbody>{shown?.trend.map((row) => <tr key={String(row.date)}><td>{String(row.date)}</td><td>{Number(row.impressions || 0).toLocaleString()}</td><td>{Number(row.views || 0).toLocaleString()}</td><td>{Number(row.completions || 0).toLocaleString()}</td><td>{(Number(row.likes || 0) + Number(row.comments || 0) + Number(row.shares || 0) + Number(row.saves || 0)).toLocaleString()}</td><td>{Number(row.followers_gained || 0).toLocaleString()}</td><td>{Number(row.conversions || 0).toLocaleString()}</td></tr>)}</tbody></table></div></section>
    <div className="ct-analytics-grid"><section className="ct-panel"><header><div><span className="ct-kicker">TOPIC FUNNEL</span><h2>选题采用漏斗</h2></div></header><div className="ct-funnel"><div style={{ width: '100%' }}><strong>{shown?.topics.total ?? 0}</strong><span>全部选题</span></div><div style={{ width: `${Math.max(35, (shown?.topics.adoption_rate || 0) * 100)}%` }}><strong>{shown?.topics.adopted ?? 0}</strong><span>已产生工程</span></div></div><p className="ct-summary-copy">当前每 {shown?.topics.adopted ? Math.max(1, Math.round((shown.topics.total || 0) / shown.topics.adopted)) : '—'} 个选题产生 1 个已采用方向。此处不使用虚构评分。</p></section><section className="ct-panel"><header><div><span className="ct-kicker">STAGES</span><h2>项目阶段分布</h2></div></header><div className="ct-stage-summary">{projectStages.map((stage) => { const row = shown?.stage_distribution.find((item) => item.stage === stage.key); const max = Math.max(1, ...(shown?.stage_distribution.map((item) => item.count) || [1])); return <div key={stage.key}><span>{stage.label}</span><strong>{row?.count ?? 0}</strong><i style={{ width: `${(row?.count || 0) / max * 100}%` }} /></div>; })}</div></section></div>
    <section className="ct-panel ct-publication-table"><header><div><span className="ct-kicker">PLATFORM PERFORMANCE</span><h2>平台表现</h2><p>按平台汇总最新累计快照。</p></div></header><div className="ct-table-wrap"><table><thead><tr><th>平台</th><th>作品数</th><th>曝光</th><th>播放</th><th>互动率</th></tr></thead><tbody>{shown?.platforms.map((row) => <tr key={String(row.platform)}><td>{String(row.label)}</td><td>{Number(row.publication_count || 0)}</td><td>{Number(row.impressions || 0).toLocaleString()}</td><td>{Number(row.views || 0).toLocaleString()}</td><td>{percent(row.engagement_rate as number | null)}</td></tr>)}</tbody></table></div>{!shown?.platforms.length && <EmptyState icon={BarChart3} title="暂无平台数据" detail="添加发布记录和指标快照后会显示对比。" />}</section>
    <section className="ct-panel ct-publication-table"><header><div><span className="ct-kicker">TOPIC PERFORMANCE</span><h2>选题效果</h2><p>通过关联工程与发布数据实时聚合。</p></div></header><div className="ct-table-wrap"><table><thead><tr><th>选题</th><th>标签</th><th>来源</th><th>工程数</th><th>首次转工程</th><th>播放</th><th>互动率</th></tr></thead><tbody>{shown?.topics.performance.map((row) => <tr key={row.topic_id}><td><strong>{row.title}</strong></td><td>{row.tags.join('、') || '—'}</td><td>{row.source_name || '—'}</td><td>{row.project_count}</td><td>{row.first_project_hours == null ? '—' : `${row.first_project_hours} 小时`}</td><td>{row.views.toLocaleString()}</td><td>{percent(row.engagement_rate)}</td></tr>)}</tbody></table></div></section>
    <div className="ct-analytics-grid"><section className="ct-panel ct-publication-table"><header><div><span className="ct-kicker">TAGS</span><h2>标签表现</h2></div></header><div className="ct-table-wrap"><table><thead><tr><th>标签</th><th>选题</th><th>工程</th><th>播放</th><th>互动率</th></tr></thead><tbody>{shown?.topics.tag_performance.map((row) => <tr key={row.tag}><td>{row.tag}</td><td>{row.topic_count}</td><td>{row.project_count}</td><td>{row.views.toLocaleString()}</td><td>{percent(row.engagement_rate)}</td></tr>)}</tbody></table></div></section><section className="ct-panel ct-publication-table"><header><div><span className="ct-kicker">SOURCES</span><h2>来源表现</h2></div></header><div className="ct-table-wrap"><table><thead><tr><th>来源</th><th>选题</th><th>工程</th><th>播放</th><th>互动率</th></tr></thead><tbody>{shown?.topics.source_performance.map((row) => <tr key={row.source_name}><td>{row.source_name}</td><td>{row.topic_count}</td><td>{row.project_count}</td><td>{row.views.toLocaleString()}</td><td>{percent(row.engagement_rate)}</td></tr>)}</tbody></table></div></section></div>
    <section className="ct-panel ct-insights"><header><div><span className="ct-kicker">RULE INSIGHTS</span><h2>规则洞察</h2><p>由逾期、缺数据、累计回退、阶段耗时和同平台四分位规则触发。</p></div><b>{shown?.insights.length ?? 0}</b></header>{shown?.insights.length ? shown.insights.map((item, index) => <article key={`${item.kind}-${item.resource_id}-${index}`} className={item.level}><Gauge /><div><strong>{item.title}</strong><p>{item.detail}</p></div></article>) : <EmptyState icon={CheckCircle2} title="暂未发现异常" detail="规则检查没有发现需要处理的事项。" />}</section>
    <details className="ct-panel ct-formulas"><summary>查看指标公式</summary>{Object.entries(shown?.formulas || {}).map(([key, value]) => <p key={key}><code>{key}</code><span>{value}</span></p>)}</details>
  </>;
}

function AssetIcon({ kind }: { kind: Asset['kind'] }) {
  const Icon = kind === 'image' ? Image : kind === 'video' ? Video : kind === 'audio' ? FileAudio : FileText;
  return <Icon aria-hidden="true" />;
}

function ProjectsView({ projects, selectedProjectId, selectProject, folderStack, enterFolder, goUp, folders, assets, busy, uploadStatus, startCreation, openFolder, uploadAssets, removeAsset }: {
  projects: Project[]; selectedProjectId: string | null; selectProject: (id: string) => void; folderStack: FolderItem[]; enterFolder: (folder: FolderItem) => void; goUp: () => void; folders: FolderItem[]; assets: Asset[]; busy: boolean; uploadStatus: string; startCreation: () => void; openFolder: () => void; uploadAssets: (files: FileList | null) => void; removeAsset: (asset: Asset) => void;
}) {
  const selected = projects.find((item) => item.id === selectedProjectId);
  return <>
    <PageTitle eyebrow="PROJECT LIBRARY" title="项目与素材" detail="按项目归档图片、视频、音频和创作文档；手机端可直接从相册或文件中上传，并随时下载。" actions={<><button className="ct-button ghost" onClick={openFolder} disabled={!selected}><FolderPlus />新建文件夹</button><label className={`ct-button ghost ${busy || !selected ? 'disabled' : ''}`} htmlFor="ct-material-upload"><Upload />{busy ? '上传中…' : '上传素材'}<input id="ct-material-upload" className="ct-file-input" type="file" multiple disabled={busy || !selected} accept="image/*,video/*,audio/*,.pdf,.txt,.md,.srt,.doc,.docx" onChange={(event) => { void uploadAssets(event.target.files); event.target.value = ''; }} /></label><button className="ct-button primary" onClick={startCreation}><Lightbulb />选择选题创作</button></>} />
    {uploadStatus && <div className="ct-upload-status" role="status" aria-live="polite"><LoaderCircle className="ct-spin" aria-hidden="true" /><span>{uploadStatus}</span></div>}
    {!projects.length ? <div className="ct-panel"><EmptyState icon={Folder} title="建立你的第一个创作项目" detail="选择选题和作品类型后，系统会自动创建项目。" action={<button className="ct-button primary" onClick={startCreation}>选择选题创作</button>} /></div> : <div className="ct-project-layout">
      <aside className="ct-project-list"><span className="ct-kicker">PROJECTS · {projects.length}</span>{projects.map((project) => <button key={project.id} className={project.id === selectedProjectId ? 'active' : ''} onClick={() => selectProject(project.id)}><span><Folder /></span><div><strong>{project.name}</strong><small>{project.asset_count} 素材 · {project.script_count} 脚本</small></div><ChevronRight /></button>)}</aside>
      <section className="ct-panel ct-assets"><header><div><span className="ct-kicker">MATERIALS</span><h2>{selected?.name}</h2><p className="ct-breadcrumb">{folderStack.length ? <><button onClick={goUp}>返回上一级</button><span>/</span>{folderStack.map((folder) => <span key={folder.id}>{folder.name}</span>)}</> : selected?.description || '这个工程还没有说明。'}</p></div><b>{folders.length + assets.length} 项</b></header>{!folders.length && !assets.length ? <EmptyState icon={Upload} title="素材区还是空的" detail="上传图片、视频、音频或文档，开始搭建内容素材库。" /> : <div className="ct-asset-grid">{folders.map((folder) => <button className="ct-folder-card" key={folder.id} onClick={() => enterFolder(folder)}><span><Folder /></span><strong>{folder.name}</strong><small>{folder.item_count} 项</small></button>)}{assets.map((asset) => <article className="ct-asset-card" key={asset.id}>{asset.kind === 'image' ? <div className="ct-asset-preview"><img src={asset.file_url} alt={asset.name} loading="lazy" /></div> : <div className={`ct-asset-preview ${asset.kind}`}><AssetIcon kind={asset.kind} /></div>}<div className="ct-asset-meta"><strong title={asset.name}>{asset.name}</strong><small>{formatSize(asset.size)} · {formatDate(asset.created_at)}</small></div><div className="ct-asset-actions"><a href={asset.download_url} download={asset.name} aria-label={`下载 ${asset.name}`} title="下载素材"><Download aria-hidden="true" /></a><button aria-label={`删除 ${asset.name}`} title="删除素材" onClick={() => void removeAsset(asset)}><Trash2 aria-hidden="true" /></button></div></article>)}</div>}</section>
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
    <PageTitle eyebrow="VOICE CAPTURE" title="录音与转写" detail="直接在浏览器录制口播、采访或灵感语音，并归档到创作项目。" />
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

function CopywritingView({ apiBasePath, requester, projects, items, selectedProjectId, refresh, notify, errorText }: {
  apiBasePath: string; requester: Requester; projects: Project[]; items: Copywriting[]; selectedProjectId: string | null; refresh: () => Promise<void>; notify: (message: string) => void; errorText: (reason: unknown, fallback: string) => string;
}) {
  const [style, setStyle] = useState<CopyStyle>('informative');
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [projectId, setProjectId] = useState(selectedProjectId ?? '');
  const [current, setCurrent] = useState<Copywriting | null>(items[0] ?? null);
  const [draft, setDraft] = useState(items[0]?.content ?? '');
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (!current && items[0]) { setCurrent(items[0]); setDraft(items[0].content); } }, [current, items]);
  useEffect(() => { if (selectedProjectId) setProjectId(selectedProjectId); }, [selectedProjectId]);
  useEffect(() => {
    const projectItem = items.find((item) => item.project_id === selectedProjectId);
    if (projectItem) { setCurrent(projectItem); setDraft(projectItem.content); }
  }, [selectedProjectId]);
  const select = (item: Copywriting) => { setCurrent(item); setDraft(item.content); };
  const create = async (event: FormEvent) => {
    event.preventDefault(); if (!title.trim() || !content.trim()) return; setBusy(true);
    try {
      const item = await requester<Copywriting>(`${apiBasePath}/copywritings`, jsonInit('POST', { title: title.trim(), content: content.trim(), style, project_id: projectId || null }));
      await refresh(); select(item); setTitle(''); setContent(''); notify('文案资料已创建');
    } catch (reason) { notify(errorText(reason, '创建文案失败')); }
    finally { setBusy(false); }
  };
  const save = async () => {
    if (!current) return; setBusy(true);
    try { const item = await requester<Copywriting>(`${apiBasePath}/copywritings/${current.id}`, jsonInit('PATCH', { content: draft })); await refresh(); setCurrent(item); notify('文案已保存'); }
    catch (reason) { notify(errorText(reason, '保存文案失败')); }
    finally { setBusy(false); }
  };
  const copy = async () => { try { await copyText(draft); notify('文案已复制，可直接粘贴到发布平台'); } catch { notify('复制失败，请手动选择文字'); } };
  const remove = async () => {
    if (!current || !window.confirm(`删除文案“${current.title}”？`)) return;
    try { await requester(`${apiBasePath}/copywritings/${current.id}`, { method: 'DELETE' }); setCurrent(null); setDraft(''); await refresh(); notify('文案已删除'); }
    catch (reason) { notify(errorText(reason, '删除文案失败')); }
  };
  return <>
    <PageTitle eyebrow="COPY MATERIALS" title="文案资料" detail="仅维护人工创建或导入的文案资料，不自动生成内容。" />
    <div className="ct-copy-layout"><form className="ct-panel ct-generator" onSubmit={create}><span className="ct-kicker">NEW MATERIAL</span><h2>新建文案资料</h2><label className="ct-button ghost"><Upload />导入 TXT / Markdown<input type="file" hidden accept=".txt,.md,text/plain,text/markdown" onChange={(event) => { const file = event.target.files?.[0]; if (!file) return; file.text().then((value) => { setTitle(file.name.replace(/\.(txt|md)$/i, '')); setContent(value); }); event.target.value = ''; }} /></label><label><span>标题 <b>*</b></span><input value={title} onChange={(event) => setTitle(event.target.value)} required placeholder="输入文案标题" /></label><label><span>文案内容 <b>*</b></span><textarea value={content} onChange={(event) => setContent(event.target.value)} required rows={7} placeholder="粘贴或输入你的文案内容" /></label><fieldset><legend>内容分类</legend><div className="ct-style-grid">{(Object.keys(styleLabels) as CopyStyle[]).map((key) => <label key={key}><input type="radio" name="style" checked={style === key} onChange={() => setStyle(key)} /><span>{styleLabels[key]}</span></label>)}</div></fieldset><label><span>关联工程</span><select value={projectId} onChange={(event) => setProjectId(event.target.value)}><option value="">不关联工程</option>{projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label><button className="ct-button primary wide" disabled={busy}>{busy ? <LoaderCircle className="ct-spin" /> : <Plus />}创建资料</button></form>
      <section className="ct-panel ct-editor"><header><div><span className="ct-kicker">EDITOR</span><h2>{current?.title || '文案编辑器'}</h2></div>{current && <div><button className="ct-icon-button danger" aria-label="删除文案" onClick={() => void remove()}><Trash2 /></button><button className="ct-button small" onClick={() => void copy()}><ClipboardCopy />复制文案</button><button className="ct-button small" onClick={() => void save()} disabled={busy}><Save />保存</button></div>}</header>{current ? <><div className="ct-editor-meta"><span>{current.style_label}</span><small>更新于 {formatDate(current.updated_at)}</small></div><textarea aria-label="文案内容" value={draft} onChange={(event) => setDraft(event.target.value)} /></> : <EmptyState icon={PenLine} title="文案会出现在这里" detail="粘贴外部工具生成的文案，并关联到当前项目。" />}</section>
      <aside className="ct-panel ct-copy-history"><header><div><span className="ct-kicker">LIBRARY</span><h2>文案库</h2></div><b>{items.length}</b></header>{items.length ? items.map((item) => <button key={item.id} className={item.id === current?.id ? 'active' : ''} onClick={() => select(item)}><span>{styleLabels[item.style]}</span><strong>{item.title}</strong><small>{formatDate(item.updated_at)}</small></button>) : <EmptyState icon={FileText} title="暂无文案" detail="手工创建的文案会保存在这里。" />}</aside>
    </div>
  </>;
}

function ScriptsView({ apiBasePath, requester, projects, scripts, assets, selectedProjectId, refresh, notify, errorText }: {
  apiBasePath: string; requester: Requester; projects: Project[]; scripts: Script[]; assets: Asset[]; selectedProjectId: string | null; refresh: () => Promise<void>; notify: (message: string) => void; errorText: (reason: unknown, fallback: string) => string;
}) {
  const [selectedId, setSelectedId] = useState(scripts[0]?.id ?? '');
  const [creating, setCreating] = useState(false);
  const [sceneOpen, setSceneOpen] = useState(false);
  const current = scripts.find((item) => item.id === selectedId) ?? scripts[0];
  useEffect(() => { if (!selectedId && scripts[0]) setSelectedId(scripts[0].id); }, [scripts, selectedId]);
  useEffect(() => {
    const projectScript = scripts.find((item) => item.project_id === selectedProjectId);
    if (projectScript) setSelectedId(projectScript.id);
  }, [selectedProjectId]);
  const createScript = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); const formElement = event.currentTarget; const form = new FormData(formElement); setCreating(true);
    try { const script = await requester<Script>(`${apiBasePath}/scripts`, jsonInit('POST', { title: form.get('title'), description: form.get('description'), project_id: form.get('project_id') || null })); await refresh(); setSelectedId(script.id); formElement.reset(); notify('脚本已创建'); }
    catch (reason) { notify(errorText(reason, '创建脚本失败')); }
    finally { setCreating(false); }
  };
  const addScene = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); if (!current) return; const form = new FormData(event.currentTarget); setCreating(true);
    try { await requester(`${apiBasePath}/scripts/${current.id}/scenes`, jsonInit('POST', { title: form.get('title'), description: form.get('description'), duration_seconds: Number(form.get('duration_seconds') || 5), image_asset_id: form.get('image_asset_id') || null })); setSceneOpen(false); await refresh(); notify('场景已添加'); }
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
  const moveScene = async (index: number, direction: -1 | 1) => {
    if (!current) return; const next = index + direction; if (next < 0 || next >= current.scenes.length) return;
    const ids = current.scenes.map((item) => item.id); [ids[index], ids[next]] = [ids[next], ids[index]];
    try { await requester(`${apiBasePath}/scripts/${current.id}/scenes/reorder`, jsonInit('POST', { scene_ids: ids })); await refresh(); notify('分镜顺序已更新'); }
    catch (reason) { notify(errorText(reason, '调整顺序失败')); }
  };
  return <>
    <PageTitle eyebrow="STORYBOARD" title="脚本与分镜（可选）" detail="可直接保存外部工具生成的脚本，短视频还可继续拆分场景。" actions={current && <><button className="ct-button ghost" onClick={() => void exportScript()}><Download />导出脚本</button><button className="ct-button primary" onClick={() => setSceneOpen(true)}><Plus />添加场景</button></>} />
    <div className="ct-script-layout"><aside className="ct-panel ct-script-list"><header><div><span className="ct-kicker">SCRIPTS</span><h2>脚本库</h2></div><b>{scripts.length}</b></header>{scripts.map((script) => <button key={script.id} className={current?.id === script.id ? 'active' : ''} onClick={() => setSelectedId(script.id)}><Clapperboard /><div><strong>{script.title}</strong><small>{script.scenes.length} 个场景 · {script.total_duration_seconds} 秒</small></div></button>)}<form key={selectedProjectId ?? 'none'} className="ct-new-script" onSubmit={createScript}><input name="title" required maxLength={200} placeholder="新脚本标题" /><select name="project_id" defaultValue={selectedProjectId ?? ''}><option value="">不关联项目</option>{projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select><textarea name="description" rows={7} placeholder="脚本正文（可选）：可粘贴完整脚本、台词或拍摄说明" /><button className="ct-button small wide" disabled={creating}><Plus />保存脚本</button></form></aside>
      <section className="ct-script-canvas">{current ? <><div className="ct-script-hero"><span>脚本</span><h2>{current.title}</h2><p>{current.description || '还没有脚本说明。'}</p><div><b>{current.scenes.length}</b><small>场景</small><b>{current.total_duration_seconds}s</b><small>总时长</small></div></div>{current.scenes.length ? <div className="ct-timeline">{current.scenes.map((scene, index) => <article key={scene.id}><div className="ct-timeline-index"><span>{String(index + 1).padStart(2, '0')}</span><i /></div><div className="ct-scene-card">{scene.image_url ? <img src={scene.image_url} alt="" /> : <div className="ct-scene-placeholder"><Image /></div>}<div><header><span>SCENE {index + 1}</span><b>{scene.duration_seconds} 秒</b></header><h3>{scene.title}</h3><p>{scene.description || '暂无画面说明'}</p><div className="ct-scene-order"><button disabled={index === 0} onClick={() => void moveScene(index, -1)} aria-label={`上移 ${scene.title}`}>↑ 上移</button><button disabled={index === current.scenes.length - 1} onClick={() => void moveScene(index, 1)} aria-label={`下移 ${scene.title}`}>↓ 下移</button></div></div><button className="ct-icon-button danger" aria-label={`删除场景 ${scene.title}`} onClick={() => void deleteScene(scene)}><Trash2 /></button></div></article>)}</div> : <div className="ct-panel"><EmptyState icon={Clapperboard} title="脚本还没有场景" detail="添加第一个场景，写下画面、台词或镜头动作。" action={<button className="ct-button primary" onClick={() => setSceneOpen(true)}>添加场景</button>} /></div>}</> : <div className="ct-panel"><EmptyState icon={Clapperboard} title="先创建一个脚本" detail="给脚本命名后，就可以逐场景搭建分镜。" /></div>}</section></div>
    {sceneOpen && current && <Modal title={`为“${current.title}”添加场景`} onClose={() => setSceneOpen(false)}><form className="ct-form" onSubmit={addScene}><label><span>场景标题 <b>*</b></span><input name="title" required autoFocus maxLength={200} placeholder="例如：清晨街道空镜" /></label><label><span>画面与台词</span><textarea name="description" rows={5} placeholder="描述景别、动作、旁白或台词" /></label><label><span>关联图片素材</span><select name="image_asset_id"><option value="">暂不关联</option>{assets.filter((asset) => asset.kind === 'image').map((asset) => <option key={asset.id} value={asset.id}>{asset.name}</option>)}</select></label><label><span>预计时长（秒）</span><input name="duration_seconds" type="number" min="1" max="3600" defaultValue="5" required /></label><footer><button type="button" className="ct-button ghost" onClick={() => setSceneOpen(false)}>取消</button><button className="ct-button primary" disabled={creating}>添加场景</button></footer></form></Modal>}
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
