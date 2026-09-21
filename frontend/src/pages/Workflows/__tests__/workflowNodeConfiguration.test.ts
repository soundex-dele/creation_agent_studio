// @vitest-environment jsdom
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ConfigProvider } from 'antd';
import type { Workflow, WorkflowStep } from '@/types';
import { api } from '@/services/api';
import WorkflowEditorPage from '../WorkflowEditorPage';
import { WECHAT_PARALLEL_APPS, WECHAT_PARALLEL_PRESET } from '@/lib/wechatParallelWorkflow';

const route = vi.hoisted(() => ({ id: 'workflow-1' as string | undefined, preset: '' }));
vi.mock('@/services/api', () => ({ api: { get: vi.fn(), put: vi.fn(), post: vi.fn() } }));
vi.mock('react-router-dom', () => ({
  useParams: () => ({ id: route.id }), useNavigate: () => vi.fn(),
  useSearchParams: () => [new URLSearchParams({ preset: route.preset })],
}));
// Layout/drag measurements require a browser. Keep the real node buttons and page/drawer
// so this regression exercises their click handlers and shared editor state in the DOM.
vi.mock('@xyflow/react', () => ({
  Background: () => null, Controls: () => null, Handle: () => null,
  Position: { Left: 'left', Right: 'right' }, MarkerType: { ArrowClosed: 'arrowclosed' },
  ReactFlow: ({ nodes, nodeTypes, onNodeClick }: any) => createElement('div', {},
    nodes.map((node: any) => createElement('div', {
      key: node.id, 'data-node-key': node.id,
      onClick: (event: MouseEvent) => onNodeClick(event, node),
    }, createElement(nodeTypes[node.type], { data: node.data, selected: node.selected })))),
}));

let root: Root;
let container: HTMLDivElement;

beforeEach(() => {
  route.id = 'workflow-1';
  route.preset = '';
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  vi.stubGlobal('matchMedia', vi.fn(() => ({
    matches: false, addListener: vi.fn(), removeListener: vi.fn(),
    addEventListener: vi.fn(), removeEventListener: vi.fn(),
  })));
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
  const getComputedStyle = window.getComputedStyle.bind(window);
  vi.spyOn(window, 'getComputedStyle').mockImplementation((element) => getComputedStyle(element));
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.restoreAllMocks();
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

const button = (text: string, scope: ParentNode = document) => {
  const result = [...scope.querySelectorAll<HTMLButtonElement>('button')]
    .find((element) => element.textContent?.replace(/\s/g, '') === text);
  expect(result, `button: ${text}`).toBeDefined();
  return result!;
};
const click = async (element: HTMLElement) => act(async () => element.click());
const switchMode = async (label: string) => {
  const option = [...container.querySelectorAll<HTMLElement>('.ant-segmented-item')]
    .find((item) => item.textContent === label);
  expect(option).toBeDefined();
  await act(async () => {
    option!.click();
    await import('../WorkflowGraphEditor');
  });
};

describe('graph node configuration', () => {
  it('loads the parallel preset in graph mode and creates it with typed PNG inputs and file bindings', async () => {
    route.id = undefined;
    route.preset = WECHAT_PARALLEL_PRESET;
    const apps = WECHAT_PARALLEL_APPS.map((slug, index) => ({
      id: index + 1, application_slug: slug, application_name: slug,
      kind: slug === 'html-to-png' ? 'task' : 'chat', default_config: {},
      input_schema: { properties: { strict: { type: 'boolean', title: '全部导出成功后继续' } } },
      guided_prompts: [{ key: 'main', title: '配置', questions: [] }],
    }));
    vi.mocked(api.get).mockImplementation(async (url) => (
      url === '/apps/' ? [] : apps.find((app) => url === `/apps/${app.application_slug}/`)
    ));
    vi.mocked(api.post).mockResolvedValue({ id: 'saved-preset' });
    await act(async () => {
      root.render(createElement(ConfigProvider, { theme: { token: { motion: false } } }, createElement(WorkflowEditorPage)));
      await import('../WorkflowGraphEditor');
    });
    expect(container.querySelectorAll('[data-node-key]')).toHaveLength(8);
    await click(button('配置节点', container.querySelector('[data-node-key="illustrations-png"]')!));
    const dialog = document.querySelector('[role="dialog"]')!;
    expect(dialog.querySelector('[role="switch"]')?.getAttribute('aria-checked')).toBe('true');
    await click(dialog.querySelector<HTMLButtonElement>('.ant-drawer-close')!);
    await click(button('创建工作流', container));
    expect(api.post).toHaveBeenCalledWith('/workflows/', expect.objectContaining({
      execution_mode: 'automatic',
      output_mapping: expect.objectContaining({ pages: { from: 'steps.pages-png.output.files' } }),
      steps: expect.arrayContaining([
        expect.objectContaining({ key: 'cover', depends_on: ['writer'] }),
        expect.objectContaining({ key: 'illustrations', depends_on: ['writer'] }),
        expect.objectContaining({ key: 'illustrations-png', input_mapping: expect.objectContaining({
          strict: { value: true }, article_source: { from: 'steps.writer.output.artifacts.article_md' },
        }) }),
      ]),
    }));
  });

  it.each(['manual', 'automatic'] as const)(
    'opens the selected node, reopens it, and retains edits in %s workflows', async (execution_mode) => {
      const workflow: Workflow = {
        id: 'workflow-1', name: '演示工作流', execution_mode, is_public: false,
        steps: ['first', 'second'].map((key, order) => ({
          id: key, key, name: key, order, depends_on: [], config: {}, condition: {}, max_attempts: 1,
          application: { id: order + 1, application_name: key, kind: 'chat', guided_prompts: [] },
        } as unknown as WorkflowStep)),
      };
      vi.mocked(api.get).mockImplementation(async (url) => url === '/apps/' ? [] : workflow);
      vi.mocked(api.put).mockResolvedValue(workflow);
      await act(async () => root.render(createElement(ConfigProvider, {
        theme: { token: { motion: false } },
      }, createElement(WorkflowEditorPage))));
      await switchMode('图编辑');
      expect(document.querySelector('[role="dialog"]')).toBeNull();

      // The first node is already selected when entering graph mode.
      await click(button('配置节点', container.querySelector('[data-node-key="first"]')!));
      let dialog = document.querySelector('[role="dialog"]')!;
      expect(dialog).not.toBeNull();
      expect(dialog.textContent).toContain('节点配置');
      const input = dialog.querySelector<HTMLInputElement>('.workflow-node-name input')!;
      expect(input.value).toBe('first');
      await act(async () => {
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, '已修改的节点');
        input.dispatchEvent(new Event('input', { bubbles: true }));
      });
      await click(dialog.querySelector<HTMLButtonElement>('.ant-drawer-close')!);
      expect(document.querySelector('.ant-drawer-open')).toBeNull();

      await click(button('配置节点', container.querySelector('[data-node-key="first"]')!));
      dialog = document.querySelector('[role="dialog"]')!;
      expect(dialog.querySelector<HTMLInputElement>('.workflow-node-name input')!.value).toBe('已修改的节点');
      await click(dialog.querySelector<HTMLButtonElement>('.ant-drawer-close')!);

      await click(button('配置节点', container.querySelector('[data-node-key="second"]')!));
      dialog = document.querySelector('[role="dialog"]')!;
      expect(dialog.querySelector<HTMLInputElement>('.workflow-node-name input')!.value).toBe('second');
      await click(dialog.querySelector<HTMLButtonElement>('.ant-drawer-close')!);
      await switchMode('列表编辑');
      expect(container.querySelector('.workflow-step-list')!.textContent).toContain('已修改的节点');
      await click(button('保存工作流', container));
      expect(api.put).toHaveBeenCalledWith('/workflows/workflow-1/', expect.objectContaining({
        execution_mode,
        steps: expect.arrayContaining([expect.objectContaining({ key: 'first', name: '已修改的节点' })]),
      }));
    },
  );
});
