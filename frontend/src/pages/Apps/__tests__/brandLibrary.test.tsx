// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { ConfigProvider } from 'antd';
import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import { api } from '@/services/api';
import { BrandLibraryWorkspace } from '../BrandLibraryPage';
import ChatApplicationRuntimePage from '../ChatApplicationRuntimePage';
import { inheritedBrandFields, type BrandProfile } from '@/services/brandLibrary';
import { applicationPath } from '@/lib/applicationCatalog';

vi.setConfig({ testTimeout: 30000 });

const mocks = vi.hoisted(() => ({ loadApp: vi.fn(), organizationId: 'org-1' }));
vi.mock('@/services/api', () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } }));
vi.mock('@/stores/useAppStore', () => ({ useAppStore: (select: (state: unknown) => unknown) => select({ loadApp: mocks.loadApp }) }));
vi.mock('@/stores/useOrganizationStore', () => ({ useOrganizationStore: (select: (state: unknown) => unknown) => select({ currentOrganizationId: mocks.organizationId }) }));
vi.mock('@/stores/useAuthStore', () => ({ useAuthStore: (select: (state: unknown) => unknown) => select({ user: { id: 'user-1' } }) }));
vi.mock('@/components/Chat/ChatContainer', () => ({ default: ({ draftRequest }: { draftRequest: { text: string } }) => <div data-testid="chat-draft">{draftRequest.text}</div> }));

const base = '/organizations/org-1/applications/12/brand-library';
const profile: BrandProfile = { id: 'brand-1', application_id: 12, name: '清风品牌', positioning: { audience: '创作者' }, voice: { keywords: '自然' }, visual: {}, updated_at: '2026-09-24T08:00:00Z' };
const second = { ...profile, id: 'brand-2', name: '第二品牌' };
const config = { enabled: true, default_modules: ['positioning', 'voice'] as ('positioning' | 'voice')[], fields: { audience: 'positioning.audience' } };
const page = (results: unknown[]) => ({ count: results.length, results, next: null });
let root: Root;
let container: HTMLDivElement;
const settle = async () => act(async () => { await new Promise((resolve) => setTimeout(resolve, 35)); });
const click = async (element: HTMLElement) => act(async () => { element.click(); });
const button = (text: string) => {
  const found = [...document.querySelectorAll<HTMLButtonElement>('button')].find((element) => element.textContent?.replace(/\s/g, '') === text);
  expect(found, text).toBeDefined(); return found!;
};
const input = async (selector: string, value: string) => {
  const field = document.querySelector<HTMLInputElement | HTMLTextAreaElement>(selector)!;
  expect(field, selector).not.toBeNull();
  await act(async () => {
    Object.getOwnPropertyDescriptor(field.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype, 'value')!.set!.call(field, value);
    field.dispatchEvent(new Event('input', { bubbles: true }));
  });
};
const choose = async (id: string, label: string) => {
  const field = document.getElementById(id)!;
  await act(async () => { field.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })); });
  const item = [...document.querySelectorAll<HTMLElement>('.ant-select-item-option')].find((el) => el.textContent === label)!;
  expect(item, label).toBeDefined(); await click(item); await settle();
};
const mount = async (chat = false) => {
  const router = createMemoryRouter([{ path: '/applications/:applicationId/chat', element: chat ? <ChatApplicationRuntimePage /> : <BrandLibraryWorkspace base={base} /> }], {
    initialEntries: ['/applications/42/chat?slug=writer'],
  });
  const render = async () => {
    await act(async () => { root.render(<ConfigProvider theme={{ token: { motion: false } }}><RouterProvider router={router} /></ConfigProvider>); });
    await settle();
  };
  await render(); return async () => {
    await act(async () => { await router.navigate('/applications/42/chat?slug=writer'); });
    await settle();
  };
};

beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() })));
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
  const computed = window.getComputedStyle.bind(window);
  vi.spyOn(window, 'getComputedStyle').mockImplementation((element) => computed(element));
  vi.spyOn(window, 'confirm').mockReturnValue(false);
  mocks.organizationId = 'org-1';
  mocks.loadApp.mockResolvedValue({ id: 'writer', applicationId: 42, name: '文案', kind: 'chat', runtime: {
    default_config: { brand_reference: config }, chat_profile: {}, agent_bindings: [],
    guided_prompts: [{ id: 'write', key: 'write', title: '创作需求', questions: [
      { id: 'source', key: 'source', label: '主题', type: 'text', required: true, default_value: '新品' },
      { id: 'audience', key: 'audience', label: '受众', type: 'text', default_value: '普通读者' },
    ] }],
  } });
  vi.mocked(api.get).mockImplementation(async (url) => {
    if (url.endsWith('/products')) return page([{ id: 'product-1', name: '产品一' }]);
    if (url.endsWith('/examples')) return page([{ id: 'example-1', name: '范文一' }]);
    if (url.endsWith('/brand-1')) return profile;
    return page([profile, second]);
  });
  vi.mocked(api.post).mockResolvedValue({ prompt: '品牌提示词' });
  vi.mocked(api.patch).mockResolvedValue(profile);
  vi.mocked(api.delete).mockResolvedValue(undefined);
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount()); container.remove();
  vi.restoreAllMocks(); vi.resetAllMocks(); vi.unstubAllGlobals();
});

it('registers the dedicated app and only inherits selected, populated, unedited fields', () => {
  expect(applicationPath({ id: 'brand-library', applicationId: 12, kind: 'custom', rendererKey: 'brand-library' })).toBe('/applications/12/brand-library?entry=apps');
  const selection = { profile, reference: { profile_id: profile.id, modules: ['positioning'] as ('positioning')[], product_ids: [], example_ids: [] } };
  expect(inheritedBrandFields(config, selection, [])).toEqual(['audience']);
  expect(inheritedBrandFields(config, selection, ['audience'])).toEqual([]);
  expect(inheritedBrandFields(config, null, [])).toEqual([]);
});

it('keeps unsaved input after save failure and confirms discarding changes', async () => {
  await mount();
  await click(button('新建档案'));
  await input('#name', '我的新品牌');
  vi.mocked(api.post).mockRejectedValueOnce({ response: { data: { detail: '保存失败，请重试' } } });
  await click(button('保存')); await settle();
  expect(document.body.textContent).toContain('保存失败，请重试');
  expect(document.querySelector<HTMLInputElement>('#name')?.value).toBe('我的新品牌');
  await click(button('取消'));
  expect(window.confirm).toHaveBeenCalled();
  expect(document.querySelector('#name')).not.toBeNull();
  vi.mocked(api.post).mockResolvedValueOnce(profile);
  await click(button('保存')); await settle();
  expect(document.body.textContent).toContain('资料已保存');
});

it('loads profile details and edits structured data', async () => {
  await mount();
  await click([...container.querySelectorAll<HTMLButtonElement>('button')].find((el) => el.textContent?.includes('清风品牌'))!);
  await settle();
  expect(container.textContent).toContain('创作者');
  await click(button('编辑档案'));
  await input('#positioning_audience', '新的读者');
  await click(button('保存')); await settle();
  expect(api.patch).toHaveBeenCalledWith(`${base}/profiles/brand-1`, expect.objectContaining({
    positioning: expect.objectContaining({ audience: '新的读者' }), voice: profile.voice,
  }));
});

async function pickBrand() {
  await click(container.querySelector<HTMLElement>('.ant-collapse-header')!);
  await choose('brand-profile', '清风品牌');
}

it('composes explicit brand references, invalidates edited previews and enters chat', async () => {
  await mount(true); await pickBrand();
  expect(container.textContent).toContain('使用品牌资料');
  await click(button('生成提示词')); await settle();
  expect(api.post).toHaveBeenLastCalledWith('/apps/writer/compose-prompt/', expect.objectContaining({ brand_reference: { profile_id: 'brand-1', modules: ['positioning', 'voice'], product_ids: [], example_ids: [] }, explicit_fields: [] }));
  expect(container.textContent).toContain('生成的提示词');
  await click(button('改为本次填写'));
  expect(container.textContent).not.toContain('生成的提示词');
  await click(button('生成提示词')); await settle();
  expect(api.post).toHaveBeenLastCalledWith('/apps/writer/compose-prompt/', expect.objectContaining({ explicit_fields: ['audience'] }));
  await click(button('进入对话')); await settle();
  expect(container.querySelector('[data-testid="chat-draft"]')?.textContent).toBe('品牌提示词');
});

it('clears selected items when switching brands and restores defaults when cancelling', async () => {
  await mount(true); await pickBrand();
  const products = [...container.querySelectorAll<HTMLElement>('.ant-checkbox-wrapper')].find((el) => el.textContent === '产品事实')!;
  await click(products.querySelector('input')!); await settle();
  await choose('brand-products', '产品一');
  await click(button('生成提示词')); await settle();
  expect(api.post).toHaveBeenLastCalledWith('/apps/writer/compose-prompt/', expect.objectContaining({ brand_reference: expect.objectContaining({ product_ids: ['product-1'] }) }));
  await choose('brand-profile', '第二品牌');
  expect(container.textContent).not.toContain('生成的提示词');
  await click(button('生成提示词')); await settle();
  expect(api.post).toHaveBeenLastCalledWith('/apps/writer/compose-prompt/', expect.objectContaining({ brand_reference: expect.objectContaining({ profile_id: 'brand-2', product_ids: [], example_ids: [] }) }));
  await act(async () => { container.querySelector<HTMLElement>('.ant-select-clear')!.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })); });
  await settle();
  expect(container.textContent).not.toContain('生成的提示词');
  expect([...container.querySelectorAll<HTMLTextAreaElement>('textarea')].some((el) => el.value === '普通读者')).toBe(true);
  await click(button('生成提示词')); await settle();
  const calls = vi.mocked(api.post).mock.calls;
  expect(calls[calls.length - 1]?.[1]).not.toHaveProperty('brand_reference');
});

it('ignores in-flight previews after a form change', async () => {
  await mount(true);
  let resolve!: (value: { prompt: string }) => void;
  vi.mocked(api.post).mockReturnValueOnce(new Promise((done) => { resolve = done; }));
  await click(button('生成提示词'));
  await input('.chat-app-field textarea', '不同主题');
  await act(async () => resolve({ prompt: '过期结果' })); await settle();
  expect(container.textContent).not.toContain('生成的提示词');
});

it('clears brand selections and generated prompts on organization change', async () => {
  const refresh = await mount(true); await pickBrand();
  await click(button('生成提示词')); await settle();
  expect(container.textContent).toContain('生成的提示词');
  mocks.organizationId = 'org-2';
  await refresh();
  expect(container.textContent).not.toContain('生成的提示词');
  expect(container.textContent).not.toContain('引用品牌资料 · 清风品牌');
  expect(api.get).toHaveBeenCalledWith('/organizations/org-2/brand-library/profiles', { page: 1 }, expect.anything());
});
