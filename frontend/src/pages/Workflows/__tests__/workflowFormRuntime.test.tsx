// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { ConfigProvider } from 'antd';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { api } from '@/services/api';
import WorkflowsPage from '../WorkflowsPage';
import WorkflowManualRunnerPage from '../WorkflowManualRunnerPage';

vi.setConfig({ testTimeout: 30000 });
const mocks = vi.hoisted(() => ({ navigate: vi.fn(), runId: '' }));
vi.mock('react-router-dom', () => ({ useNavigate: () => mocks.navigate, useParams: () => ({ id: 'flow' }),
  useSearchParams: () => [new URLSearchParams(mocks.runId ? { runId: mocks.runId } : {})] }));
vi.mock('@/services/api', () => ({ api: { get: vi.fn(), post: vi.fn(), delete: vi.fn() } }));
vi.mock('@/stores/useOrganizationStore', () => ({ useOrganizationStore: (select: (s: unknown) => unknown) => select({ currentOrganizationId: 'org-1' }) }));
vi.mock('@/components/WorkflowBrandPicker', async () => {
  const actual = await vi.importActual<typeof import('@/components/WorkflowBrandPicker')>('@/components/WorkflowBrandPicker');
  return { ...actual, default: ({ value, onChange }: { value: unknown; onChange: (v: unknown) => void }) => <button onClick={() => onChange({
    ...(value as object), selection: { profile: { id: 'brand', name: '品牌', positioning: { audience: '品牌读者' }, voice: {}, visual: {} },
      reference: { profile_id: 'brand', modules: ['positioning'], product_ids: [], example_ids: [] } },
  })}>选择本次品牌</button> };
});

const application = { id: 8, application_id: 8, kind: 'chat', application_slug: 'writer', application_name: '写作',
  default_config: { guided_entry_prompt_key: 'write', brand_reference: { enabled: true, fields: { audience: 'positioning.audience' }, default_modules: ['positioning'] } },
  guided_prompts: [{ key: 'write', title: '写作需求', questions: [
    { key: 'source', label: '主题', type: 'text', required: true, default_value: '初始主题', options: [] },
    { key: 'audience', label: '受众', type: 'text', required: true, default_value: '默认读者', options: [] },
  ] }],
};
const flow = { id: 'flow', name: '模板流程', execution_mode: 'automatic', step_count: 1, steps: [{
  id: 'node', key: 'writer', order: 0, depends_on: [], application_id: 8, application,
  config: { form_preset: { id: 'knowledge', kind: 'builtin', name: '知识模板', prompt_key: 'write', values: { audience: '模板读者' } } },
}] };
let root: Root;
let container: HTMLDivElement;
beforeEach(() => {
  mocks.runId = '';
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() })));
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
  const computed = window.getComputedStyle.bind(window);
  vi.spyOn(window, 'getComputedStyle').mockImplementation((element) => computed(element));
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
  vi.mocked(api.get).mockImplementation(async (url) => url === '/workflows/' ? [flow] : url === '/workflows/flow/' ? flow : []);
  vi.mocked(api.post).mockResolvedValue({ id: 'run-1', status: 'running', output_summary: {} });
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); vi.restoreAllMocks(); vi.clearAllMocks(); vi.unstubAllGlobals(); });
const click = async (label: string) => {
  const button = [...document.querySelectorAll<HTMLButtonElement>('button')].find((el) => el.textContent?.replace(/\s/g, '') === label);
  expect(button, label).toBeDefined(); await act(async () => button!.click());
};

it('keeps template defaults below the chosen brand and sends only edited startup keys as explicit', async () => {
  await act(async () => root.render(<ConfigProvider theme={{ token: { motion: false } }}><WorkflowsPage /></ConfigProvider>));
  await click('运行');
  expect(document.querySelector<HTMLTextAreaElement>('#workflow-input-audience')?.value).toBe('模板读者');
  await click('选择本次品牌');
  expect(document.body.textContent).toContain('使用本次品牌资料');
  const field = document.querySelector<HTMLTextAreaElement>('#workflow-input-source')!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(field, '新主题');
    field.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await click('开始自动运行');
  expect(api.post).toHaveBeenCalledWith('/workflows/flow/start/', expect.objectContaining({
    input: { source: '新主题', audience: '模板读者' }, explicit_input_fields: ['source'],
    brand_context: { reference: { profile_id: 'brand', modules: ['positioning'], product_ids: [], example_ids: [] }, nodes: {} },
  }), expect.anything());
  expect(mocks.navigate).toHaveBeenCalledWith('/runs/run-1');
});

it('waits for brand selection before creating a manual session and passes only context identifiers to the iframe', async () => {
  vi.mocked(api.get).mockResolvedValue({ ...flow, execution_mode: 'manual' });
  await act(async () => root.render(<ConfigProvider theme={{ token: { motion: false } }}><WorkflowManualRunnerPage /></ConfigProvider>));
  expect(api.post).not.toHaveBeenCalled();
  await click('选择本次品牌'); await click('开始手动执行');
  expect(api.post).toHaveBeenCalledWith('/workflows/flow/manual-session/', expect.objectContaining({
    action: 'open', brand_context: expect.objectContaining({ reference: expect.objectContaining({ profile_id: 'brand' }) }),
  }));
  const source = container.querySelector('iframe')?.getAttribute('src') || '';
  expect(source).toContain('manualRunId=run-1'); expect(source).toContain('workflowStepKey=writer');
  expect(source).not.toContain('brand'); expect(source).not.toContain('模板读者');
});

it('resumes a manual run by id without replacing its frozen brand selection', async () => {
  mocks.runId = 'existing';
  vi.mocked(api.get).mockResolvedValue({ ...flow, execution_mode: 'manual' });
  await act(async () => root.render(<WorkflowManualRunnerPage />));
  expect(api.post).toHaveBeenCalledWith('/workflows/flow/manual-session/', { action: 'open', run_id: 'existing' });
});
