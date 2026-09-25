// @vitest-environment jsdom
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import MessageInput from '../MessageInput';
import { usePreferencesStore } from '@/stores/usePreferencesStore';

const state = vi.hoisted(() => ({
  api: { get: vi.fn() }, organizationId: 'one',
  remote: false, online: true,
  load: vi.fn(), send: vi.fn(),
}));
vi.mock('../ChatConnectionContext', () => ({
  useChatConnection: () => ({ api: state.api, remote: state.remote, online: state.online }),
}));
vi.mock('@/stores/useOrganizationStore', () => ({
  useOrganizationStore: (select: (value: unknown) => unknown) => select({ currentOrganizationId: state.organizationId }),
}));
vi.mock('@/stores/useAgentStore', () => ({ useAgentStore: () => ({ agents: [], loadAgents: state.load }) }));
vi.mock('@/stores/useProjectStore', () => ({ useProjectStore: () => ({ projects: [], loadProjects: state.load }) }));
vi.mock('@/pages/Apps/FolderPickerModal', () => ({ default: () => null }));

let root: Root;
let container: HTMLDivElement;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  state.api = { get: vi.fn() };
  state.organizationId = 'one';
  state.remote = false;
  state.online = true;
  state.send.mockReset();
  usePreferencesStore.getState().reset();
  usePreferencesStore.getState().setDefaultPermissionMode('allow_all');
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  usePreferencesStore.getState().reset();
});
const render = async () => {
  await act(async () => root.render(React.createElement(MessageInput, { value: 'hello', onSendMessage: state.send })));
};
const send = async () => {
  await act(async () => container.querySelector<HTMLButtonElement>('[aria-label="发送消息"]')!.click());
  return state.send.mock.lastCall?.[1].permissionMode;
};

it('overrides the full-control preference when organization approval is required', async () => {
  state.api.get.mockResolvedValue({ skills: [], require_tool_approval: true });
  await render();
  expect(container.textContent).toContain('默认权限');
  expect(await send()).toBe('default');
});

it('keeps full control when the organization allows it', async () => {
  state.api.get.mockResolvedValue({ skills: [], require_tool_approval: false });
  await render();
  expect(container.textContent).toContain('完全控制');
  expect(await send()).toBe('allow_all');
});

it('retains the saved permission and waits instead of silently sending with default permissions', async () => {
  state.api.get.mockReturnValue(new Promise(() => {}));
  await render();
  expect(container.textContent).toContain('完全控制（待确认）');
  await send();
  expect(state.send).not.toHaveBeenCalled();
  state.organizationId = 'two';
  state.api.get.mockRejectedValue(new Error('offline'));
  await render();
  expect(container.textContent).toContain('权限校验失败，点击重试');
  await send();
  expect(state.send).not.toHaveBeenCalled();
  expect(usePreferencesStore.getState().defaultPermissionMode).toBe('allow_all');
});

it.each([undefined, null])('requires an explicit policy before restoring full control (%s)', async required => {
  state.api.get.mockResolvedValue({ skills: [], require_tool_approval: required });
  await render();
  expect(container.textContent).toContain('权限校验失败，点击重试');
  await send();
  expect(state.send).not.toHaveBeenCalled();
  expect(usePreferencesStore.getState().defaultPermissionMode).toBe('allow_all');
});

it('does not reuse policy from another organization or computer', async () => {
  state.api.get.mockResolvedValue({ skills: [], require_tool_approval: false });
  await render();
  expect(await send()).toBe('allow_all');
  state.organizationId = 'two';
  state.api.get.mockReturnValue(new Promise(() => {}));
  await render();
  state.send.mockClear();
  await send();
  expect(state.send).not.toHaveBeenCalled();
  state.api = { get: vi.fn().mockResolvedValue({ skills: [], require_tool_approval: true }) };
  await render();
  expect(await send()).toBe('default');
});

it('applies settings changes to every mounted conversation in both directions', async () => {
  state.api.get.mockResolvedValue({ skills: [], require_tool_approval: false });
  await act(async () => root.render(React.createElement(React.Fragment, null,
    ...['first', 'second'].map(key => React.createElement(MessageInput, {
      key, value: key, onSendMessage: state.send,
    })),
  )));
  for (const mode of ['default', 'allow_all'] as const) {
    await act(async () => usePreferencesStore.getState().setDefaultPermissionMode(mode));
    const controls = container.querySelectorAll('[aria-label="对话权限（所有会话）"]');
    expect(Array.from(controls, control => control.textContent)).toEqual(
      Array(2).fill(mode === 'default' ? '默认权限' : '完全控制'),
    );
    state.send.mockClear();
    for (const button of container.querySelectorAll<HTMLButtonElement>('[aria-label="发送消息"]')) {
      await act(async () => button.click());
    }
    expect(state.send.mock.calls.map(call => call[1].permissionMode)).toEqual([mode, mode]);
  }
});

it('persists a composer selection and uses it in another conversation', async () => {
  state.api.get.mockResolvedValue({ skills: [], require_tool_approval: false });
  await render();
  await act(async () => container.querySelector<HTMLButtonElement>('[aria-label="对话权限（所有会话）"]')!.click());
  const option = Array.from(document.querySelectorAll<HTMLElement>('[role="menuitem"]'))
    .find(item => item.textContent?.includes('默认权限'));
  expect(option).toBeDefined();
  await act(async () => option!.click());
  expect(usePreferencesStore.getState().defaultPermissionMode).toBe('default');
  expect(JSON.parse(localStorage.getItem('agent-studio-preferences')!).state.defaultPermissionMode).toBe('default');
  await act(async () => root.render(React.createElement(MessageInput, {
    key: 'another-conversation', value: 'hello', onSendMessage: state.send,
  })));
  expect(await send()).toBe('default');
});

it('restores full control after leaving and reopening a computer, including storage rehydration', async () => {
  state.remote = true;
  usePreferencesStore.getState().setDefaultPermissionMode('default');
  state.api.get.mockImplementation(async path => path === '/conversations/composer-options/'
    ? { skills: [], require_tool_approval: false } : []);
  await render();
  await act(async () => container.querySelector<HTMLButtonElement>('[aria-label="对话权限（所有会话）"]')!.click());
  const option = Array.from(document.querySelectorAll<HTMLElement>('[role="menuitem"]'))
    .find(item => item.textContent?.includes('完全控制'));
  await act(async () => option!.click());
  expect(await send()).toBe('allow_all');
  const saved = localStorage.getItem('agent-studio-preferences')!;
  await act(async () => root.render(null));
  usePreferencesStore.setState({ defaultPermissionMode: 'default' });
  localStorage.setItem('agent-studio-preferences', saved);
  await usePreferencesStore.persist.rehydrate();
  let ready!: (value: unknown) => void;
  state.api.get.mockImplementation(path => path === '/conversations/composer-options/'
    ? new Promise(resolve => { ready = resolve; }) : Promise.resolve([]));
  state.send.mockClear();
  await render();
  expect(container.textContent).toContain('完全控制（待确认）');
  await send();
  expect(state.send).not.toHaveBeenCalled();
  await act(async () => ready({ skills: [], require_tool_approval: false }));
  expect(await send()).toBe('allow_all');
});

it('retries failed policy checks and checks again after the computer reconnects', async () => {
  state.remote = true;
  state.api.get.mockImplementation(path => path === '/conversations/composer-options/'
    ? Promise.reject(new Error('offline')) : Promise.resolve([]));
  await render();
  expect(container.textContent).toContain('完全控制（待确认）');
  state.api.get.mockImplementation(async path => path === '/conversations/composer-options/'
    ? { skills: [], require_tool_approval: false } : []);
  await act(async () => container.querySelector<HTMLButtonElement>('[role="status"] button')!.click());
  expect(await send()).toBe('allow_all');
  state.online = false;
  await render();
  state.send.mockClear();
  await send();
  expect(state.send).not.toHaveBeenCalled();
  state.api.get.mockClear();
  state.online = true;
  await render();
  expect(state.api.get).toHaveBeenCalledWith('/conversations/composer-options/');
  expect(await send()).toBe('allow_all');
});
