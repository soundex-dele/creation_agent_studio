// @vitest-environment jsdom
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import AgentActivityPanel from '../AgentActivityPanel';
import McpRequestForm from '../McpRequestForm';
import type { AgentQuestion } from '@/entities/run';

let root: Root;
let host: HTMLDivElement;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); });

it('renders progress, live output, diffs, summaries and warnings', () => {
  const html = renderToStaticMarkup(<AgentActivityPanel activity={{
    plan: { plan: [{ step: '运行测试', status: 'inProgress' }] },
    tools: { shell: { output: '23 passed' } }, diff: { diff: '-old\n+new' },
    warnings: [{ message: '已切换模型' }],
    items: { reasoning: { id: 'reasoning', type: 'reasoning', summary: ['检查测试结果'] } },
  }} />);
  for (const text of ['运行测试', '进行中', '23 passed', 'agent-diff-add', 'agent-diff-remove', '检查测试结果', '已切换模型']) expect(html).toContain(text);
});

const question: AgentQuestion = { id: 'request-1', kind: 'question', header: '工具', question: '配置', options: [],
  elicitation: true, formSchema: { type: 'object', required: ['enabled'], properties: {
    enabled: { type: 'boolean' }, count: { type: 'integer', default: 3 },
  } } };
it('submits required false booleans and schema defaults without exposing values in history', async () => {
  const answer = vi.fn().mockResolvedValue(undefined);
  await act(async () => root.render(<McpRequestForm question={question} onAnswer={answer} />));
  await act(async () => host.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })));
  expect(answer).toHaveBeenCalledWith({ action: 'accept', content: { enabled: false, count: 3 } });
});
it('allows rejecting a form and displays server validation failures', async () => {
  const answer = vi.fn().mockRejectedValue(new Error('字段类型不正确'));
  await act(async () => root.render(<McpRequestForm question={{ ...question, url: 'javascript:alert(1)' }} onAnswer={answer} />));
  expect(host.querySelector('a')).toBeNull();
  await act(async () => host.querySelector<HTMLButtonElement>('button')!.click());
  expect(answer.mock.calls[0][0].action).toBe('decline');
  expect(host.textContent).toContain('字段类型不正确');
});
