// @vitest-environment jsdom
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { message } from 'antd';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import AgentLifecyclePanel from '../AgentLifecyclePanel';

vi.setConfig({ testTimeout: 15000 });

const api = vi.hoisted(() => ({ get: vi.fn(), delete: vi.fn() }));
vi.mock('@/services/api', () => ({ api }));
vi.mock('@/components/Permissions/ResourcePermissionModal', () => ({ default: () => null }));
vi.mock('@/components/Permissions/BulkResourcePermissionModal', () => ({ default: () => null }));
vi.mock('@/components/Agents/AgentEditorModal', () => ({
  default: ({ open, agentId, onSaved }: {
    open: boolean; agentId: number | null; onSaved: () => Promise<void>;
  }) => open ? React.createElement('button', {
    'data-testid': 'editor', onClick: onSaved,
  }, `保存 ${agentId}`) : null,
}));

const agent = {
  id: 7, name: '脚本助手', slug: 'script-assistant', description: '编写脚本',
  is_active: true, visibility: 'private', can_edit: true,
  can_delete: true, can_manage_permissions: true, can_toggle: false,
};
let rows: typeof agent[];
let root: Root;
let container: HTMLDivElement;

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  vi.stubGlobal('matchMedia', vi.fn(() => ({
    matches: false, addListener: vi.fn(), removeListener: vi.fn(),
    addEventListener: vi.fn(), removeEventListener: vi.fn(),
  })));
  const getComputedStyle = window.getComputedStyle.bind(window);
  vi.spyOn(window, 'getComputedStyle').mockImplementation((element) => getComputedStyle(element));
  const messageClosed = Promise.resolve(true);
  const closeMessage = Object.assign(() => {}, { then: messageClosed.then.bind(messageClosed) });
  vi.spyOn(message, 'success').mockReturnValue(closeMessage);
  vi.spyOn(message, 'error').mockReturnValue(closeMessage);
  rows = [{ ...agent }];
  api.get.mockReset().mockImplementation(async (url: string) => (
    url === '/agents/' ? rows : url.endsWith('/deployment/') ? null : []
  ));
  api.delete.mockReset().mockImplementation(async () => { rows = []; });
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

const render = async () => {
  await act(async () => root.render(React.createElement(AgentLifecyclePanel)));
};
const click = async (selector: string) => {
  const button = document.querySelector<HTMLButtonElement>(selector);
  expect(button).not.toBeNull();
  await act(async () => button!.click());
};

it('opens the selected agent editor and reloads management data after saving', async () => {
  await render();
  await click('[aria-label="编辑 脚本助手"]');
  expect(container.querySelector('[data-testid="editor"]')?.textContent).toBe('保存 7');
  api.get.mockClear();
  await click('[data-testid="editor"]');
  expect(api.get).toHaveBeenCalledWith('/agents/', { manageable: 1, mine: 1 });
  expect(api.get).toHaveBeenCalledWith('/agents/7/versions/');
});

it('requires confirmation before deleting and refreshes the list afterwards', async () => {
  await render();
  await click('[aria-label="删除 脚本助手"]');
  expect(api.delete).not.toHaveBeenCalled();
  await click('.ant-popconfirm-buttons .ant-btn-primary');
  expect(api.delete).toHaveBeenCalledExactlyOnceWith('/agents/7/');
  expect(container.querySelector('[aria-label="删除 脚本助手"]')).toBeNull();
  expect(container.textContent).toContain('当前组织暂无智能体');
});

it('keeps the agent and displays the server reason when deletion is rejected', async () => {
  api.delete.mockRejectedValue({ response: { data: { detail: '智能体仍被应用引用' } } });
  await render();
  await click('[aria-label="删除 脚本助手"]');
  await click('.ant-popconfirm-buttons .ant-btn-primary');
  expect(message.error).toHaveBeenCalledWith('智能体仍被应用引用');
  expect(container.querySelector('[aria-label="删除 脚本助手"]')).not.toBeNull();
});

it('hides unauthorized actions and disables editing for inactive agents', async () => {
  rows = [
    { ...agent, can_edit: false, can_delete: false },
    { ...agent, id: 8, name: '停用助手', is_active: false },
  ];
  await render();
  expect(container.querySelector('[aria-label="编辑 脚本助手"]')).toBeNull();
  expect(container.querySelector('[aria-label="删除 脚本助手"]')).toBeNull();
  expect(container.querySelector<HTMLButtonElement>('[aria-label="编辑 停用助手"]')?.disabled).toBe(true);
  expect(container.querySelector<HTMLButtonElement>('[aria-label="删除 停用助手"]')?.disabled).toBe(false);
});
