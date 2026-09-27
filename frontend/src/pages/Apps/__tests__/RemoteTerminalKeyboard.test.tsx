// @vitest-environment jsdom
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { api } from '@/services/api';
import type { TerminalEvent } from '@/services/remoteTerminal';
import RemoteTerminalPage from '../RemoteTerminalPage';

// Keep the real xterm keyboard/composition handlers; only layout and transport are mocked.
vi.mock('@xterm/addon-fit', () => ({ FitAddon: class { activate() {} dispose() {} fit() {} } }));
vi.mock('@/services/remoteTerminal', async importOriginal => ({
  ...await importOriginal<typeof import('@/services/remoteTerminal')>(),
  terminalStream: vi.fn(async (_device: string, _session: string, _cursor: number, signal: AbortSignal,
    onEvent: (event: TerminalEvent) => Promise<void>) => {
    await onEvent({ type: 'ready' });
    await new Promise<void>(resolve => signal.addEventListener('abort', () => resolve(), { once: true }));
  }),
}));

let root: Root;
let container: HTMLDivElement;
let textarea: HTMLTextAreaElement;
beforeEach(async () => {
  vi.useFakeTimers();
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  window.matchMedia = vi.fn().mockImplementation(query => ({ matches: false, media: query,
    addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() }));
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} });
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
  vi.spyOn(api, 'get').mockImplementation(async path => path.endsWith('/context/')
    ? { terminal: { enabled: true, supported: true } } : { sessions: [] });
  vi.spyOn(api, 'post').mockResolvedValue({});
  container = document.createElement('div'); document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(<MemoryRouter initialEntries={['/terminals/session']}>
      <Routes><Route path="/terminals/:sessionId" element={<RemoteTerminalPage deviceId="computer" online />} /></Routes>
    </MemoryRouter>);
  });
  await act(async () => { await vi.dynamicImportSettled(); });
  textarea = container.querySelector<HTMLTextAreaElement>('.xterm-helper-textarea')!;
  expect(textarea).not.toBeNull();
  expect(textarea.readOnly).toBe(false);
});
afterEach(async () => {
  await act(async () => root.unmount()); container.remove();
  vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals();
});

function typedText() {
  return vi.mocked(api.post).mock.calls.filter(([path]) => path.endsWith('/input/'))
    .map(([, body]) => (body as { data: string }).data).join('');
}

function key(text: string) {
  const keyCode = text.toUpperCase().charCodeAt(0);
  const down = new KeyboardEvent('keydown', { key: text, keyCode, bubbles: true, cancelable: true });
  if (textarea.dispatchEvent(down)) {
    textarea.dispatchEvent(new KeyboardEvent('keypress', {
      key: text, charCode: text.charCodeAt(0), bubbles: true, cancelable: true,
    }));
  }
  textarea.dispatchEvent(new KeyboardEvent('keyup', { key: text, keyCode, bubbles: true }));
}

it('keeps letters delivered through input events between physical keystrokes', async () => {
  await act(async () => {
    key('t');
    // Virtual keyboards and IMEs can commit text without keydown/keypress.
    textarea.value = 'ermin';
    textarea.dispatchEvent(new InputEvent('input', {
      data: 'ermin', inputType: 'insertText', bubbles: true, composed: true,
    }));
    key('a'); key('l');
    await vi.advanceTimersByTimeAsync(25);
  });
  expect(typedText()).toBe('terminal');
});

it('sends a committed Chinese composition once before subsequent letters', async () => {
  await act(async () => {
    textarea.dispatchEvent(new CompositionEvent('compositionstart', { bubbles: true }));
    textarea.dispatchEvent(new CompositionEvent('compositionupdate', { data: '中文', bubbles: true }));
    textarea.value = '中文';
    await vi.advanceTimersByTimeAsync(1);
    textarea.dispatchEvent(new CompositionEvent('compositionend', { data: '中文', bubbles: true }));
    await vi.advanceTimersByTimeAsync(1);
    key('o'); key('k');
    await vi.advanceTimersByTimeAsync(25);
  });
  expect(typedText()).toBe('中文ok');
});
