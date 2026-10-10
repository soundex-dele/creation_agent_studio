// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ArticleEditor } from '../douyin/ArticleEditor';
import { ResearchResult } from '../douyin/ResearchResult';
import { researchTaskStatus } from '@/services/douyinResearch';
import type { ResearchClient, ResearchTask, StyleReview } from '@/services/douyinResearch';
import { saveResearchBlob } from '@/services/researchAssistant';

vi.mock('@/services/researchAssistant', () => ({ saveResearchBlob: vi.fn() }));
let container: HTMLDivElement; let root: Root; let client: ResearchClient;
let clipboardDescriptor: PropertyDescriptor | undefined;
const content = { title: '标题', body: '真实正文', notes: ['核对事实'] };
const version = { id: 'v1', revision: 1, content, created_at: '2026-10-10T00:00:00Z' };
const reviewed: StyleReview = { status: 'completed', summary: '保留样本中的留白结尾。', revision: 1 };
beforeEach(() => {
  vi.clearAllMocks();
  clipboardDescriptor = Object.getOwnPropertyDescriptor(navigator, 'clipboard');
  Object.defineProperty(globalThis, 'IS_REACT_ACT_ENVIRONMENT', { configurable: true, value: true });
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() })));
  const original = window.getComputedStyle; vi.spyOn(window, 'getComputedStyle').mockImplementation(el => original(el));
  client = { versions: vi.fn().mockResolvedValue([version]), saveVersion: vi.fn(), editor: { download: vi.fn().mockResolvedValue(new Blob(['# 标题\n\n真实正文'])) } } as unknown as ResearchClient;
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); if (clipboardDescriptor) Object.defineProperty(navigator, 'clipboard', clipboardDescriptor); else Reflect.deleteProperty(navigator, 'clipboard'); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
async function render(review?: StyleReview) { await act(async () => root.render(<ArticleEditor client={client} taskId="task1" styleReview={review} />)); }
async function click(text: string) { const button = [...container.querySelectorAll('button')].find(el => el.textContent === text)!; expect(button).toBeDefined(); await act(async () => button.click()); }

it.each([
  ['completed', '生成版本 1 已完成模型文风校对'],
  ['unavailable', '文风校对未完成，已保留初稿'],
  ['not_applicable', '未进行文风校对'],
] as const)('shows %s status separately from article content', async (status, label) => {
  await render({ ...reviewed, status });
  expect(container.textContent).toContain(label);
  expect(container.querySelector<HTMLTextAreaElement>('[aria-label="文章正文"]')!.value).toBe(content.body);
});

it('supports historical tasks without review metadata', async () => {
  await render();
  expect(container.textContent).not.toContain('文风校对');
  expect(container.textContent).toContain('复制正文');
});

it('keeps review metadata out of copied text and exported article', async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
  await render(reviewed); await click('复制正文'); await click('导出文章 Markdown');
  expect(writeText).toHaveBeenCalledWith('真实正文');
  expect(client.editor.download).toHaveBeenCalledWith('', 'task1', 'v1');
  expect(saveResearchBlob).toHaveBeenCalledWith(expect.any(Blob), '标题.md');
});

it('does not apply the generation review to a later saved version and restores it on history selection', async () => {
  vi.mocked(client.versions).mockResolvedValue([{ ...version, id: 'v2', revision: 2 }, version] as Awaited<ReturnType<ResearchClient['versions']>>);
  await render(reviewed);
  expect(container.textContent).toContain('当前修改未进行文风校对');
  const select = container.querySelector('[aria-label="文章历史版本"]')!;
  await act(async () => select.closest('.ant-select')!.querySelector('.ant-select-selector')!.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })));
  const option = [...document.querySelectorAll<HTMLElement>('.ant-select-item-option-content')].find(el => el.textContent?.startsWith('版本 1'))!;
  await act(async () => option.click());
  expect(container.textContent).toContain('生成版本 1 已完成模型文风校对');
});

it('shows the review stage before exposing the final editable article', async () => {
  const task = { id: 'task1', kind: 'article', status: 'running', stage: '正在校对个人文风', output: {}, progress: {}, error: '' } as ResearchTask;
  await act(async () => root.render(<ResearchResult client={client} task={task} run={vi.fn()} />));
  expect(researchTaskStatus(task)).toBe('正在校对个人文风');
  expect(container.querySelector('[aria-label="文章正文"]')).toBeNull();
  await act(async () => root.render(<ResearchResult client={client} task={{ ...task, status: 'succeeded', output: { ...content, style_review: reviewed } }} run={vi.fn()} />));
  expect(container.textContent).toContain('生成版本 1 已完成模型文风校对');
  expect(container.querySelector('[aria-label="文章正文"]')).not.toBeNull();
});
