import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Button, Drawer, Dropdown, Input, Modal, Spin, message } from 'antd';
import { ArrowLeft, ChevronDown, ChevronRight, Folder, Menu, Monitor, MoreHorizontal, Plus, Sparkles, SquarePen, X } from 'lucide-react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import ChatContainer from '@/components/Chat/ChatContainer';
import ChatWorkspaceSidebar from '@/components/Chat/ChatWorkspaceSidebar';
import { ChatConnectionContext } from '@/components/Chat/ChatConnectionContext';
import type { ComposerContext } from '@/components/Chat/MessageInput';
import { createConversationStore, type Conversation, type ConversationDetail } from '@/stores/useConversationStore';
import type { Project } from '@/stores/useProjectStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import useMediaQuery from '@/hooks/useMediaQuery';
import { createUnifiedChatApi, coworkError } from '@/services/cowork';
import FolderPickerModal from '@/pages/Apps/FolderPickerModal';
import './ChatPage.css';

type ChatApi = ReturnType<typeof createUnifiedChatApi>;
type Selection = Pick<ComposerContext, 'projectId' | 'workingDirectory'>;
type Page<T> = { results: T[]; next: string | null };

const workspaceIsLocked = (conversation: ConversationDetail | null) => Boolean(
  conversation?.workspace_locked || (conversation?.scope === 'cowork'
    && conversation.messages.some(item => item.role === 'user')),
);

function useProjects(api: ChatApi, revision: number, selectedId?: number) {
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

function useConversations(api: ChatApi, revision: number, projectId?: number, enabled = true) {
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

type ConversationAction = 'clear' | 'delete';
type ManageConversation = (conversation: Conversation, action: ConversationAction) => void;

function ConversationRows({ list, selected, onSelect, onManage, disabled }: {
  list: ReturnType<typeof useConversations>; selected: string | null;
  onSelect: (conversation: Conversation) => void;
  onManage: ManageConversation; disabled: boolean;
}) {
  return <>
    {list.items.map(item => <div key={item.id} className="cowork-conversation-row">
      <button className="cowork-conversation" disabled={disabled}
        aria-current={selected === item.id ? 'page' : undefined} title={item.title || '新对话'}
        onClick={() => onSelect(item)}>{item.title || '新对话'}</button>
      <Dropdown trigger={['click']} menu={{
        items: [{ key: 'clear', label: '清空对话' }, { key: 'delete', label: '删除对话', danger: true }],
        onClick: ({ key }) => onManage(item, key as ConversationAction),
      }}>
        <button className="cowork-icon cowork-conversation-action" disabled={disabled} aria-label={`管理对话：${item.title || '新对话'}`}>
          <MoreHorizontal size={17} aria-hidden="true" />
        </button>
      </Dropdown>
    </div>)}
    {list.error && <div className="cowork-list-state" role="alert">{list.error}<Button type="link" onClick={list.retry}>重试</Button></div>}
    {list.loading && <div className="cowork-list-state"><Spin size="small" /></div>}
    {!list.loading && !list.error && !list.items.length && <p className="cowork-list-state">暂无对话</p>}
    {list.more && <button className="cowork-more" disabled={list.loading} onClick={list.loadMore}>加载更多</button>}
  </>;
}

function ProjectRow({ project, api, revision, selected, active, disabled, onNew, onSelect, onManage, onManageConversation, onSelectionVisible }: {
  project: Project; api: ChatApi; revision: number; selected: string | null; active: boolean; disabled: boolean;
  onNew: (project: Project) => void; onSelect: (conversation: Conversation) => void;
  onManage: (project: Project, action: 'rename' | 'delete') => void;
  onManageConversation: ManageConversation;
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
        aria-label={`在 ${project.title} 中新建对话`} title="新建对话"><SquarePen size={17} aria-hidden="true" /></button>
      <Dropdown trigger={['click']} menu={{ items: [{ key: 'rename', label: '重命名' }, { key: 'delete', label: '移除项目', danger: true }],
        onClick: ({ key }) => onManage(project, key as 'rename' | 'delete') }}>
        <button className="cowork-icon cowork-project-action" disabled={disabled} aria-label={`管理 ${project.title}`}><MoreHorizontal size={17} /></button>
      </Dropdown>
    </div>
    {expanded && <div className="cowork-project-chats"><ConversationRows list={list} selected={active ? selected : null}
      onSelect={onSelect} onManage={onManageConversation} disabled={disabled} /></div>}
  </div>;
}

export default function ChatPage() {
  const organizationId = useOrganizationStore(state => state.currentOrganizationId);
  const userId = useAuthStore(state => state.user?.id);
  return <ChatWorkspace key={`${organizationId}:${userId}`} />;
}

function ChatWorkspace() {
  const [api] = useState(createUnifiedChatApi);
  const [store] = useState(() => createConversationStore(undefined, api, 'unified-conversations'));
  const current = store(state => state.currentConversation);
  const runStatus = store(state => state.activeRun?.status);
  const loadingConversation = store(state => state.isLoading);
  const streamingMessageId = store(state => state.streamingMessageId);
  const [params, setParams] = useSearchParams();
  const navigatePage = useNavigate();
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
  const [conversationManagement, setConversationManagement] = useState<{ conversation: Conversation; action: ConversationAction } | null>(null);
  const [conversationManagementError, setConversationManagementError] = useState('');
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
  const workspaceName = selectedProject?.title || (projectId ? '项目工作目录'
    : ownsConversation && current?.scope === 'default' && workspacePath ? workspacePath : '默认会话目录');
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
        const legacyProject = current?.scope === 'default' && next.projectId
          ? projects.find(project => project.id === next.projectId) : undefined;
        if (current?.scope === 'default' && next.projectId && !legacyProject) {
          throw new Error('项目不存在，请刷新后重试。');
        }
        const updated = await api.post<ConversationDetail>(`/conversations/${conversationId}/workspace/`, {
          project_id: legacyProject ? null : next.projectId ?? null,
          working_directory: legacyProject?.working_directory || next.workingDirectory || '',
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

  const manageConversation: ManageConversation = (conversation, action) => {
    setConversationManagement({ conversation, action });
    setConversationManagementError('');
  };
  const saveConversationManagement = async () => {
    if (!conversationManagement || busy) return;
    const { conversation, action } = conversationManagement;
    const origin = locationKey.current;
    setBusy(true); setConversationManagementError('');
    try {
      await api.delete(`/conversations/${conversation.id}/${action === 'clear' ? 'clear' : 'delete_conversation'}/`);
      if (!mounted.current) return;
      if (locationKey.current === origin && conversationId === conversation.id) {
        if (action === 'delete') {
          store.getState().setCurrentConversation(null);
          setDraftVersion(value => value + 1);
          navigate(null);
        } else {
          await store.getState().fetchConversationDetail(conversation.id);
        }
      }
      if (!mounted.current) return;
      setConversationManagement(null); refresh();
    } catch (error) {
      if (mounted.current) setConversationManagementError(coworkError(error, '对话更新失败，请重试'));
    } finally { if (mounted.current) setBusy(false); }
  };

  const sidebar = <div className="cowork-sidebar-content">
    <div className="cowork-brand"><span>对话</span>{mobile && <button className="cowork-icon" aria-label="关闭导航" onClick={() => setSidebarOpen(false)}><X size={20} /></button>}</div>
    <button className="cowork-new-chat" disabled={busy} onClick={() => newChat()}><SquarePen size={18} aria-hidden="true" />新建对话</button>
    <div className="cowork-sidebar-scroll">
      <div className="cowork-section-heading">
        <button aria-expanded={projectsExpanded} onClick={() => setProjectsExpanded(value => !value)}>项目</button>
        <button className="cowork-icon" disabled={busy} onClick={() => setFolderOpen(true)} aria-label="新建项目"><Plus size={17} /></button>
      </div>
      {projectsExpanded && <div className="cowork-projects">
        {projects.map(project => <ProjectRow key={project.id} project={project} api={api} revision={revision}
          selected={conversationId} active={projectId === project.id} disabled={busy} onNew={newChat} onSelect={selectConversation}
          onSelectionVisible={setVisibleProjectSelection}
          onManageConversation={manageConversation}
          onManage={(project, action) => { setManagement({ project, action }); setTitle(project.title); setManagementError(''); }} />)}
        {projectsLoading && <div className="cowork-list-state"><Spin size="small" /></div>}
        {projectsError && <div role="alert" className="cowork-list-state">{projectsError}<Button type="link" onClick={refresh}>重试</Button></div>}
        {!projectsLoading && !projectsError && !projects.length && <p className="cowork-list-state">绑定文件夹，开始一个项目</p>}
        {projectsMore && <button className="cowork-more" disabled={projectsLoading} onClick={loadMoreProjects}>加载更多</button>}
      </div>}
      <div className="cowork-section-heading"><button aria-expanded={recentsExpanded} onClick={() => setRecentsExpanded(value => !value)}>最近对话</button></div>
      {recentsExpanded && <ConversationRows list={recents} selected={visibleProjectSelection === conversationId ? null : conversationId}
        onSelect={selectConversation} onManage={manageConversation} disabled={busy} />}
    </div>
  </div>;

  return <ChatConnectionContext.Provider value={connection}>
    <div className="cowork-page">
      {!mobile && <aside className="cowork-sidebar" aria-label="对话导航">{sidebar}</aside>}
      <main className="cowork-main">
        <header className="cowork-header">
          {params.get('embedded') !== '1' && params.get('standalone') !== '1' && <button
            className="cowork-icon" aria-label="返回首页" title="返回首页" onClick={() => navigatePage('/')}>
            <ArrowLeft size={18} aria-hidden="true" />
          </button>}
          {mobile && <button className="cowork-icon" aria-label="打开对话导航" aria-expanded={sidebarOpen} onClick={() => setSidebarOpen(true)}><Menu size={20} aria-hidden="true" /></button>}
          <span title={selectedProject?.working_directory}>{selectedProject?.title || '对话'}</span>
          <ChatWorkspaceSidebar key={conversationId || 'draft'} conversationId={conversationId} />
        </header>
        <div className="cowork-chat">
          {invalidProject ? <Alert type="error" showIcon message="项目不存在或已移除" action={<Button onClick={() => newChat()}>新建对话</Button>} /> :
            <ChatContainer key={draftVersion} conversationId={conversationId} createOnFirstSend suggestions={[]}
              emptyIcon={<Sparkles size={44} strokeWidth={1.3} aria-hidden="true" />}
              emptyTitle={selectedProject ? `在 ${selectedProject.title} 中，我们要完成什么？` : '今天，我们一起完成什么？'}
              emptyDescription={selectedProject ? '描述任务，AI 将在这个项目的文件夹中协作。' : '直接开始对话，或绑定文件夹创建一个项目。'}
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
        closable={false} rootClassName="cowork-navigation-drawer" aria-label="对话导航">{sidebar}</Drawer>
      <Modal title={conversationManagement?.action === 'clear' ? '清空对话' : '删除对话'}
        open={Boolean(conversationManagement)} onCancel={() => { if (!busy) setConversationManagement(null); }}
        onOk={() => void saveConversationManagement()} confirmLoading={busy}
        okText="确认" cancelText="取消" okButtonProps={{ danger: true }}>
        <p>{conversationManagement?.action === 'clear' ? '确定清空此对话的所有消息？' : '确定删除此对话？'}工作目录和磁盘文件会保留。</p>
        {conversationManagementError && <Alert type="error" showIcon message={conversationManagementError} />}
      </Modal>
      <FolderPickerModal apiClient={api} title="选择项目文件夹（当前后端机器）" open={folderOpen} onClose={() => { if (!busy) setFolderOpen(false); }} onSelect={path => void createProject(path)} />
      <FolderPickerModal apiClient={api} title="选择工作空间（当前后端机器）" open={workspaceFolderOpen && !workspaceLocked}
        onClose={() => { if (!busy) setWorkspaceFolderOpen(false); }} onSelect={path => void selectWorkspace({ workingDirectory: path })} />
      <Modal title={management?.action === 'delete' ? '移除项目' : '重命名项目'} open={Boolean(management)}
        onCancel={() => { if (!busy) setManagement(null); }} onOk={() => void saveManagement()} confirmLoading={busy}
        okText={management?.action === 'delete' ? '移除项目和对话' : '保存'} cancelText="取消"
        okButtonProps={{ danger: management?.action === 'delete', disabled: management?.action === 'rename' && !title.trim() }}>
        {management?.action === 'delete' ? <p>将移除「{management.project.title}」及其全部对话，对话也会从最近对话中消失。绑定文件夹和磁盘文件会保留。</p> :
          <label className="cowork-rename-label">项目名称<Input autoFocus value={title} maxLength={200} onChange={event => setTitle(event.target.value)} onPressEnter={() => { if (title.trim()) void saveManagement(); }} /></label>}
        {managementError && <Alert type="error" showIcon message={managementError} />}
      </Modal>
    </div>
  </ChatConnectionContext.Provider>;
}
