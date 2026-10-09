// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { GenerationPreview } from '../douyin/GenerationPreview';
import type { DouyinTask } from '@/services/douyinBenchmark';

let root: Root; let container: HTMLDivElement;
type PreviewTask = Pick<DouyinTask, 'id' | 'status' | 'progress'>;
const task = (text: string, status = 'running', id = 'article'): PreviewTask => ({ id, status, progress: { ai_preview: { text, state: 'receiving' } } });
async function render(value: PreviewTask) { await act(async () => root.render(<GenerationPreview task={value} />)); }
async function click(text: string) { const button = [...container.querySelectorAll('button')].find(b => b.textContent === text)!; expect(button).toBeDefined(); await act(async () => button.click()); }
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); vi.unstubAllGlobals(); });

it('renders incomplete article text and replaces it on repair without exposing identifiers or HTML', async () => {
  await render(task('{"title":"文章标题","body":"第一段\\n\\n第二'));
  expect(container.textContent).toContain('第一段\n\n第二');
  expect(container.textContent).not.toContain('"body"');
  await render(task('{"title":"修正版","body":"<script>示例</script>","sample_id":"private-id"}'));
  expect(container.textContent).not.toContain('第一段');
  expect(container.textContent).not.toContain('private-id');
  expect(container.textContent).toContain('<script>示例</script>');
  expect(container.querySelector('script')).toBeNull();
});

it('handles waiting, validation, cancellation, failure and completion', async () => {
  await render({ ...task(''), progress: { ai_preview: { text: '', state: 'waiting' } } });
  expect(container.textContent).toContain('等待 AI 返回内容');
  await render({ ...task(''), progress: { ai_preview: { text: '{"body":"片段"}', state: 'received' } } });
  expect(container.textContent).toContain('正在校验结果');
  for (const status of ['cancelled', 'failed']) {
    await render(task('{"body":"片段"}', status));
    expect(container.textContent).toContain('生成已停止');
    expect(container.textContent).toContain('片段');
  }
  await render(task('{"body":"片段"}', 'succeeded'));
  expect(container.textContent).toBe('');
});

it('does not drag readers to the bottom and resets on task switch', async () => {
  await render(task('{"body":"开始"}'));
  const region = container.querySelector<HTMLElement>('[aria-label="逐步生成的内容"]')!;
  Object.defineProperties(region, { scrollHeight: { configurable: true, value: 1000 }, clientHeight: { configurable: true, value: 100 } });
  region.scrollTop = 100;
  await act(async () => region.dispatchEvent(new Event('scroll', { bubbles: true })));
  await render(task('{"body":"开始，继续生成"}'));
  expect(region.scrollTop).toBe(100);
  await click('回到最新内容');
  expect(region.scrollTop).toBe(1000);
  await click('收起内容');
  expect(container.querySelector('[aria-label="逐步生成的内容"]')).toBeNull();
  await render(task('{"body":"另一个账号"}', 'running', 'second-account'));
  expect(container.textContent).toContain('另一个账号');
  expect(container.textContent).not.toContain('继续生成');
});

it('shows topics and voice evidence before the full JSON is available', async () => {
  await render(task('{"topics":[{"title":"第一个选题","hook":"从实际问题开始'));
  expect(container.textContent).toContain('第一个选题');
  expect(container.textContent).toContain('从实际问题开始');
  await render(task('{"content":{"positioning":"知识分享"},"findings":[{"text":"保留短句","quote":"我的原话'));
  expect(container.textContent).toContain('知识分享');
  expect(container.textContent).toContain('保留短句');
  expect(container.textContent).toContain('我的原话');
});
