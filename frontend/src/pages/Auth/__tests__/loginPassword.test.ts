// @vitest-environment jsdom
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '@/services/api';
import { getNativeCredentialRequest } from '@/services/nativeCredentials';
import LoginPage from '../LoginPage';

const { login } = vi.hoisted(() => ({ login: vi.fn() }));
vi.mock('@/stores/useAuthStore', () => ({ useAuthStore: (selector: (state: unknown) => unknown) => selector({ login }) }));
vi.mock('@/services/api', () => ({ api: { get: vi.fn() } }));
vi.mock('@/services/nativeCredentials', () => ({ getNativeCredentialRequest: vi.fn() }));

let container: HTMLDivElement;
let root: Root;
const request = vi.fn<NonNullable<ReturnType<typeof getNativeCredentialRequest>>>();
const saved = { username: 'alice', password: 'test-password' };
const settle = () => act(async () => { await new Promise(resolve => setTimeout(resolve, 20)); });
const field = (name: string) => container.querySelector<HTMLInputElement>(`#login_${name}`)!;
const submit = async () => {
  await act(async () => container.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })));
  await settle();
};
const render = async () => {
  await act(async () => root.render(createElement(MemoryRouter, {}, createElement(LoginPage))));
  await settle();
};

beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() })));
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
  const getStyle = window.getComputedStyle.bind(window);
  vi.spyOn(window, 'getComputedStyle').mockImplementation(element => getStyle(element));
  vi.mocked(api.get).mockResolvedValue({ mode: 'account', registration_enabled: false });
  login.mockReset().mockResolvedValue(undefined);
  request.mockReset().mockImplementation(async action => action === 'load' ? saved : null);
  vi.mocked(getNativeCredentialRequest).mockReturnValue(request);
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  document.body.innerHTML = '';
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('remember mobile login password', () => {
  it('fills saved credentials and saves only after successful login', async () => {
    await render();
    expect(field('username').value).toBe(saved.username);
    expect(field('password').value).toBe(saved.password);
    expect(container.querySelector<HTMLInputElement>('input[type=checkbox]')!.checked).toBe(true);
    expect(request).not.toHaveBeenCalledWith('save', expect.anything());
    await submit();
    expect(login).toHaveBeenCalledWith(saved.username, saved.password);
    expect(request).toHaveBeenCalledWith('save', saved);
  });

  it('never stores a rejected password', async () => {
    login.mockRejectedValue(new Error('Invalid password'));
    await render();
    await submit();
    expect(request).not.toHaveBeenCalledWith('save', expect.anything());
  });

  it('removes the saved password when unchecked and does not save it again', async () => {
    await render();
    await act(async () => container.querySelector<HTMLInputElement>('input[type=checkbox]')!.click());
    expect(request).toHaveBeenCalledWith('clear');
    await submit();
    expect(login).toHaveBeenCalled();
    expect(request).not.toHaveBeenCalledWith('save', expect.anything());
  });

  it('does not overwrite user input when saved credentials arrive late', async () => {
    let finish!: (value: typeof saved) => void;
    request.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    await render();
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(field('username'), 'new-user');
      field('username').dispatchEvent(new Event('input', { bubbles: true }));
    });
    await act(async () => finish(saved));
    expect(field('username').value).toBe('new-user');
    expect(field('password').value).toBe('');
  });

  it('uses browser autofill without offering unsupported native storage on the web', async () => {
    vi.mocked(getNativeCredentialRequest).mockReturnValue(undefined);
    await render();
    expect(container.querySelector('input[type=checkbox]')).toBeNull();
    expect(field('username').autocomplete).toBe('username');
    expect(field('password').autocomplete).toBe('current-password');
    expect(request).not.toHaveBeenCalled();
  });
});
