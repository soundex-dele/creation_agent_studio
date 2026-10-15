// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { ConfigProvider } from 'antd';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import type { AgentQuestion } from '@/entities/run';
import AgentQuestionCard from '../AgentQuestionCard';

let root: Root; let host: HTMLDivElement;
const onAnswer = vi.fn(async () => {});
const onCancel = vi.fn(async () => {});
const question: AgentQuestion = {
  id: 'request-1', kind: 'question', header: '探索方向', question: '先确定最重要的方向', options: [],
  questions: [
    { id: 'goal', header: '目标', question: '本次最想达到什么目标？', isOther: true,
      options: [{ label: '帮助读者', value: '帮助读者' }, { label: '介绍产品', value: '介绍产品' }] },
    { id: 'mismatch', header: '偏差', question: '之前的选题哪里不合适？', options: [] },
  ],
};
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} })));
  onAnswer.mockClear(); onCancel.mockClear();
  host = document.createElement('div'); document.body.appendChild(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

const submit = () => [...host.querySelectorAll('button')].find(button => button.textContent === '提交回答')!;
async function render(value = question) {
  await act(async () => root.render(<ConfigProvider theme={{ token: { motion: false } }}>
    <AgentQuestionCard question={value} onAnswer={onAnswer} onCancel={onCancel} />
  </ConfigProvider>));
}
async function input(element: HTMLTextAreaElement, value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(element, value);
    element.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

it('waits for all real answers and submits a selected option plus free text using question IDs', async () => {
  await render();
  expect(submit().disabled).toBe(true);
  expect(onAnswer).not.toHaveBeenCalled();
  await act(async () => host.querySelector<HTMLInputElement>('input[value="帮助读者"]')!.click());
  expect(submit().disabled).toBe(true);
  await input(host.querySelector('textarea')!, '不想要大而全的功能清单');
  await act(async () => submit().click());
  expect(onAnswer).toHaveBeenCalledExactlyOnceWith({
    answers: { goal: { answers: ['帮助读者'] }, mismatch: { answers: ['不想要大而全的功能清单'] } },
    text: undefined, selections: undefined,
  });
  await render({ ...question, id: 'request-2', questions: [{ id: 'choice', header: '选题', question: '哪个切口更合适？', options: [] }] });
  expect(submit().disabled).toBe(true);
  expect(host.querySelector('textarea')?.value).toBe('');
});

it('supports a custom answer instead of forcing the offered directions', async () => {
  await render({ ...question, questions: [question.questions![0]] });
  await act(async () => host.querySelector<HTMLInputElement>('input[value="__other__"]')!.click());
  await input(host.querySelector('textarea')!, '不知道，想先看看有哪些方向');
  await act(async () => submit().click());
  expect(onAnswer).toHaveBeenCalledWith({ answers: { goal: { answers: ['不知道，想先看看有哪些方向'] } },
    text: '不知道，想先看看有哪些方向', selections: undefined });
});
