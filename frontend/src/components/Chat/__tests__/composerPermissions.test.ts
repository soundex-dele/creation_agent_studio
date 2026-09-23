// @vitest-environment jsdom
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import MessageInput from '../MessageInput';

const state = vi.hoisted(() => ({
  api: { get: vi.fn() }, organizationId: 'one',
  load: vi.fn(), send: vi.fn(),
}));
vi.mock('../ChatConnectionContext', () => ({
  useChatConnection: () => ({ api: state.api, remote: false }),
}));
vi.mock('@/stores/usePreferencesStore', () => ({
  usePreferencesStore: (select: (value: unknown) => unknown) => select({
    defaultPermissionMode: 'allow_all', sendShortcut: 'enter',
  }),
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
  state.send.mockReset();
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
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

it('uses default permissions while policy is loading or unavailable', async () => {
  state.api.get.mockReturnValue(new Promise(() => {}));
  await render();
  expect(await send()).toBe('default');
  state.organizationId = 'two';
  state.api.get.mockRejectedValue(new Error('offline'));
  await render();
  expect(await send()).toBe('default');
});

it('does not reuse policy from another organization or computer', async () => {
  state.api.get.mockResolvedValue({ skills: [], require_tool_approval: false });
  await render();
  expect(await send()).toBe('allow_all');
  state.organizationId = 'two';
  state.api.get.mockReturnValue(new Promise(() => {}));
  await render();
  expect(await send()).toBe('default');
  state.api = { get: vi.fn().mockResolvedValue({ skills: [], require_tool_approval: true }) };
  await render();
  expect(await send()).toBe('default');
});
