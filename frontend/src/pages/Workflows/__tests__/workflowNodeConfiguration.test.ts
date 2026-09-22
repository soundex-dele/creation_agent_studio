// @vitest-environment jsdom
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ConfigProvider } from 'antd';
import type { Workflow, WorkflowStep } from '@/types';
import { api } from '@/services/api';
import WorkflowEditorPage from '../WorkflowEditorPage';
import { WECHAT_PARALLEL_APPS, WECHAT_PARALLEL_PRESET } from '@/lib/wechatParallelWorkflow';
import { IMAGE_TEXT_PARALLEL_APPS, IMAGE_TEXT_PARALLEL_PRESET } from '../presets/imageTextParallel';
import { SHORT_VIDEO_PARALLEL_APPS, SHORT_VIDEO_PARALLEL_PRESET } from '../presets/shortVideoParallel';
import { CONTENT_SUITE_APPS, CONTENT_SUITE_PRESET } from '../presets/contentSuite';

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
  it('loads and saves the combined preset with one writer and isolated branch artifacts', async () => {
    route.id = undefined;
    route.preset = CONTENT_SUITE_PRESET;
    const apps = CONTENT_SUITE_APPS.map((slug, index) => ({
      id: index + 1, application_slug: slug, application_name: slug,
      kind: slug === 'html-to-png' ? 'task' : 'chat', default_config: {}, input_schema: {},
      guided_prompts: [{ key: 'main', title: '配置', questions: [] }],
    }));
    vi.mocked(api.get).mockImplementation(async (url) => (
      url === '/apps/' ? [] : apps.find((app) => url === `/apps/${app.application_slug}/`)
    ));
    vi.mocked(api.post).mockResolvedValue({ id: 'saved-suite' });
    await act(async () => {
      root.render(createElement(ConfigProvider, { theme: { token: { motion: false } } }, createElement(WorkflowEditorPage)));
      await import('../WorkflowGraphEditor');
    });
    expect(document.querySelectorAll('[data-node-key]')).toHaveLength(17);
    expect(document.querySelectorAll('[data-node-key="writer"]')).toHaveLength(1);
    await click(button('完成编辑'));
    await click(button('创建工作流', container));
    expect(api.post).toHaveBeenCalledWith('/workflows/', expect.objectContaining({
      execution_mode: 'automatic',
      output_mapping: expect.objectContaining({
        article_pages: { from: 'steps.article-pages-png.output.files' },
        image_text_images: { from: 'steps.image-illustrations-png.output.files' },
        video_jianying: { from: 'steps.video-jianying.output.artifacts.builder' },
        video_cover: { from: 'steps.video-cover-png.output.files' },
      }),
      steps: expect.arrayContaining([
        expect.objectContaining({ key: 'image-copy', depends_on: ['writer'] }),
        expect.objectContaining({ key: 'video-copy', depends_on: ['writer'] }),
        expect.objectContaining({ key: 'video-cover-png', depends_on: ['video-cover'],
          input_mapping: expect.objectContaining({ html_file: { from: 'steps.video-cover.output.artifacts.html' } }),
        }),
        expect.objectContaining({ key: 'video-jianying', depends_on: ['video-copy'], config: expect.objectContaining({
          workflow_artifacts: expect.objectContaining({
            builder: 'short-video/jianying/builder.py',
          }),
        }) }),
      ]),
    }));
  });

  it('loads and saves the short-video preset with parallel script and cover branches', async () => {
    route.id = undefined;
    route.preset = SHORT_VIDEO_PARALLEL_PRESET;
    const apps = SHORT_VIDEO_PARALLEL_APPS.map((slug, index) => ({
      id: index + 1, application_slug: slug, application_name: slug,
      kind: slug === 'html-to-png' ? 'task' : 'chat', default_config: {}, input_schema: {},
      guided_prompts: [{ key: 'main', title: '配置', questions: [] }],
    }));
    vi.mocked(api.get).mockImplementation(async (url) => (
      url === '/apps/' ? [] : apps.find((app) => url === `/apps/${app.application_slug}/`)
    ));
    vi.mocked(api.post).mockResolvedValue({ id: 'saved-short-video' });
    await act(async () => {
      root.render(createElement(ConfigProvider, { theme: { token: { motion: false } } }, createElement(WorkflowEditorPage)));
      await import('../WorkflowGraphEditor');
    });
    expect(document.querySelector('.workflow-graph-modal[role="dialog"]')).not.toBeNull();
    expect(document.querySelectorAll('[data-node-key]')).toHaveLength(5);
    await click(button('完成编辑'));
    await click(button('创建工作流', container));
    expect(api.post).toHaveBeenCalledWith('/workflows/', expect.objectContaining({
      execution_mode: 'automatic',
      output_mapping: expect.objectContaining({
        jianying: { from: 'steps.jianying.output.artifacts.builder' },
        cover: { from: 'steps.cover-png.output.files' },
      }),
      steps: expect.arrayContaining([
        expect.objectContaining({ key: 'copy', depends_on: ['writer'] }),
        expect.objectContaining({ key: 'jianying', depends_on: ['copy'], config: expect.objectContaining({
          automation: expect.objectContaining({ answers: expect.objectContaining({ task: { value: 'script' } }) }),
          workflow_artifacts: expect.objectContaining({ narration: 'jianying/narration.txt' }),
        }) }),
        expect.objectContaining({ key: 'cover', depends_on: ['copy'] }),
        expect.objectContaining({ key: 'cover-png', depends_on: ['cover'],
          input_mapping: expect.objectContaining({ html_file: { from: 'steps.cover.output.artifacts.html' } }),
        }),
      ]),
    }));
  });

  it.each([
    { presetId: WECHAT_PARALLEL_PRESET, applicationSlugs: WECHAT_PARALLEL_APPS, stepCount: 8,
      branchFrom: 'writer', outputName: 'pages', outputStep: 'pages-png', insertArticle: true },
    { presetId: IMAGE_TEXT_PARALLEL_PRESET, applicationSlugs: IMAGE_TEXT_PARALLEL_APPS, stepCount: 6,
      branchFrom: 'copy', outputName: 'illustrations', outputStep: 'illustrations-png', insertArticle: false },
  ])('loads $presetId in graph mode and creates it with typed PNG inputs and file bindings', async ({
    presetId, applicationSlugs, stepCount, branchFrom, outputName, outputStep, insertArticle,
  }) => {
    route.id = undefined;
    route.preset = presetId;
    const apps = applicationSlugs.map((slug, index) => ({
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
    expect(document.querySelector('.workflow-graph-modal[role="dialog"]')).not.toBeNull();
    expect(document.querySelectorAll('[data-node-key]')).toHaveLength(stepCount);
    await click(button('配置节点', document.querySelector('[data-node-key="illustrations-png"]')!));
    const dialog = document.querySelector('.ant-drawer [role="dialog"]')!;
    expect(dialog.querySelector('[role="switch"]')?.getAttribute('aria-checked')).toBe('true');
    await click(dialog.querySelector<HTMLButtonElement>('.ant-drawer-close')!);
    await click(button('完成编辑'));
    await click(button('创建工作流', container));
    expect(api.post).toHaveBeenCalledWith('/workflows/', expect.objectContaining({
      execution_mode: 'automatic',
      output_mapping: expect.objectContaining({ [outputName]: { from: `steps.${outputStep}.output.files` } }),
      steps: expect.arrayContaining([
        expect.objectContaining({ key: 'cover', depends_on: [branchFrom] }),
        expect.objectContaining({ key: 'illustrations', depends_on: [branchFrom] }),
        expect.objectContaining({ key: 'illustrations-png', input_mapping: expect.objectContaining({
          strict: { value: true },
          ...(insertArticle ? { article_source: { from: 'steps.writer.output.artifacts.article_md' } }
            : { manifest_file: { from: 'steps.illustrations.output.artifacts.manifest' } }),
        }) }),
      ]),
    }));
  });

  it(
    'opens the selected node, reopens the graph modal, and retains edits in automatic workflows', async () => {
      const execution_mode = 'automatic';
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
      expect(document.querySelector('.workflow-graph-modal[role="dialog"]')).not.toBeNull();
      expect(container.querySelector('.workflow-graph')).toBeNull();
      expect(document.querySelector('.ant-drawer-open')).toBeNull();

      // The first node is already selected when entering graph mode.
      await click(button('配置节点', document.querySelector('[data-node-key="first"]')!));
      let dialog = document.querySelector('.ant-drawer [role="dialog"]')!;
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

      await click(button('配置节点', document.querySelector('[data-node-key="first"]')!));
      dialog = document.querySelector('.ant-drawer [role="dialog"]')!;
      expect(dialog.querySelector<HTMLInputElement>('.workflow-node-name input')!.value).toBe('已修改的节点');
      await click(dialog.querySelector<HTMLButtonElement>('.ant-drawer-close')!);

      await click(button('配置节点', document.querySelector('[data-node-key="second"]')!));
      dialog = document.querySelector('.ant-drawer [role="dialog"]')!;
      expect(dialog.querySelector<HTMLInputElement>('.workflow-node-name input')!.value).toBe('second');
      await click(dialog.querySelector<HTMLButtonElement>('.ant-drawer-close')!);
      await click(button('完成编辑'));
      expect(container.querySelector('.workflow-step-list')!.textContent).toContain('已修改的节点');
      await switchMode('图编辑');
      expect(document.querySelector('[data-node-key="first"]')!.textContent).toContain('已修改的节点');
      await click(document.querySelector<HTMLButtonElement>('.workflow-graph-modal .ant-modal-close')!);
      expect(document.querySelector('.workflow-graph-modal')).toBeNull();
      await click(button('保存工作流', container));
      expect(api.put).toHaveBeenCalledWith('/workflows/workflow-1/', expect.objectContaining({
        execution_mode,
        steps: expect.arrayContaining([expect.objectContaining({ key: 'first', name: '已修改的节点' })]),
      }));
    },
  );

  it('only exposes graph editing for automatic execution and resets to the list when switching back', async () => {
    const workflow = { id: 'workflow-1', name: '手动工作流', execution_mode: 'manual', steps: [] };
    vi.mocked(api.get).mockImplementation(async (url) => url === '/apps/' ? [] : workflow);
    await act(async () => root.render(createElement(ConfigProvider, {
      theme: { token: { motion: false } },
    }, createElement(WorkflowEditorPage))));
    expect(container.querySelector('[aria-label="工作流编辑模式"]')).toBeNull();
    expect(document.querySelector('.workflow-graph')).toBeNull();
    await switchMode('自动执行');
    await switchMode('图编辑');
    const graph = document.querySelector('.workflow-graph-modal')!;
    expect(graph).not.toBeNull();
    await click(button('添加应用', graph));
    expect([...document.querySelectorAll('.ant-modal-title')].some((title) => title.textContent === '选择应用')).toBe(true);
    const picker = [...document.querySelectorAll('.ant-modal')].find((modal) => modal.textContent?.includes('选择应用'))!;
    await click(picker.querySelector<HTMLButtonElement>('.ant-modal-close')!);
    expect(document.querySelector('.workflow-graph-modal')).not.toBeNull();
    await click(button('完成编辑'));
    await switchMode('手动执行');
    expect(container.querySelector('[aria-label="工作流编辑模式"]')).toBeNull();
    expect(document.querySelector('.workflow-graph-modal')).toBeNull();
    await switchMode('自动执行');
    expect(container.querySelector('.workflow-editor-mode .ant-segmented-item-selected')?.textContent).toBe('列表编辑');
    expect(document.querySelector('.workflow-graph-modal')).toBeNull();
    expect(container.querySelector('.workflow-step-list')).not.toBeNull();
  });
});
