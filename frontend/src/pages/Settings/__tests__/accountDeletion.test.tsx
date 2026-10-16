// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { ConfigProvider, message } from 'antd';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import AccountManagementPage from '../AccountManagementPage';

const mocks = vi.hoisted(() => ({
  get: vi.fn(), delete: vi.fn(), post: vi.fn(), patch: vi.fn(),
  user: { id: '1', role: 'admin' },
}));
vi.mock('@/services/api', () => ({ api: mocks }));
vi.mock('@/stores/useAuthStore', () => ({
  useAuthStore: (select: (state: { user: typeof mocks.user }) => unknown) => select({ user: mocks.user }),
}));
vi.mock('@/components/Workspace/WorkspaceHeader', () => ({ default: () => null }));

const admin = { id: 1, username: 'administrator', email: '', role: 'admin', is_active: true, created_at: '2026-10-16T00:00:00Z' };
const member = { ...admin, id: 2, username: 'member-to-delete', role: 'member' };
let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  vi.clearAllMocks();
  mocks.user = { id: '1', role: 'admin' };
  mocks.get.mockResolvedValue({ count: 2, results: [admin, member] });
  mocks.delete.mockResolvedValue(undefined);
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({
    matches: false, addListener: vi.fn(), removeListener: vi.fn(),
    addEventListener: vi.fn(), removeEventListener: vi.fn(),
  }));
  const original = window.getComputedStyle;
  vi.spyOn(window, 'getComputedStyle').mockImplementation(element => original(element));
  vi.spyOn(message, 'success').mockImplementation(() => (() => undefined) as ReturnType<typeof message.success>);
  host = document.createElement('div');
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

async function renderPage() {
  await act(async () => root.render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <MemoryRouter><AccountManagementPage /></MemoryRouter>
    </ConfigProvider>,
  ));
}

function button(text: string, parent: ParentNode = document) {
  const match = Array.from(parent.querySelectorAll('button')).find(item => (
    item.textContent?.replace(/\s/g, '') === text
  ));
  expect(match, `button ${text}`).toBeTruthy();
  return match!;
}

async function openDelete() {
  const trigger = host.querySelector<HTMLButtonElement>('[aria-label="删除账号 member-to-delete"]');
  expect(trigger).not.toBeNull();
  await act(async () => trigger!.click());
}

it('requires confirmation, supports cancellation, and disables self deletion across ID types', async () => {
  await renderPage();
  expect(host.querySelector<HTMLButtonElement>('[aria-label="删除账号 administrator"]')?.disabled).toBe(true);
  await openDelete();
  expect(document.querySelector('[role="dialog"]')?.textContent).toContain('member-to-delete');
  expect(document.querySelector('[role="dialog"]')?.textContent).toContain('无法撤销');
  expect(mocks.delete).not.toHaveBeenCalled();
  await act(async () => button('取消', document.querySelector('[role="dialog"]')!).click());
  expect(mocks.delete).not.toHaveBeenCalled();
  expect(host.textContent).toContain('member-to-delete');
});

it('deletes the selected account and refreshes the current page', async () => {
  await renderPage();
  await openDelete();
  mocks.get.mockResolvedValueOnce({ count: 1, results: [admin] });
  await act(async () => button('确认删除').click());
  expect(mocks.delete).toHaveBeenCalledExactlyOnceWith('/auth/admin/users/2/');
  expect(mocks.get).toHaveBeenLastCalledWith('/auth/admin/users/', { page: 1 });
  expect(host.textContent).not.toContain('member-to-delete');
  expect(message.success).toHaveBeenCalledWith('账号 member-to-delete 已删除');
});

it('keeps errors in the confirmation dialog and allows retry without duplicate submissions', async () => {
  await renderPage();
  await openDelete();
  mocks.delete.mockRejectedValueOnce({
    isAxiosError: true, response: { status: 409, data: { detail: '请先转移工作流' } },
  });
  await act(async () => button('确认删除').click());
  expect(document.querySelector('[role="dialog"] [role="alert"]')?.textContent).toContain('请先转移工作流');
  expect(host.textContent).toContain('member-to-delete');
  let finish!: () => void;
  mocks.delete.mockImplementationOnce(() => new Promise<void>(resolve => { finish = resolve; }));
  await act(async () => {
    button('确认删除').click();
    button('确认删除').click();
  });
  expect(mocks.delete).toHaveBeenCalledTimes(2);
  expect(button('取消', document.querySelector('[role="dialog"]')!).disabled).toBe(true);
  mocks.get.mockResolvedValueOnce({ count: 1, results: [admin] });
  await act(async () => finish());
  expect(host.textContent).not.toContain('member-to-delete');
});

it('returns to the preceding page when the last row is deleted', async () => {
  mocks.get.mockResolvedValueOnce({ count: 21, results: [admin] });
  await renderPage();
  mocks.get.mockResolvedValueOnce({ count: 21, results: [member] });
  await act(async () => host.querySelector<HTMLLIElement>('.ant-pagination-item-2')!.click());
  await openDelete();
  mocks.get.mockResolvedValueOnce({ count: 20, results: [admin] });
  await act(async () => button('确认删除').click());
  expect(mocks.get).toHaveBeenLastCalledWith('/auth/admin/users/', { page: 1 });
});

it('treats a missing account as already deleted after a lost response', async () => {
  await renderPage();
  await openDelete();
  mocks.delete.mockRejectedValueOnce(new Error('network failure'));
  await act(async () => button('确认删除').click());
  expect(document.querySelector('[role="dialog"] [role="alert"]')?.textContent).toContain('删除账号失败');
  mocks.delete.mockRejectedValueOnce({ isAxiosError: true, response: { status: 404 } });
  mocks.get.mockResolvedValueOnce({ count: 1, results: [admin] });
  await act(async () => button('确认删除').click());
  expect(host.textContent).not.toContain('member-to-delete');
  expect(message.success).toHaveBeenCalled();
});

it('does not offer account management to non-admin users', async () => {
  mocks.user.role = 'member';
  await renderPage();
  expect(host.textContent).toContain('仅管理员可管理账号');
  expect(mocks.get).not.toHaveBeenCalled();
  expect(host.querySelector('[aria-label^="删除账号"]')).toBeNull();
});
