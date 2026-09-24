// @vitest-environment jsdom
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { ConfigProvider } from 'antd';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { api } from '@/services/api';
import OrganizationGovernancePanel from '../OrganizationGovernancePanel';

vi.mock('@/services/api', () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } }));

let root: Root;
let container: HTMLDivElement;
const member = { id: 7, username: 'owner', role: 'owner', is_active: true, monthly_token_limit: 100, monthly_tokens_used: 100 };
const settle = () => act(async () => { await new Promise(resolve => setTimeout(resolve, 30)); });
const click = async (label: string) => {
  const button = [...document.querySelectorAll<HTMLButtonElement>('button')].find(item => item.textContent?.replace(/\s/g, '') === label);
  expect(button).toBeDefined();
  await act(async () => button!.click());
  await settle();
};
const render = async (role: string) => {
  await act(async () => root.render(createElement(ConfigProvider, { theme: { token: { motion: false } } },
    createElement(OrganizationGovernancePanel, { organizationId: 'org-1', role }))));
  await settle();
};
const setLimit = async (value: string) => {
  const input = document.querySelector<HTMLInputElement>('[role="dialog"] input')!;
  expect(input).not.toBeNull();
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
};

beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() })));
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
  const getComputedStyle = window.getComputedStyle.bind(window);
  vi.spyOn(window, 'getComputedStyle').mockImplementation(element => getComputedStyle(element));
  vi.mocked(api.get).mockImplementation(async url => url.includes('/members/') ? [member] : {});
  vi.mocked(api.patch).mockResolvedValue(member);
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.restoreAllMocks(); vi.resetAllMocks(); vi.unstubAllGlobals();
});

it('allows administrators to set zero and clear an owner quota', async () => {
  await render('admin');
  expect(container.textContent).toContain('配额已用尽');
  await click('设置配额');
  await setLimit('0');
  await click('保存');
  expect(api.patch).toHaveBeenLastCalledWith('/enterprise/organizations/org-1/members/7/', { monthly_token_limit: 0 });
  await click('设置配额');
  await setLimit('');
  await click('保存');
  expect(api.patch).toHaveBeenLastCalledWith('/enterprise/organizations/org-1/members/7/', { monthly_token_limit: null });
});

it('shows usage without edit controls for viewers', async () => {
  await render('viewer');
  expect(container.textContent).toContain('100 / 100');
  expect(container.textContent).toContain('配额已用尽');
  expect(container.textContent).not.toContain('设置配额');
});

it('preserves entered quota when saving fails', async () => {
  await render('owner');
  await click('设置配额');
  await setLimit('200');
  vi.mocked(api.patch).mockRejectedValueOnce(new Error('offline'));
  await click('保存');
  expect(document.querySelector<HTMLInputElement>('[role="dialog"] input')?.value).toBe('200');
  await click('保存');
  expect(api.patch).toHaveBeenLastCalledWith('/enterprise/organizations/org-1/members/7/', { monthly_token_limit: 200 });
});
