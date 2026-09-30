// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { api } from '@/services/api';
import CoWorkPage from '../CoWorkPage';
import type { ChatContainerProps } from '@/components/Chat/ChatContainer';
import { useChatConnection } from '@/components/Chat/ChatConnectionContext';
import type { ConversationDetail } from '@/stores/useConversationStore';

vi.mock('@/stores/useAuthStore', () => ({ useAuthStore: (select: (state: unknown) => unknown) => select({ user: { id: 1 } }) }));
vi.mock('@/stores/useOrganizationStore', () => ({ useOrganizationStore: (select: (state: unknown) => unknown) => select({ currentOrganizationId: 'org' }) }));
vi.mock('@/hooks/useMediaQuery', () => ({ default: () => false }));
vi.mock('../FolderPickerModal', () => ({ default: ({ open, onSelect }: { open: boolean; onSelect: (path: string) => void }) => open ? <button onClick={() => onSelect('/work/project')}>选择测试目录</button> : null }));
let chat: ChatContainerProps;
vi.mock('@/components/Chat/ChatContainer', () => ({ default: function MockChatContainer(props: ChatContainerProps) {
  chat = props;
  const { store } = useChatConnection();
  return <div data-testid="chat" data-project={props.workspaceControl?.selection.projectId ?? ''}>
    {props.emptyTitle}
    <button onClick={async () => {
      const conversation = await store.getState().createConversation('First task', undefined, props.workspaceControl?.selection.projectId);
      store.getState().setCurrentConversation({ ...conversation, messages: [] } as ConversationDetail);
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
async function render(path = '/apps/cowork?entry=home&embedded=1') {
  await act(async () => root.render(<MemoryRouter initialEntries={[path]}><CoWorkPage /><Location /></MemoryRouter>));
  await settle();
}

beforeEach(() => {
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
  expect(api.post).toHaveBeenCalledWith('/conversations/?scope=cowork', expect.objectContaining({ title: 'First task', scope: 'cowork' }), expect.anything());
  const url = host.querySelector('output')!.textContent!;
  expect(url).toContain('conversation=9'); expect(url).toContain('entry=home'); expect(url).toContain('embedded=1');
  expect(host.querySelector('.cowork-conversation')?.textContent).toBe('First task');
});

it('creates a folder project without creating a conversation, then sends in that project', async () => {
  await render(); await click('新建 Project'); await click('选择测试目录');
  expect(api.post).toHaveBeenCalledTimes(1);
  expect(api.post).toHaveBeenCalledWith('/projects/?scope=cowork', { working_directory: '/work/project', scope: 'cowork' }, undefined);
  expect(host.querySelector('[data-testid="chat"]')?.getAttribute('data-project')).toBe('4');
  await click('发送第一条消息');
  expect(api.post).toHaveBeenLastCalledWith('/conversations/?scope=cowork', expect.objectContaining({ scope: 'cowork', project_id: 4 }), expect.anything());
  expect(host.querySelector('.cowork-project-chats')?.textContent).toContain('First task');
  expect(host.querySelectorAll('.cowork-conversation')).toHaveLength(2);
});

it('keeps the selected project after a failed folder binding', async () => {
  projects = [project];
  await render('/apps/cowork?project=4');
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
  await render('/apps/cowork?project=4');
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
  await render('/apps/cowork?project=404');
  expect(host.textContent).toContain('项目不存在或已移除');
  expect(host.querySelector('[data-testid="chat"]')).toBeNull();
  expect(api.post).not.toHaveBeenCalled();
});
