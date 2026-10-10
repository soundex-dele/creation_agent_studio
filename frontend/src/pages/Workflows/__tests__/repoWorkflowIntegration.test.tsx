// @vitest-environment jsdom
import { act, type ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { ConfigProvider } from 'antd';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '@/services/api';
import type { ApplicationRuntime, Workflow } from '@/types';
import RepoExplainerPage from '@/pages/Apps/RepoExplainerPage';
import WorkflowEditorPage from '../WorkflowEditorPage';
import WorkflowsPage from '../WorkflowsPage';
import { CONTENT_SUITE_APPS, buildContentSuiteWorkflow } from '../presets/contentSuite';
import { repoWorkflowEditorPath, repoWorkflowReturnPath } from '../repoWorkflowSource';
import { repoProjectFixture, repoSource } from './fixtures/repoWorkflow';

const route = vi.hoisted(() => ({ id: undefined as string | undefined, query: '', organizationId: '', userId: 'user-1', navigate: vi.fn() }));
vi.mock('@/services/api', () => ({ api: { get: vi.fn(), put: vi.fn(), post: vi.fn(), delete: vi.fn() } }));
vi.mock('react-router-dom', () => ({
  useParams: () => ({ id: route.id, applicationId: '7' }), useNavigate: () => route.navigate,
  useSearchParams: () => [new URLSearchParams(route.query), vi.fn()],
}));
vi.mock('@/stores/useOrganizationStore', () => ({ useOrganizationStore: (select: (s: unknown) => unknown) => select({ currentOrganizationId: route.organizationId }) }));
vi.mock('@/stores/useAuthStore', () => ({ useAuthStore: (select: (s: unknown) => unknown) => select({ user: { id: route.userId } }) }));
vi.mock('../WorkflowGraphEditor', () => ({ default: () => null }));

const apps = CONTENT_SUITE_APPS.map((slug, index) => ({
  id: index + 1, application_slug: slug, application_name: slug,
  kind: slug === 'html-to-png' ? 'task' : 'chat', default_config: {}, input_schema: {},
  guided_prompts: [{ key: 'main', title: '配置', questions: [] }],
})) as unknown as ApplicationRuntime[];
const projectUrl = `/organizations/${repoSource.organizationId}/applications/7/repo-explainer/projects/${repoSource.projectId}`;
let root: Root;
let container: HTMLDivElement;

beforeEach(() => {
  route.id = undefined;
  route.query = repoWorkflowEditorPath(repoSource).split('?')[1];
  route.organizationId = repoSource.organizationId;
  route.userId = 'user-1';
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() })));
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
  const computed = window.getComputedStyle.bind(window);
  vi.spyOn(window, 'getComputedStyle').mockImplementation(element => computed(element));
  localStorage.clear();
  vi.mocked(api.get).mockImplementation(async url => {
    if (url === projectUrl) return repoProjectFixture();
    return apps.find(app => url === `/apps/${app.application_slug}/`) || [];
  });
  vi.mocked(api.post).mockResolvedValue({ id: 'saved-suite' });
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount()); container.remove();
  vi.restoreAllMocks(); vi.resetAllMocks(); vi.unstubAllGlobals(); localStorage.clear();
});
const render = async (element: ReactNode = <WorkflowEditorPage />) => act(async () => {
  root.render(<ConfigProvider theme={{ token: { motion: false } }}>{element}</ConfigProvider>);
});
const button = (label: string) => {
  const result = [...document.querySelectorAll<HTMLButtonElement>('button')].find(el => el.textContent?.replace(/\s/g, '') === label);
  expect(result, label).toBeDefined(); return result!;
};
const click = async (element: HTMLElement) => act(async () => element.click());
const material = () => container.querySelector<HTMLTextAreaElement>('#workflow-topic-material');
const change = async (field: HTMLTextAreaElement, value: string) => act(async () => {
  Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(field, value);
  field.dispatchEvent(new Event('input', { bubbles: true }));
});

describe('repository source to workflow editor', () => {
  it.each(['missing', 'throwing', 'absent'])('opens the selected features without executing anything when crypto is %s', async mode => {
    vi.stubGlobal('crypto', mode === 'absent' ? undefined : {
      randomUUID: mode === 'throwing' ? () => { throw new Error('insecure context'); } : undefined,
    });
    route.query = `project=${repoSource.projectId}`;
    await render(<RepoExplainerPage />);
    await click([...container.querySelectorAll<HTMLElement>('[role="tab"]')].find(el => el.textContent === '功能解读')!);
    expect(button('用已选0项功能创作').disabled).toBe(true);
    expect(button('用总预设制作全套素材').disabled).toBe(true);
    const choices = [...container.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')].filter(el => el.closest('label')?.textContent === '用于创作');
    await click(choices[0]); await click(choices[2]);
    expect(container.textContent).toContain('已选 2 项功能');
    expect(button('用已选2项功能创作').disabled).toBe(false);
    await click(button('用总预设制作全套素材'));
    expect(route.navigate).toHaveBeenCalledWith(repoWorkflowEditorPath({ ...repoSource, featureIds: ['f1', 'f3'] }));
    route.navigate.mockClear();
    await click(button('用已选2项功能创作'));
    expect(container.textContent).toContain('write-short-video-copy');
    expect(button('生成文案').disabled).toBe(false);
    expect(route.navigate).not.toHaveBeenCalled();
    expect(api.post).not.toHaveBeenCalled();
  });

  it('reloads source after refresh, saves edited material, reopens it and submits it through the existing run form', async () => {
    await render();
    expect(material()?.value).toContain('analyzed-commit');
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    expect(api.post).not.toHaveBeenCalled();
    expect(api.put).not.toHaveBeenCalled();
    await act(async () => root.unmount()); root = createRoot(container);
    await render();
    expect(vi.mocked(api.get).mock.calls.filter(([url]) => url === projectUrl)).toHaveLength(2);
    const edited = `${material()!.value}\n面向新手，重点介绍查询功能。`;
    await change(material()!, edited);
    await click(button('创建工作流'));
    const saved = { ...(vi.mocked(api.post).mock.calls[0][1] as Workflow), id: 'saved-suite',
      step_count: 17, steps: buildContentSuiteWorkflow(apps).steps };
    expect(saved.is_public).toBe(false);
    expect(saved.name).toContain('示例仓库');
    expect(saved.input_schema?.properties?.topic.default).toBe(edited);
    expect(saved.steps).toHaveLength(17);
    expect(route.navigate).toHaveBeenCalledWith('/workflows');

    route.id = saved.id;
    // Editing an existing workflow must ignore even invalid repository query parameters.
    route.query = 'preset=wechat-content-suite&repoProject=invalid';
    vi.mocked(api.get).mockImplementation(async url => url === '/workflows/saved-suite/' ? saved : []);
    vi.mocked(api.put).mockResolvedValue(saved);
    await render();
    expect(material()?.value).toBe(edited);
    await click(button('保存工作流'));
    expect(api.put).toHaveBeenCalledWith('/workflows/saved-suite/', expect.objectContaining({ input_schema: saved.input_schema }));

    vi.mocked(api.get).mockImplementation(async url => url === '/workflows/' ? [saved] : url === '/workflows/saved-suite/' ? saved : []);
    vi.mocked(api.post).mockClear().mockResolvedValue({ id: 'run-1' });
    await render(<WorkflowsPage />);
    await click(button('运行'));
    expect(api.get).toHaveBeenLastCalledWith('/workflows/saved-suite/');
    expect(document.body.textContent).toContain('开始自动运行');
    expect(document.querySelector<HTMLTextAreaElement>('#workflow-input-topic')?.value).toBe(edited);
    expect(api.post).not.toHaveBeenCalled();
    await click(button('开始自动运行'));
    expect(api.post).toHaveBeenCalledWith('/workflows/saved-suite/start/', expect.objectContaining({ input: { topic: edited } }), expect.anything());
  }, 30000);

  it('does not carry a stale selection into a newer analysis with matching feature ids', async () => {
    route.query = `project=${repoSource.projectId}`;
    await render(<RepoExplainerPage />);
    await click([...container.querySelectorAll<HTMLElement>('[role="tab"]')].find(el => el.textContent === '功能解读')!);
    const choice = [...container.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')].find(el => el.closest('label')?.textContent === '用于创作')!;
    await click(choice);
    const newer = repoProjectFixture();
    newer.tasks[0].id = '77777777-7777-4777-8777-777777777777';
    const originalGet = vi.mocked(api.get).getMockImplementation()!;
    vi.mocked(api.get).mockImplementation((...args) => args[0] === projectUrl ? Promise.resolve(newer) : originalGet(...args));
    await click(button('刷新'));
    expect(container.textContent).toContain('所选分析已不可用');
    expect(container.textContent).not.toContain('用总预设制作全套素材');
    expect(route.navigate).not.toHaveBeenCalled();
    expect(api.post).not.toHaveBeenCalled();
  });

  it.each(['organization', 'user'])('discards loaded material when the %s changes', async context => {
    await render();
    expect(material()).not.toBeNull();
    const reads = vi.mocked(api.get).mock.calls.filter(([url]) => url === projectUrl).length;
    if (context === 'organization') route.organizationId = '66666666-6666-4666-8666-666666666666';
    else {
      route.userId = 'user-2';
      vi.mocked(api.get).mockRejectedValue({ response: { status: 403, data: { detail: '无权读取项目' } } });
    }
    await render();
    expect(material()).toBeNull();
    expect(container.textContent).toContain(context === 'organization' ? '当前组织与仓库素材来源不一致' : '无权读取项目');
    if (context === 'organization') expect(vi.mocked(api.get).mock.calls.filter(([url]) => url === projectUrl)).toHaveLength(reads);
    expect(api.post).not.toHaveBeenCalled();
  });

  it('ignores a pending source response after the organization changes', async () => {
    let resolve!: (data: unknown) => void;
    vi.mocked(api.get).mockImplementation(() => new Promise(done => { resolve = done; }));
    await render();
    route.organizationId = '66666666-6666-4666-8666-666666666666';
    await render();
    await act(async () => resolve(repoProjectFixture()));
    expect(material()).toBeNull();
    expect(container.textContent).toContain('当前组织与仓库素材来源不一致');
    expect(api.get).toHaveBeenCalledTimes(1);
  });

  it.each(['analysis', 'feature', 'permission', 'dependency', 'parameters'])(
    'shows a recoverable error for invalid %s without creating a workflow', async problem => {
      const project = repoProjectFixture();
      const originalGet = vi.mocked(api.get).getMockImplementation()!;
      if (problem === 'analysis') project.tasks[0].status = 'failed';
      if (problem === 'feature') project.tasks[0].output.features!.shift();
      if (problem === 'parameters') route.query = 'repoProject=invalid';
      vi.mocked(api.get).mockImplementation(async (...args) => {
        if (args[0] === projectUrl) {
          if (problem === 'permission') throw { response: { status: 403, data: { detail: '无权读取项目' } } };
          return project;
        }
        if (problem === 'dependency' && args[0] === '/apps/html-to-png/') throw new Error('not installed');
        return originalGet(...args);
      });
      await render();
      expect(material()).toBeNull();
      expect(container.textContent).toContain(problem === 'dependency' ? '总预设加载失败' : '仓库素材加载失败');
      expect(api.post).not.toHaveBeenCalled();
      await click(button(problem === 'parameters' ? '返回应用中心' : '返回仓库解读助手'));
      expect(route.navigate).toHaveBeenCalledWith(problem === 'parameters' ? '/apps' : repoWorkflowReturnPath(repoSource));
    },
  );

  it('clears the material default without saving a default that violates minLength', async () => {
    await render();
    await change(material()!, '');
    await click(button('创建工作流'));
    const saved = vi.mocked(api.post).mock.calls[0][1] as Workflow;
    expect(saved.input_schema?.properties?.topic.default).toBeUndefined();
    expect(saved.input_schema?.required).toContain('topic');
  });
});
