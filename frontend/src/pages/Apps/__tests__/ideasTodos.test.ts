// @vitest-environment jsdom
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { ConfigProvider } from 'antd';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '@/services/api';
import { localDate, type Idea, type Todo } from '@/services/ideasTodos';
import { IdeasTodosWorkspace } from '../IdeasTodosPage';

vi.mock('@/services/api', () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } }));

const base = '/organizations/org-1/applications/12/ideas-todos';
const idea: Idea = { id: 'idea-1', title: '新灵感', body: '正文内容', tags: ['生活'], is_pinned: false, created_at: '2026-09-23T08:00:00Z', updated_at: '2026-09-23T08:00:00Z' };
const todo: Todo = { id: 'todo-1', title: '买牛奶', description: '早餐用', priority: 2, due_date: null, is_completed: false, completed_at: null, created_at: idea.created_at, updated_at: idea.updated_at };
const page = (results: Array<Idea | Todo>) => ({ count: results.length, next: null, previous: null, results });
let root: Root;
let container: HTMLDivElement;
const settle = async (delay = 20) => act(async () => { await new Promise((resolve) => setTimeout(resolve, delay)); });
const click = async (element: HTMLElement) => act(async () => element.click());
const button = (text: string, scope: ParentNode = document) => {
  const found = [...scope.querySelectorAll<HTMLButtonElement>('button')].find((element) => element.textContent?.replace(/\s/g, '') === text);
  expect(found, text).toBeDefined();
  return found!;
};
const input = async (selector: string, value: string) => {
  const field = document.querySelector<HTMLInputElement | HTMLTextAreaElement>(selector)!;
  expect(field, selector).not.toBeNull();
  await act(async () => {
    const prototype = field.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(prototype, 'value')!.set!.call(field, value);
    field.dispatchEvent(new Event('input', { bubbles: true }));
  });
};
const tab = async (label: string) => {
  await click([...container.querySelectorAll<HTMLElement>('[role="tab"]')].find((element) => element.textContent === label)!);
  await settle();
};
const choose = async (label: string, option: string) => {
  const field = document.querySelector<HTMLInputElement>(`input[aria-label="${label}"]`)!;
  expect(field).not.toBeNull();
  await act(async () => field.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })));
  const item = [...document.querySelectorAll<HTMLElement>('.ant-select-item-option')].find((element) => element.textContent === option)!;
  expect(item).toBeDefined();
  await click(item);
  await settle();
};
const render = async () => {
  await act(async () => root.render(createElement(MemoryRouter, {},
    createElement(ConfigProvider, { theme: { token: { motion: false } } }, createElement(IdeasTodosWorkspace, { base })))));
  await settle();
};

beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() })));
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
  const getComputedStyle = window.getComputedStyle.bind(window);
  vi.spyOn(window, 'getComputedStyle').mockImplementation((element) => getComputedStyle(element));
  vi.mocked(api.get).mockResolvedValue(page([]));
  vi.mocked(api.post).mockResolvedValue(idea);
  vi.mocked(api.patch).mockResolvedValue(idea);
  vi.mocked(api.delete).mockResolvedValue(undefined);
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.restoreAllMocks(); vi.resetAllMocks(); vi.unstubAllGlobals();
});

describe('Ideas & Todos interactions', () => {
  it('creates ideas and todos independently with different fields and endpoints', async () => {
    await render();
    await click(button('新增想法'));
    expect(document.querySelector('#entry-tags')).not.toBeNull();
    expect(document.querySelector('#entry-priority')).toBeNull();
    await input('#entry-title', '散步灵感');
    await input('#entry-body', '写一篇随笔');
    await click(button('保存'));
    expect(api.post).toHaveBeenCalledWith(`${base}/ideas`, { title: '散步灵感', body: '写一篇随笔', tags: [], is_pinned: false });
    await tab('待办');
    expect(api.get).toHaveBeenLastCalledWith(`${base}/todos`, expect.objectContaining({ status: 'pending', today: localDate() }), expect.anything());
    await click(button('新增待办'));
    expect(document.querySelector('#entry-tags')).toBeNull();
    expect(document.querySelector('#entry-priority')).not.toBeNull();
    await input('#entry-title', '买牛奶');
    await input('#entry-due-date', '2026-10-01');
    await click(button('保存'));
    expect(api.post).toHaveBeenLastCalledWith(`${base}/todos`, { title: '买牛奶', description: '', priority: 2, due_date: '2026-10-01' });
  });

  it('validates blank titles and preserves form contents after save failure', async () => {
    await render();
    await click(button('新增想法'));
    await click(button('保存'));
    expect(document.querySelector('#entry-title-error')?.textContent).toContain('请输入标题');
    expect(api.post).not.toHaveBeenCalled();
    await input('#entry-title', '不要丢失');
    await input('#entry-body', '断网后还在');
    vi.mocked(api.post).mockRejectedValueOnce({ response: { data: { title: ['服务暂不可用'] } } });
    await click(button('保存'));
    expect(document.querySelector<HTMLInputElement>('#entry-title')?.value).toBe('不要丢失');
    expect(document.querySelector<HTMLTextAreaElement>('#entry-body')?.value).toBe('断网后还在');
    expect(document.querySelector('[role="dialog"]')?.textContent).toContain('服务暂不可用');
    await click(button('保存'));
    expect(api.post).toHaveBeenCalledTimes(2);
  });

  it('keeps search filters per tab and applies status, local date and priority', async () => {
    await render();
    await input('input[aria-label="搜索想法"]', '公园');
    await input('input[aria-label="筛选标签"]', '生活');
    await settle(280);
    expect(api.get).toHaveBeenLastCalledWith(`${base}/ideas`, expect.objectContaining({ search: '公园', tag: '生活', page: 1 }), expect.anything());
    await tab('待办');
    await choose('待办状态', '今日到期');
    await choose('筛选优先级', '高优先级');
    expect(api.get).toHaveBeenLastCalledWith(`${base}/todos`, expect.objectContaining({ status: 'today', priority: 3, today: localDate() }), expect.anything());
    await tab('想法');
    expect(container.querySelector<HTMLInputElement>('input[aria-label="搜索想法"]')?.value).toBe('公园');
  });

  it('completes and restores todos using PATCH and retains state on failure', async () => {
    vi.mocked(api.get).mockImplementation(async (url) => page(url.endsWith('/todos') ? [todo] : []));
    await render(); await tab('待办');
    vi.mocked(api.patch).mockRejectedValueOnce(new Error('offline'));
    await click(container.querySelector<HTMLInputElement>('input[type="checkbox"]')!);
    expect(container.querySelector<HTMLInputElement>('input[type="checkbox"]')?.checked).toBe(false);
    expect(container.textContent).toContain('操作失败');
    vi.mocked(api.get).mockResolvedValue(page([{ ...todo, is_completed: true, completed_at: idea.updated_at }]));
    await click(container.querySelector<HTMLInputElement>('input[type="checkbox"]')!);
    expect(api.patch).toHaveBeenLastCalledWith(`${base}/todos/todo-1`, { is_completed: true });
    await settle();
    expect(container.querySelector<HTMLInputElement>('input[type="checkbox"]')?.checked).toBe(true);
    await click(container.querySelector<HTMLInputElement>('input[type="checkbox"]')!);
    expect(api.patch).toHaveBeenLastCalledWith(`${base}/todos/todo-1`, { is_completed: false });
  });

  it('pins, edits and confirms deletion of an idea', async () => {
    vi.mocked(api.get).mockResolvedValue(page([idea]));
    await render();
    await click(button('置顶'));
    expect(api.patch).toHaveBeenLastCalledWith(`${base}/ideas/idea-1`, { is_pinned: true });
    await settle();
    await click(button('编辑'));
    expect(document.querySelector<HTMLInputElement>('#entry-title')?.value).toBe(idea.title);
    await input('#entry-title', '修改想法');
    await click(button('保存'));
    expect(api.patch).toHaveBeenLastCalledWith(`${base}/ideas/idea-1`, expect.objectContaining({ title: '修改想法', tags: ['生活'] }));
    await settle();
    await click(button('删除', container));
    expect(api.delete).not.toHaveBeenCalled();
    await click(button('删除', document.querySelector('.ant-popover')!));
    expect(api.delete).toHaveBeenCalledWith(`${base}/ideas/idea-1`);
  });

  it('ignores a late response from the previous tab', async () => {
    let resolveIdeas!: (value: ReturnType<typeof page>) => void;
    vi.mocked(api.get).mockImplementation((url) => url.endsWith('/ideas')
      ? new Promise((resolve) => { resolveIdeas = resolve; }) : Promise.resolve(page([todo])));
    await render(); await tab('待办');
    await act(async () => resolveIdeas(page([idea])));
    expect(container.textContent).toContain(todo.title);
    expect(container.textContent).not.toContain(idea.title);
  });

  it('retries a failed list request and recovers from an empty last page', async () => {
    vi.mocked(api.get).mockRejectedValueOnce(new Error('offline'));
    await render();
    expect(container.textContent).toContain('操作失败');
    vi.mocked(api.get).mockResolvedValue({ ...page([idea]), count: 21 });
    await click(button('重试')); await settle();
    expect(container.textContent).toContain(idea.title);
    vi.mocked(api.get).mockRejectedValueOnce({ response: { status: 404, data: { detail: 'Invalid page.' } } });
    await click(container.querySelector<HTMLElement>('.ant-pagination-item-2')!);
    await settle(); await settle();
    expect(api.get).toHaveBeenLastCalledWith(`${base}/ideas`, expect.objectContaining({ page: 1 }), expect.anything());
  });
});

it('uses local calendar dates rather than UTC date serialization', () => {
  expect(localDate(new Date(2026, 0, 2, 0, 5))).toBe('2026-01-02');
});
