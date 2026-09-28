// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
import { copyText } from '../clipboard';

const clipboardDescriptor = Object.getOwnPropertyDescriptor(navigator, 'clipboard');
const execDescriptor = Object.getOwnPropertyDescriptor(document, 'execCommand');

function setClipboard(value: unknown) {
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value });
}

function setExecCommand(value: unknown) {
  Object.defineProperty(document, 'execCommand', { configurable: true, value });
}

afterEach(() => {
  for (const [target, key, descriptor] of [
    [navigator, 'clipboard', clipboardDescriptor],
    [document, 'execCommand', execDescriptor],
  ] as const) {
    if (descriptor) Object.defineProperty(target, key, descriptor);
    else Reflect.deleteProperty(target, key);
  }
  document.body.replaceChildren();
  window.getSelection()?.removeAllRanges();
  vi.restoreAllMocks();
});

it('prefers the Clipboard API without adding a copy control', async () => {
  const text = '# 回复\n\n中文 **内容** 🚀';
  const writeText = vi.fn(async () => {});
  const execCommand = vi.fn();
  setClipboard({ writeText });
  setExecCommand(execCommand);
  await copyText(text);
  expect(writeText).toHaveBeenCalledExactlyOnceWith(text);
  expect(execCommand).not.toHaveBeenCalled();
  expect(document.querySelector('textarea')).toBeNull();
});

it.each(['missing', 'no-write-method', 'rejected'])('copies exact text with fallback when Clipboard API is %s', async mode => {
  const text = '# 回复\n\n中文 **内容** 🚀';
  setClipboard(mode === 'missing' ? undefined : mode === 'no-write-method' ? {} : {
    writeText: vi.fn().mockRejectedValue(new DOMException('Denied', 'NotAllowedError')),
  });
  const execCommand = vi.fn(() => {
    const textarea = document.activeElement as HTMLTextAreaElement;
    expect(textarea.tagName).toBe('TEXTAREA');
    expect(textarea.value.slice(textarea.selectionStart, textarea.selectionEnd)).toBe(text);
    expect(textarea.readOnly).toBe(true);
    return true;
  });
  setExecCommand(execCommand);
  await copyText(text);
  expect(execCommand).toHaveBeenCalledExactlyOnceWith('copy');
  expect(document.querySelector('textarea')).toBeNull();
});

it.each(['success', 'false', 'throws', 'unavailable'])('restores draft focus and selection and cleans up when fallback returns %s', async result => {
  setClipboard(undefined);
  setExecCommand(result === 'unavailable' ? undefined : () => {
    if (result === 'throws') throw new Error('Denied');
    return result === 'success';
  });
  const draft = document.createElement('textarea');
  draft.value = '保留草稿和选区';
  document.body.appendChild(draft);
  draft.focus();
  draft.setSelectionRange(1, 4, 'backward');
  if (result === 'success') await copyText('消息');
  else await expect(copyText('消息')).rejects.toThrow();
  expect(document.activeElement).toBe(draft);
  expect(draft.value).toBe('保留草稿和选区');
  expect([draft.selectionStart, draft.selectionEnd, draft.selectionDirection]).toEqual([1, 4, 'backward']);
  expect(document.querySelectorAll('textarea')).toHaveLength(1);
});

it('restores an existing message text selection', async () => {
  setClipboard(undefined);
  setExecCommand(() => true);
  const paragraph = document.createElement('p');
  paragraph.textContent = '已选中的消息';
  document.body.appendChild(paragraph);
  const range = document.createRange();
  range.selectNodeContents(paragraph);
  window.getSelection()!.addRange(range);
  await copyText('另一条消息');
  expect(window.getSelection()!.toString()).toBe('已选中的消息');
});
