import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Button, Drawer, Dropdown, Input, Modal, Spin, message } from 'antd';
import { ChevronDown, ChevronRight, Folder, Menu, Monitor, MoreHorizontal, Plus, Sparkles, SquarePen, X } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import ChatContainer from '@/components/Chat/ChatContainer';
import ChatWorkspaceSidebar from '@/components/Chat/ChatWorkspaceSidebar';
import { ChatConnectionContext } from '@/components/Chat/ChatConnectionContext';
import type { ComposerContext } from '@/components/Chat/MessageInput';
import { createConversationStore, type Conversation, type ConversationDetail } from '@/stores/useConversationStore';
import type { Project } from '@/stores/useProjectStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import useMediaQuery from '@/hooks/useMediaQuery';
import { createCoworkApi, coworkError } from '@/services/cowork';
import FolderPickerModal from './FolderPickerModal';
import './CoWorkPage.css';

type CoworkApi = ReturnType<typeof createCoworkApi>;
type Selection = Pick<ComposerContext, 'projectId' | 'workingDirectory'>;
type Page<T> = { results: T[]; next: string | null };

const workspaceIsLocked = (conversation: ConversationDetail | null) => Boolean(
  conversation?.workspace_locked || conversation?.messages.some(item => item.role === 'user'),
);

function useProjects(api: CoworkApi, revision: number, selectedId?: number) {
  const [items, setItems] = useState<Project[]>([]);
  const [pages, setPages] = useState(1);
  const [more, setMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError('');
    void (async () => {
      const collected: Project[] = [];
      let next = false;
      for (let page = 1; page <= pages; page += 1) {
        const result = await api.get<Page<Project> | Project[]>('/projects/', { page }, { signal: controller.signal }).catch(error => {
          if (page > 1 && error?.response?.status === 404) return { results: [], next: null };
          throw error;
        });
        collected.push(...(Array.isArray(result) ? result : result.results));
        next = !Array.isArray(result) && Boolean(result.next);
        if (!next) break;
      }
      if (selectedId && Number.isSafeInteger(selectedId) && selectedId > 0 && !collected.some(item => item.id === selectedId)) {
        const selected = await api.get<Project>(`/projects/${selectedId}/`, undefined, { signal: controller.signal }).catch(error => {
          if (error?.response?.status === 404) return null;
          throw error;
        });
        if (selected?.id === selectedId) collected.unshift(selected);
      }
      if (!controller.signal.aborted) { setItems(collected); setMore(next); }
    })().catch(error => {
      if (!controller.signal.aborted) setError(coworkError(error, '项目加载失败'));
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [api, revision, pages, selectedId]);
  return { items, setItems, more, loading, error, loadMore: () => setPages(value => value + 1) };
}

function useConversations(api: CoworkApi, revision: number, projectId?: number, enabled = true) {
  const [items, setItems] = useState<Conversation[]>([]);
  const [pages, setPages] = useState(1);
  const [more, setMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    setLoading(true);
    setError('');
    void (async () => {
      const collected: Conversation[] = [];
      let next = false;
      for (let page = 1; page <= pages; page += 1) {
        const result = await api.get<Page<Conversation>>('/conversations/', {
          page, ...(projectId ? { project_id: projectId } : {}),
        }, { signal: controller.signal }).catch(error => {
          if (page > 1 && error?.response?.status === 404) return { results: [], next: null };
          throw error;
        });
        collected.push(...result.results.map(item => ({ ...item, id: String(item.id) })));
        next = Boolean(result.next);
        if (!next) break;
      }
      if (!controller.signal.aborted) { setItems(collected); setMore(next); }
    })().catch(error => {
      if (!controller.signal.aborted) setError(coworkError(error, '对话列表加载失败'));
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [api, projectId, enabled, pages, revision, retry]);
  return { items, more, loading, error, loadMore: () => setPages(value => value + 1), retry: () => setRetry(value => value + 1) };
}

function ConversationRows({ list, selected, onSelect }: {
  list: ReturnType<typeof useConversations>; selected: string | null;
  onSelect: (conversation: Conversation) => void;
}) {
  return <>
    {list.items.map(item => <button key={item.id} className="cowork-conversation"
      aria-current={selected === item.id ? 'page' : undefined} title={item.title || '新对话'}
      onClick={() => onSelect(item)}>{item.title || '新对话'}</button>)}
    {list.error && <div className="cowork-list-state" role="alert">{list.error}<Button type="link" onClick={list.retry}>重试</Button></div>}
    {list.loading && <div className="cowork-list-state"><Spin size="small" /></div>}
    {!list.loading && !list.error && !list.items.length && <p className="cowork-list-state">暂无对话</p>}
    {list.more && <button className="cowork-more" disabled={list.loading} onClick={list.loadMore}>Show more</button>}
  </>;
}

function ProjectRow({ project, api, revision, selected, active, disabled, onNew, onSelect, onManage, onSelectionVisible }: {
  project: Project; api: CoworkApi; revision: number; selected: string | null; active: boolean; disabled: boolean;
  onNew: (project: Project) => void; onSelect: (conversation: Conversation) => void;
  onManage: (project: Project, action: 'rename' | 'delete') => void;
  onSelectionVisible: (id: string | null) => void;
}) {
  const [expanded, setExpanded] = useState(active);
  const list = useConversations(api, revision, project.id, expanded);
  useEffect(() => { if (active) setExpanded(true); }, [active]);
  useEffect(() => {
    if (!active) return;
    onSelectionVisible(expanded && list.items.some(item => item.id === selected) ? selected : null);
    return () => onSelectionVisible(null);
  }, [active, expanded, list.items, selected, onSelectionVisible]);
  return <div className="cowork-project">
    <div className="cowork-project-row">
      <button className="cowork-icon" aria-label={`${expanded ? '收起' : '展开'} ${project.title}`} aria-expanded={expanded}
        onClick={() => setExpanded(value => !value)}>{expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}</button>
      <button className="cowork-project-name" disabled={disabled} onClick={() => onNew(project)} title={project.working_directory}>
        <Folder size={17} aria-hidden="true" /><span>{project.title}</span>
      </button>
      <button className="cowork-icon cowork-project-action" disabled={disabled} onClick={() => onNew(project)}
        aria-label={`在 ${project.title} 中新建对话`} title="New chat"><SquarePen size={17} aria-hidden="true" /></button>
      <Dropdown trigger={['click']} menu={{ items: [{ key: 'rename', label: '重命名' }, { key: 'delete', label: '移除项目', danger: true }],
        onClick: ({ key }) => onManage(project, key as 'rename' | 'delete') }}>
        <button className="cowork-icon cowork-project-action" disabled={disabled} aria-label={`管理 ${project.title}`}><MoreHorizontal size={17} /></button>
      </Dropdown>
    </div>
    {expanded && <div className="cowork-project-chats"><ConversationRows list={list} selected={active ? selected : null} onSelect={onSelect} /></div>}
  </div>;
}

export default function CoWorkPage() {
  const organizationId = useOrganizationStore(state => state.currentOrganizationId);
  const userId = useAuthStore(state => state.user?.id);
  return <CoWorkWorkspace key={`${organizationId}:${userId}`} />;
}

function CoWorkWorkspace() {
  const [api] = useState(createCoworkApi);
  const [store] = useState(() => createConversationStore(undefined, api, 'cowork-conversations'));
  const current = store(state => state.currentConversation);
  const runStatus = store(state => state.activeRun?.status);
  const loadingConversation = store(state => state.isLoading);
  const streamingMessageId = store(state => state.streamingMessageId);
  const [params, setParams] = useSearchParams();
  const mounted = useRef(true);
  const locationKey = useRef(params.toString());
  locationKey.current = params.toString();
  const conversationId = params.get('conversation');
  const requestedProject = params.get('project');
  const draftProjectId = requestedProject ? Number(requestedProject) : undefined;
  const ownsConversation = current?.id === conversationId;
  const projectId = conversationId ? (ownsConversation ? current?.project ?? undefined : undefined) : draftProjectId;
  const [revision, setRevision] = useState(0);
  const { items: projects, setItems: setProjects, loading: projectsLoading, error: projectsError, more: projectsMore, loadMore: loadMoreProjects } = useProjects(api, revision, projectId);
  const [projectsExpanded, setProjectsExpanded] = useState(true);
  const [recentsExpanded, setRecentsExpanded] = useState(true);
  const [visibleProjectSelection, setVisibleProjectSelection] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [folderOpen, setFolderOpen] = useState(false);
  const [workspaceFolderOpen, setWorkspaceFolderOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [draftVersion, setDraftVersion] = useState(0);
  const [management, setManagement] = useState<{ project: Project; action: 'rename' | 'delete' } | null>(null);
  const [title, setTitle] = useState('');
  const [managementError, setManagementError] = useState('');
  const mobile = useMediaQuery('(max-width: 767px)');
  const recents = useConversations(api, revision);
  const selectedProject = projects.find(project => project.id === projectId);
  const invalidProject = !conversationId && Boolean(requestedProject) && !projectsLoading && !projectsError && !selectedProject;
  const connection = useMemo(() => ({ api, store, online: true, remote: false }), [api, store]);
  const selection = useMemo<Selection>(() => ({ projectId }), [projectId]);
  const workspaceLocked = ownsConversation && workspaceIsLocked(current);
  const workspaceUnavailable = busy || loadingConversation || Boolean(streamingMessageId)
    || Boolean(conversationId && !ownsConversation)
    || Boolean(!conversationId && requestedProject && !selectedProject);
  const workspacePath = selectedProject?.working_directory || (ownsConversation ? current?.working_directory : undefined);
  const workspaceName = selectedProject?.title || (projectId ? '正在加载工作空间…' : '默认会话目录');
  const refresh = useCallback(() => setRevision(value => value + 1), []);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; store.getState().reset(); };
  }, [store]);
  useEffect(() => { refresh(); }, [current?.id, current?.title, current?.updated_at, runStatus, refresh]);
  useEffect(() => { if (!mobile) setSidebarOpen(false); }, [mobile]);

  const navigate = (id: string | null, project?: number, replace = false) => {
    setParams(previous => {
      const next = new URLSearchParams(previous);
      next.delete('conversation'); next.delete('project');
      if (id) next.set('conversation', id);
      if (project) next.set('project', String(project));
      return next;
    }, { replace });
    setSidebarOpen(false);
    setWorkspaceFolderOpen(false);
  };
  const newChat = (project?: Project) => {
    if (busy) return;
    store.getState().setCurrentConversation(null);
    setDraftVersion(value => value + 1);
    navigate(null, project?.id);
  };
  const selectConversation = (item: Conversation) => {
    if (busy) return;
    navigate(item.id, item.project ?? undefined);
  };
  const changeWorkspace = async (next: Selection) => {
    const latest = store.getState();
    if (conversationId && latest.currentConversation?.id === conversationId && workspaceIsLocked(latest.currentConversation)) {
      throw new Error('发送消息后工作空间已锁定，如需切换请新建对话。');
    }
    if (workspaceUnavailable || latest.isLoading || latest.streamingMessageId) throw new Error('请等待当前操作完成后再切换工作空间');
    setBusy(true);
    const origin = locationKey.current;
    try {
      if (conversationId) {
        const updated = await api.post<ConversationDetail>(`/conversations/${conversationId}/workspace/`, {
          project_id: next.projectId ?? null, working_directory: next.workingDirectory || '',
        });
        if (!mounted.current || locationKey.current !== origin) return;
        const state = store.getState();
        if (state.currentConversation?.id === conversationId) {
          state.setCurrentConversation({ ...state.currentConversation, ...updated, id: String(updated.id) });
          navigate(conversationId, updated.project ?? undefined, true);
        }
      } else if (next.workingDirectory) {
        const project = await api.post<Project>('/projects/', { working_directory: next.workingDirectory });
        if (!mounted.current || locationKey.current !== origin) return;
        setProjects(items => [project, ...items.filter(item => item.id !== project.id)]);
        navigate(null, project.id, true);
      } else navigate(null, next.projectId, true);
      refresh();
    } finally { setBusy(false); }
  };
  const selectWorkspace = async (next: Selection) => {
    try {
      await changeWorkspace(next);
      setWorkspaceFolderOpen(false);
    } catch (error) { message.error(coworkError(error, '切换工作空间失败')); }
  };
  const createProject = async (path: string) => {
    if (busy) return;
    setBusy(true);
    const origin = locationKey.current;
    try {
      const project = await api.post<Project>('/projects/', { working_directory: path });
      if (!mounted.current || locationKey.current !== origin) return;
      setProjects(items => [project, ...items.filter(item => item.id !== project.id)]);
      setFolderOpen(false);
      store.getState().setCurrentConversation(null);
      setDraftVersion(value => value + 1);
      navigate(null, project.id);
      refresh();
    } catch (error) { message.error(coworkError(error, '创建项目失败')); }
    finally { setBusy(false); }
  };
  const saveManagement = async () => {
    if (!management || busy) return;
    setBusy(true); setManagementError('');
    const origin = locationKey.current;
    try {
      if (management.action === 'rename') {
        await api.patch(`/projects/${management.project.id}/`, { title: title.trim() });
      } else {
        await api.delete(`/projects/${management.project.id}/`);
        if (!mounted.current || locationKey.current !== origin) return;
        if (projectId === management.project.id || draftProjectId === management.project.id) {
          store.getState().setCurrentConversation(null);
          setDraftVersion(value => value + 1);
          navigate(null);
        }
      }
      if (!mounted.current) return;
      setManagement(null); refresh();
    } catch (error) { setManagementError(coworkError(error, '项目更新失败')); }
    finally { setBusy(false); }
  };

  const sidebar = <div className="cowork-sidebar-content">
    <div className="cowork-brand"><span>CoWork</span>{mobile && <button className="cowork-icon" aria-label="关闭导航" onClick={() => setSidebarOpen(false)}><X size={20} /></button>}</div>
    <button className="cowork-new-chat" disabled={busy} onClick={() => newChat()}><SquarePen size={18} aria-hidden="true" />New chat</button>
    <div className="cowork-sidebar-scroll">
      <div className="cowork-section-heading">
        <button aria-expanded={projectsExpanded} onClick={() => setProjectsExpanded(value => !value)}>Projects</button>
        <button className="cowork-icon" disabled={busy} onClick={() => setFolderOpen(true)} aria-label="新建 Project"><Plus size={17} /></button>
      </div>
      {projectsExpanded && <div className="cowork-projects">
        {projects.map(project => <ProjectRow key={project.id} project={project} api={api} revision={revision}
          selected={conversationId} active={projectId === project.id} disabled={busy} onNew={newChat} onSelect={selectConversation}
          onSelectionVisible={setVisibleProjectSelection}
          onManage={(project, action) => { setManagement({ project, action }); setTitle(project.title); setManagementError(''); }} />)}
        {projectsLoading && <div className="cowork-list-state"><Spin size="small" /></div>}
        {projectsError && <div role="alert" className="cowork-list-state">{projectsError}<Button type="link" onClick={refresh}>重试</Button></div>}
        {!projectsLoading && !projectsError && !projects.length && <p className="cowork-list-state">绑定文件夹，开始一个项目</p>}
        {projectsMore && <button className="cowork-more" disabled={projectsLoading} onClick={loadMoreProjects}>Show more</button>}
      </div>}
      <div className="cowork-section-heading"><button aria-expanded={recentsExpanded} onClick={() => setRecentsExpanded(value => !value)}>Recents</button></div>
      {recentsExpanded && <ConversationRows list={recents} selected={visibleProjectSelection === conversationId ? null : conversationId} onSelect={selectConversation} />}
    </div>
  </div>;

  return <ChatConnectionContext.Provider value={connection}>
    <div className="cowork-page">
      {!mobile && <aside className="cowork-sidebar" aria-label="CoWork 导航">{sidebar}</aside>}
      <main className="cowork-main">
        <header className="cowork-header">
          {mobile && <button className="cowork-icon" aria-label="打开 CoWork 导航" aria-expanded={sidebarOpen} onClick={() => setSidebarOpen(true)}><Menu size={20} /></button>}
          <span title={selectedProject?.working_directory}>{selectedProject?.title || 'CoWork'}</span>
          <ChatWorkspaceSidebar key={conversationId || 'draft'} conversationId={conversationId} />
        </header>
        <div className="cowork-chat">
          {invalidProject ? <Alert type="error" showIcon message="项目不存在或已移除" action={<Button onClick={() => newChat()}>新建对话</Button>} /> :
            <ChatContainer key={draftVersion} conversationId={conversationId} createOnFirstSend suggestions={[]}
              emptyIcon={<Sparkles size={44} strokeWidth={1.3} aria-hidden="true" />}
              emptyTitle={selectedProject ? `在 ${selectedProject.title} 中，我们要完成什么？` : '今天，我们一起完成什么？'}
              emptyDescription={selectedProject ? '描述任务，AI 将在这个项目的文件夹中协作。' : '直接开始对话，或绑定文件夹创建一个 Project。'}
              inputPlaceholder="描述你的任务…"
              showWorkspaceSelector={false}
              showWorkspaceSidebar={false}
              inputAccessory={<div className="cowork-workspace-strip">
                {workspaceLocked ? <div className="cowork-workspace-control" title={workspacePath || workspaceName}>
                  <Folder size={16} aria-hidden="true" /><span className="cowork-workspace-name">{workspaceName}</span>
                </div> : <Dropdown trigger={['click']} disabled={workspaceUnavailable} menu={{
                  selectedKeys: [projectId ? String(projectId) : 'none'],
                  items: [
                    { key: 'none', label: '使用默认会话目录' },
                    { key: 'system-directory', label: '选择系统目录…' },
                    ...projects.map(project => ({ key: String(project.id), label: project.title })),
                    ...(projectsMore ? [{ key: 'more', label: '加载更多工作空间', disabled: projectsLoading }] : []),
                  ],
                  onClick: ({ key }) => {
                    if (workspaceUnavailable) return;
                    if (key === 'more') loadMoreProjects();
                    else if (key === 'system-directory') setWorkspaceFolderOpen(true);
                    else void selectWorkspace({ projectId: key === 'none' ? undefined : Number(key) });
                  },
                }}>
                  <button type="button" className="cowork-workspace-control" disabled={workspaceUnavailable}
                    aria-label={`切换工作空间：${workspaceName}`} title={workspacePath || '发送第一条消息前可以切换工作空间'}>
                    <Folder size={16} aria-hidden="true" /><span className="cowork-workspace-name">{workspaceName}</span><ChevronDown size={14} aria-hidden="true" />
                  </button>
                </Dropdown>}
                <span className="cowork-workspace-host"><Monitor size={16} aria-hidden="true" />当前后端</span>
              </div>}
              workspaceControl={{ selection, projects, onChange: changeWorkspace, busy: workspaceUnavailable || workspaceFolderOpen }}
              onConversationCreated={id => { navigate(id, store.getState().currentConversation?.project ?? undefined, true); refresh(); }} />}
        </div>
      </main>
      <Drawer open={mobile && sidebarOpen} onClose={() => setSidebarOpen(false)} placement="left" width="min(88vw, 320px)"
        closable={false} rootClassName="cowork-navigation-drawer" aria-label="CoWork 导航">{sidebar}</Drawer>
      <FolderPickerModal apiClient={api} title="选择项目文件夹（当前后端机器）" open={folderOpen} onClose={() => { if (!busy) setFolderOpen(false); }} onSelect={path => void createProject(path)} />
      <FolderPickerModal apiClient={api} title="选择工作空间（当前后端机器）" open={workspaceFolderOpen && !workspaceLocked}
        onClose={() => { if (!busy) setWorkspaceFolderOpen(false); }} onSelect={path => void selectWorkspace({ workingDirectory: path })} />
      <Modal title={management?.action === 'delete' ? '移除 Project' : '重命名 Project'} open={Boolean(management)}
        onCancel={() => { if (!busy) setManagement(null); }} onOk={() => void saveManagement()} confirmLoading={busy}
        okText={management?.action === 'delete' ? '移除项目和对话' : '保存'} cancelText="取消"
        okButtonProps={{ danger: management?.action === 'delete', disabled: management?.action === 'rename' && !title.trim() }}>
        {management?.action === 'delete' ? <p>将移除「{management.project.title}」及其全部对话，对话也会从 Recents 消失。绑定文件夹和磁盘文件会保留。</p> :
          <label className="cowork-rename-label">项目名称<Input autoFocus value={title} maxLength={200} onChange={event => setTitle(event.target.value)} onPressEnter={() => { if (title.trim()) void saveManagement(); }} /></label>}
        {managementError && <Alert type="error" showIcon message={managementError} />}
      </Modal>
    </div>
  </ChatConnectionContext.Provider>;
}
