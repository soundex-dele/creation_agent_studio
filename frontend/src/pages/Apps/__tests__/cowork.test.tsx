// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { api } from '@/services/api';
import ChatPage from '@/pages/Chat/ChatPage';
import type { ChatContainerProps } from '@/components/Chat/ChatContainer';
import { useChatConnection } from '@/components/Chat/ChatConnectionContext';
import type { ConversationDetail } from '@/stores/useConversationStore';

let userId = 1;
let organizationId = 'org';
let mobile = false;
vi.mock('@/stores/useAuthStore', () => ({ useAuthStore: (select: (state: unknown) => unknown) => select({ user: { id: userId } }) }));
vi.mock('@/stores/useOrganizationStore', () => ({ useOrganizationStore: (select: (state: unknown) => unknown) => select({ currentOrganizationId: organizationId }) }));
vi.mock('@/hooks/useMediaQuery', () => ({ default: () => mobile }));
vi.mock('@/pages/Apps/FolderPickerModal', () => ({ default: ({ open, onSelect }: { open: boolean; onSelect: (path: string) => void }) => open ? <button onClick={() => onSelect('/work/project')}>选择测试目录</button> : null }));
let chat: ChatContainerProps;
let chatStore: ReturnType<typeof useChatConnection>['store'];
vi.mock('@/components/Chat/ChatContainer', () => ({ default: function MockChatContainer(props: ChatContainerProps) {
  chat = props;
  const { store } = useChatConnection();
  chatStore = store;
  return <div data-testid="chat" data-project={props.workspaceControl?.selection.projectId ?? ''}>
    {props.emptyTitle}
    {props.inputAccessory}
    <input aria-label="任务草稿" />
    <button onClick={async () => {
      const conversation = await store.getState().createConversation('First task', undefined, props.workspaceControl?.selection.projectId);
      store.getState().setCurrentConversation({ ...conversation, messages: [{ id: '1', role: 'user', content: 'First task', created_at: '' }] } as ConversationDetail);
      props.onConversationCreated?.(conversation.id);
    }}>发送第一条消息</button>
  </div>;
} }));

let host: HTMLDivElement;
let root: Root;
let projects: Array<Record<string, unknown>>;
let conversations: Array<Record<string, unknown>>;
const project = { id: 4, title: 'project', working_directory: '/work/project', scope: 'cowork', directory_source: 'explicit' };
function Location() { return <output data-testid="location">{useLocation().search}</output>; }
const settle = async () => act(async () => { await new Promise(resolve => setTimeout(resolve, 10)); });
const click = async (label: string) => {
  const target = [...document.querySelectorAll<HTMLButtonElement>('button')].find(item => item.getAttribute('aria-label') === label || item.textContent?.replace(/\s/g, '') === label.replace(/\s/g, ''));
  expect(target, label).toBeTruthy();
  await act(async () => target!.click()); await settle();
};
const chooseWorkspace = async (label: string) => {
  const target = [...document.querySelectorAll<HTMLElement>('[role="menuitem"]')].find(item => item.textContent === label);
  expect(target, label).toBeTruthy();
  await act(async () => target!.click()); await settle();
};
async function render(path = '/chat?entry=home&embedded=1') {
  await act(async () => root.render(<MemoryRouter initialEntries={[path]}><ChatPage /><Location /></MemoryRouter>));
  await settle();
}

beforeEach(() => {
  userId = 1; organizationId = 'org'; mobile = false;
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  window.matchMedia = vi.fn().mockImplementation(query => ({ matches: false, media: query, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() }));
  const getComputedStyle = window.getComputedStyle.bind(window);
  vi.spyOn(window, 'getComputedStyle').mockImplementation(element => getComputedStyle(element));
  projects = []; conversations = [];
  vi.spyOn(api, 'get').mockImplementation(async (url, params) => {
    if (url.startsWith('/projects/')) return projects as never;
    const rows = params?.project_id ? conversations.filter(item => item.project === params.project_id) : conversations;
    return { results: rows, next: null } as never;
  });
  vi.spyOn(api, 'post').mockImplementation(async (url, data) => {
    if (url.startsWith('/projects/')) { projects = [project]; return project as never; }
    const created = { ...(data as Record<string, unknown>), id: 9, project: (data as Record<string, unknown>).project_id ?? null, title: 'First task' };
    conversations = [created]; return created as never;
  });
  vi.spyOn(api, 'patch').mockImplementation(async (_url, data) => { projects = [{ ...project, ...(data as Record<string, unknown>) }]; return projects[0] as never; });
  vi.spyOn(api, 'delete').mockImplementation(async () => { projects = []; conversations = []; return undefined as never; });
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it('keeps a draft local and preserves shell presentation when first sent', async () => {
  await render();
  expect(api.post).not.toHaveBeenCalled();
  expect(host.textContent).toContain('绑定文件夹');
  await click('发送第一条消息');
  expect(api.post).toHaveBeenCalledWith('/conversations/?scope=unified', expect.objectContaining({ title: 'First task', scope: 'cowork' }), expect.anything());
  const url = host.querySelector('output')!.textContent!;
  expect(url).toContain('conversation=9'); expect(url).toContain('entry=home'); expect(url).toContain('embedded=1');
  expect(host.querySelector('.cowork-conversation')?.textContent).toBe('First task');
});

it('creates a folder project without creating a conversation, then sends in that project', async () => {
  await render(); await click('新建项目'); await click('选择测试目录');
  expect(api.post).toHaveBeenCalledTimes(1);
  expect(api.post).toHaveBeenCalledWith('/projects/?scope=cowork', { working_directory: '/work/project', scope: 'cowork' }, undefined);
  expect(host.querySelector('[data-testid="chat"]')?.getAttribute('data-project')).toBe('4');
  await click('发送第一条消息');
  expect(api.post).toHaveBeenLastCalledWith('/conversations/?scope=unified', expect.objectContaining({ scope: 'cowork', project_id: 4 }), expect.anything());
  expect(host.querySelector('.cowork-project-chats')?.textContent).toContain('First task');
  expect(host.querySelectorAll('.cowork-conversation')).toHaveLength(2);
});

it('keeps the selected project after a failed folder binding', async () => {
  projects = [project];
  await render('/chat?project=4');
  vi.mocked(api.post).mockRejectedValueOnce({ response: { data: { working_directory: ['目录不存在'] } } });
  await act(async () => { await expect(chat.workspaceControl!.onChange({ workingDirectory: '/missing' })).rejects.toBeTruthy(); });
  expect(host.querySelector('[data-testid="chat"]')?.getAttribute('data-project')).toBe('4');
  expect(host.querySelector('output')?.textContent).toContain('project=4');
});

it('shows every recent conversation in server order, including project conversations', async () => {
  projects = [project];
  conversations = [{ id: 2, title: 'Newest', project: null }, { id: 1, title: 'Project history', project: 4 }];
  await render();
  expect([...host.querySelectorAll('.cowork-conversation')].map(item => item.textContent)).toEqual(['Newest', 'Project history']);
  await click('展开 project');
  expect(host.querySelector('.cowork-project-chats')?.textContent).toContain('Project history');
  await click('Newest');
  expect(host.querySelector('output')?.textContent).toContain('conversation=2');
});

it('renames a project and removes its conversations without offering file deletion', async () => {
  projects = [project]; conversations = [{ id: 9, title: 'Task', project: 4 }];
  await render('/chat?project=4');
  await click('管理 project');
  const rename = [...document.querySelectorAll<HTMLElement>('[role="menuitem"]')].find(item => item.textContent?.includes('重命名'))!;
  await act(async () => rename.click()); await settle();
  const input = document.querySelector<HTMLInputElement>('.cowork-rename-label input')!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, 'Renamed');
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await click('保存');
  expect(api.patch).toHaveBeenCalledWith('/projects/4/?scope=cowork', { title: 'Renamed' }, undefined);
  await click('管理 Renamed');
  const remove = [...document.querySelectorAll<HTMLElement>('[role="menuitem"]')].find(item => item.textContent?.includes('移除项目'))!;
  await act(async () => remove.click()); await settle();
  expect(document.body.textContent).toContain('绑定文件夹和磁盘文件会保留');
  await click('移除项目和对话');
  expect(api.delete).toHaveBeenCalledWith('/projects/4/?scope=cowork', undefined);
  expect(host.querySelectorAll('.cowork-conversation')).toHaveLength(0);
  expect(host.querySelector('output')?.textContent).not.toContain('project=4');
});

it('blocks an expired project link instead of sending into a default directory', async () => {
  await render('/chat?project=404');
  expect(host.textContent).toContain('项目不存在或已移除');
  expect(host.querySelector('[data-testid="chat"]')).toBeNull();
  expect(api.post).not.toHaveBeenCalled();
});

it('merges the workspace menu above the composer and preserves the draft when switching', async () => {
  projects = [project];
  await render();
  expect(chat.showWorkspaceSelector).toBe(false);
  const draft = host.querySelector<HTMLInputElement>('[aria-label="任务草稿"]')!;
  draft.value = 'Keep my draft';
  await click('切换工作空间：默认会话目录');
  await chooseWorkspace('project');
  expect(host.querySelector('.cowork-workspace-name')?.textContent).toBe('project');
  expect(chat.workspaceControl?.selection.projectId).toBe(4);
  expect(host.querySelector('[aria-label="任务草稿"]')).toBe(draft);
  expect(draft.value).toBe('Keep my draft');
  await click('切换工作空间：project');
  await chooseWorkspace('使用默认会话目录');
  expect(chat.workspaceControl?.selection.projectId).toBeUndefined();
  expect(api.post).not.toHaveBeenCalled();
});

it('binds a folder from the upper menu without resetting the draft', async () => {
  await render();
  const draft = host.querySelector<HTMLInputElement>('[aria-label="任务草稿"]')!;
  draft.value = 'Keep folder task';
  await click('切换工作空间：默认会话目录');
  await chooseWorkspace('选择系统目录…');
  expect(chat.workspaceControl?.busy).toBe(true);
  await click('选择测试目录');
  expect(chat.workspaceControl?.selection.projectId).toBe(4);
  expect(host.querySelector('[aria-label="任务草稿"]')).toBe(draft);
  expect(draft.value).toBe('Keep folder task');
  expect(api.post).toHaveBeenCalledTimes(1);
});

it('locks the workspace after the first message and enables it again for a new chat', async () => {
  projects = [project];
  await render('/chat?project=4');
  await click('发送第一条消息');
  expect(host.querySelector('.cowork-workspace-strip button')).toBeNull();
  expect(host.querySelector('.cowork-workspace-name')?.textContent).toBe('project');
  expect(host.querySelector('.cowork-workspace-strip')?.textContent).not.toContain('已锁定');
  const requests = vi.mocked(api.post).mock.calls.length;
  await act(async () => { await expect(chat.workspaceControl!.onChange({})).rejects.toThrow('已锁定'); });
  expect(api.post).toHaveBeenCalledTimes(requests);
  await click('新建对话');
  expect(host.querySelector<HTMLButtonElement>('.cowork-workspace-strip button')?.disabled).toBe(false);
  expect(host.querySelector('.cowork-workspace-status')).toBeNull();
});

it('keeps a reopened conversation read-only using the server lock', async () => {
  await render('/chat?conversation=9');
  expect(host.querySelector<HTMLButtonElement>('.cowork-workspace-strip button')?.disabled).toBe(true);
  await act(async () => chatStore.getState().setCurrentConversation({
    id: '9', title: 'Existing', workspace_locked: true, messages: [],
    working_directory: '/work/existing', created_at: '', updated_at: '',
  }));
  expect(host.querySelector('.cowork-workspace-strip button')).toBeNull();
  expect(host.querySelector('.cowork-workspace-control')?.getAttribute('title')).toContain('/work/existing');
});

it('blocks switching while the first conversation is being created and recovers after failure', async () => {
  await render();
  await act(async () => chatStore.setState({ isLoading: true }));
  expect(host.querySelector<HTMLButtonElement>('.cowork-workspace-strip button')?.disabled).toBe(true);
  await act(async () => { await expect(chat.workspaceControl!.onChange({ projectId: 4 })).rejects.toThrow('请等待'); });
  await act(async () => chatStore.setState({ isLoading: false }));
  expect(host.querySelector<HTMLButtonElement>('.cowork-workspace-strip button')?.disabled).toBe(false);
});

it('highlights a project conversation once and falls back to Recents when its project is collapsed', async () => {
  projects = [project];
  await render('/chat?project=4');
  await click('发送第一条消息');
  expect(host.querySelectorAll('.cowork-conversation[aria-current="page"]')).toHaveLength(1);
  expect(host.querySelector('.cowork-project-chats .cowork-conversation[aria-current="page"]')).not.toBeNull();
  expect(host.querySelector('.cowork-project-row.is-active')).toBeNull();
  await click('收起 project');
  expect(host.querySelectorAll('.cowork-conversation[aria-current="page"]')).toHaveLength(1);
  expect(host.querySelector('.cowork-project-chats')).toBeNull();
  await click('展开 project');
  expect(host.querySelectorAll('.cowork-conversation[aria-current="page"]')).toHaveLength(1);
  expect(host.querySelector('.cowork-project-chats .cowork-conversation[aria-current="page"]')).not.toBeNull();
});

it('starts a fresh draft in the project selected by its 新建对话 button', async () => {
  projects = [project];
  await render();
  await click('发送第一条消息');
  const previousDraft = host.querySelector('[aria-label="任务草稿"]');
  await click('在 project 中新建对话');
  expect(chat.conversationId).toBeNull();
  expect(chat.workspaceControl?.selection.projectId).toBe(4);
  expect(host.querySelector('[aria-label="任务草稿"]')).not.toBe(previousDraft);
  expect(host.querySelector('output')?.textContent).toContain('project=4');
  expect(host.querySelector<HTMLButtonElement>('.cowork-workspace-strip button')?.disabled).toBe(false);
  await click('发送第一条消息');
  expect(api.post).toHaveBeenLastCalledWith('/conversations/?scope=unified', expect.objectContaining({ project_id: 4 }), expect.anything());
});

it('opens the workspace sidebar from the top-right header without a duplicate chat toolbar', async () => {
  await render();
  expect(chat.showWorkspaceSidebar).toBe(false);
  expect(host.querySelector('.cowork-header [aria-label="新建对话"]')).toBeNull();
  expect(host.querySelectorAll('[aria-label="打开右侧栏"]')).toHaveLength(1);
  expect(host.querySelector('.cowork-header [aria-label="打开右侧栏"]')).not.toBeNull();
  await click('打开右侧栏');
  expect(document.body.textContent).toContain('会话工作空间');
  expect(host.querySelector('[aria-label="打开右侧栏"]')?.getAttribute('aria-expanded')).toBe('true');
});

it('continues showing legacy directory controls after messages and converts a project choice to its path', async () => {
  projects = [project];
  await render('/chat?conversation=old');
  const old = { id: 'old', title: 'Legacy', scope: 'default' as const, workspace_locked: false,
    messages: [{ id: 'm1', role: 'user' as const, content: 'Sent', created_at: '' }],
    working_directory: '/work/legacy', created_at: '', updated_at: '' };
  await act(async () => chatStore.getState().setCurrentConversation(old));
  expect(host.querySelector<HTMLButtonElement>('.cowork-workspace-strip button')?.disabled).toBe(false);
  expect(host.querySelector('.cowork-workspace-name')?.textContent).toBe('/work/legacy');
  vi.mocked(api.post).mockResolvedValueOnce({ ...old, working_directory: '/work/project' });
  await act(async () => chat.workspaceControl!.onChange({ projectId: 4 }));
  expect(api.post).toHaveBeenLastCalledWith('/conversations/old/workspace/?scope=unified', {
    project_id: null, working_directory: '/work/project',
  }, undefined);
  expect(chatStore.getState().currentConversation?.scope).toBe('default');
});

it('clears the selected conversation and refreshes both lists without leaving its URL', async () => {
  projects = [project]; conversations = [{ id: 9, title: 'Task', project: 4, scope: 'cowork' }];
  await render('/chat?conversation=9');
  const old = { id: '9', title: 'Task', project: 4, scope: 'cowork' as const, workspace_locked: true,
    messages: [{ id: 'm1', role: 'user' as const, content: 'Sent', created_at: '' }], created_at: '', updated_at: '' };
  await act(async () => chatStore.getState().setCurrentConversation(old));
  await settle();
  const originalGet = vi.mocked(api.get).getMockImplementation()!;
  vi.mocked(api.get).mockImplementation(async (url, params, config) => url === '/conversations/9/?scope=unified'
    ? { ...old, messages: [] } as never : originalGet(url, params, config));
  vi.mocked(api.delete).mockResolvedValueOnce(undefined);
  await click('管理对话：Task'); await chooseWorkspace('清空对话');
  expect(api.delete).not.toHaveBeenCalled();
  vi.mocked(api.get).mockClear();
  await click('确认');
  expect(api.delete).toHaveBeenCalledWith('/conversations/9/clear/?scope=unified', undefined);
  expect(chatStore.getState().currentConversation?.messages).toEqual([]);
  expect(host.querySelector('output')?.textContent).toContain('conversation=9');
  expect(api.get).toHaveBeenCalledWith('/conversations/?scope=unified', { page: 1, project_id: 4 }, expect.anything());
  expect(api.get).toHaveBeenCalledWith('/conversations/?scope=unified', { page: 1 }, expect.anything());
});

it('retains failed deletion for retry and returns to a draft after deleting the current conversation', async () => {
  conversations = [{ id: 9, title: 'Delete me', project: null, scope: 'default' }];
  await render('/chat?conversation=9&entry=home');
  await click('管理对话：Delete me'); await chooseWorkspace('删除对话');
  vi.mocked(api.delete).mockRejectedValueOnce({ response: { data: { detail: '当前对话仍在执行' } } });
  await click('确认');
  expect(document.body.textContent).toContain('当前对话仍在执行');
  expect(host.querySelector('output')?.textContent).toContain('conversation=9');
  await click('确认');
  expect(api.delete).toHaveBeenLastCalledWith('/conversations/9/delete_conversation/?scope=unified', undefined);
  expect(host.querySelector('output')?.textContent).toBe('?entry=home');
  expect(chatStore.getState().currentConversation).toBeNull();
  expect(host.querySelectorAll('.cowork-conversation')).toHaveLength(0);
});

it('paginates mixed history in server order', async () => {
  vi.mocked(api.get).mockImplementation(async (url, params) => {
    if (url.startsWith('/projects/')) return [] as never;
    return { results: params?.page === 2 ? [{ id: 1, title: 'Older', scope: 'default' }]
      : [{ id: 2, title: 'Newer', scope: 'cowork' }], next: params?.page === 2 ? null : '/next' } as never;
  });
  await render();
  await click('加载更多');
  expect([...host.querySelectorAll('.cowork-conversation')].map(item => item.textContent)).toEqual(['Newer', 'Older']);
});

it('allows retrying a failed history load', async () => {
  let failed = true;
  vi.mocked(api.get).mockImplementation(async url => {
    if (url.startsWith('/projects/')) return [] as never;
    if (failed) throw { response: { data: { detail: '暂时无法加载历史' } } };
    return { results: [{ id: 1, title: 'Recovered', scope: 'default' }], next: null } as never;
  });
  await render();
  expect(host.textContent).toContain('暂时无法加载历史');
  failed = false;
  await click('重试');
  expect(host.querySelector('.cowork-conversation')?.textContent).toBe('Recovered');
});

it('uses one mobile drawer for project navigation and closes it on selection', async () => {
  mobile = true;
  conversations = [{ id: 1, title: 'Mobile history', scope: 'default' }];
  await render('/chat?entry=apps');
  expect(host.querySelector('aside')).toBeNull();
  await click('打开对话导航');
  expect(document.querySelector('.cowork-navigation-drawer')).not.toBeNull();
  await click('Mobile history');
  expect(host.querySelector('output')?.textContent).toContain('conversation=1');
  expect(host.querySelector('[aria-label="打开对话导航"]')?.getAttribute('aria-expanded')).toBe('false');
});

it.each(['user', 'organization'])('disposes the old connection when the %s changes', async change => {
  await render();
  const previous = chatStore;
  await act(async () => previous.getState().setCurrentConversation({ id: 'private', title: 'Private', messages: [], created_at: '', updated_at: '' }));
  if (change === 'user') userId = 2;
  else organizationId = 'other';
  await render();
  expect(chatStore).not.toBe(previous);
  expect(previous.getState().currentConversation).toBeNull();
  expect(chatStore.getState().currentConversation).toBeNull();
});

it.each(['entry=home', 'entry=apps', 'standalone=1', 'embedded=1'])('keeps its own navigation under %s', async query => {
  await render(`/chat?${query}`);
  expect(host.querySelectorAll('aside[aria-label="对话导航"]')).toHaveLength(1);
  expect(Boolean(host.querySelector('[aria-label="返回首页"]'))).toBe(!/standalone|embedded/.test(query));
});
