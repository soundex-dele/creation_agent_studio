// @vitest-environment jsdom
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, expect, it } from 'vitest';
import { useAuthStore } from '@/stores/useAuthStore';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import { ProtectedRoute } from '../guards';

const initialAuth = useAuthStore.getState();
const initialOrganizations = useOrganizationStore.getState();
let root: Root;
let host: HTMLDivElement;

beforeEach(() => {
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  useOrganizationStore.setState({ loadedForUserId: 'user-1' });
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  useAuthStore.setState(initialAuth);
  useOrganizationStore.setState(initialOrganizations);
});

it.each([
  { role: 'admin', authenticated: true, expected: '控制台内容' },
  { role: 'member', authenticated: true, expected: '首页' },
  { role: 'auditor', authenticated: true, expected: '首页' },
  { role: null, authenticated: true, expected: '首页' },
  { role: null, authenticated: false, expected: '登录' },
] as const)('restricts console access for $role (authenticated: $authenticated)', async ({ role, authenticated, expected }) => {
  useAuthStore.setState({
    isAuthenticated: authenticated,
    user: role ? { id: 'user-1', username: 'test', email: '', created_at: '', role } : null,
  });
  await act(async () => root.render(createElement(MemoryRouter, { initialEntries: ['/enterprise'] },
    createElement(Routes, {},
      createElement(Route, { path: '/', element: createElement('div', {}, '首页') }),
      createElement(Route, { path: '/auth/login', element: createElement('div', {}, '登录') }),
      createElement(Route, {
        path: '/enterprise',
        element: createElement(ProtectedRoute, {
          requiredRole: 'admin', children: createElement('div', {}, '控制台内容'),
        }),
      }),
    ),
  )));
  expect(host.textContent).toBe(expected);
});

it.each(['admin', 'member', 'auditor'] as const)('keeps settings accessible to %s', async (role) => {
  useAuthStore.setState({
    isAuthenticated: true,
    user: { id: 'user-1', username: 'test', email: '', created_at: '', role },
  });
  await act(async () => root.render(createElement(MemoryRouter, { initialEntries: ['/settings'] },
    createElement(ProtectedRoute, { children: createElement('div', {}, '设置内容') }),
  )));
  expect(host.textContent).toBe('设置内容');
});
