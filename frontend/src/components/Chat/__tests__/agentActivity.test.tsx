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

it('renders progress, diffs and actionable warnings while hiding technical activity', () => {
  const html = renderToStaticMarkup(<AgentActivityPanel activity={{
    plan: { plan: [{ step: '运行测试', status: 'inProgress' }] },
    tools: { shell: { output: '23 passed' } }, diff: { diff: '-old\n+new' },
    warnings: [{ message: '已切换模型' }, {
      message: 'Codex could not find bubblewrap on PATH. Install bubblewrap with your OS package manager. Codex will use the bundled bubblewrap in the meantime.',
    }],
    items: { reasoning: { id: 'reasoning', type: 'reasoning', summary: ['检查测试结果'] } },
  }} />);
  for (const text of ['运行测试', '进行中', 'agent-diff-add', 'agent-diff-remove', '已切换模型']) expect(html).toContain(text);
  for (const text of ['bubblewrap', '工具实时输出', '23 passed', '思考摘要', '检查测试结果']) expect(html).not.toContain(text);
});

const ignoredConfigNotice = 'Codex is ignoring 1 unrecognized configuration setting. Check for typos or deprecated settings.';
const unstableFeatureNotice = 'Under-development features enabled: default_mode_request_user_input. Under-development features are incomplete and may behave unpredictably.';

it('hides repeated Codex startup notices from live and saved activity without leaving an empty panel', () => {
  const html = renderToStaticMarkup(<AgentActivityPanel activity={{ warnings: [
    { method: 'configWarning', summary: ignoredConfigNotice, details: 'user (C:\\Users\\admin\\.codex\\config.toml): `disable_response_storage` is ignored.' },
    { method: 'configWarning', summary: ignoredConfigNotice },
    { method: 'warning', message: unstableFeatureNotice },
    { message: 'Codex is ignoring 2 unrecognized configuration settings. Check for typos or deprecated settings.' },
  ] }} />);
  expect(html).toBe('');
});

it('keeps actionable configuration warnings and runtime errors alongside startup notices', () => {
  const html = renderToStaticMarkup(<AgentActivityPanel activity={{ warnings: [
    { method: 'warning', message: unstableFeatureNotice },
    { method: 'configWarning', summary: '配置文件读取失败', details: 'Permission denied' },
    { method: 'error', error: { message: '模型请求失败' } },
    { method: 'guardianWarning', message: '操作需要审批' },
    { method: 'error', message: ignoredConfigNotice },
  ] }} />);
  for (const message of ['配置文件读取失败', 'Permission denied', '模型请求失败', '操作需要审批', ignoredConfigNotice]) {
    expect(html).toContain(message);
  }
  expect(html).not.toContain('Under-development features enabled:');
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
