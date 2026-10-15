// @vitest-environment jsdom
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import PocketSalvagerPage from '../../PocketSalvagerPage';
import type { Bridge } from '../renderer';
import { step } from '../engine';

const renderer = vi.hoisted(() => ({ bridge: null as Bridge | null, fail: false, destroy: vi.fn() }));
vi.mock('../renderer', () => ({ mountGame: (_parent: HTMLElement, bridge: Bridge, ready: () => void) => {
  if (renderer.fail) throw new Error('No graphics context');
  renderer.bridge = bridge; ready(); return renderer.destroy;
} }));
vi.mock('@/stores/useAuthStore', () => ({ useAuthStore: (select: (s: unknown) => unknown) => select({ user: { id: 'captain' } }) }));
vi.mock('@/stores/useOrganizationStore', () => ({ useOrganizationStore: (select: (s: unknown) => unknown) => select({ currentOrganizationId: 'island' }) }));
let root: Root; let container: HTMLDivElement;
beforeEach(() => {
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  renderer.fail = false; renderer.bridge = null; renderer.destroy.mockClear(); localStorage.clear();
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => { callback(0); return 1; });
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });
async function render(query = 'entry=apps') {
  await act(async () => root.render(<MemoryRouter initialEntries={[`/applications/43/pocket-salvager?${query}`]}>
    <Routes><Route path="/applications/:applicationId/pocket-salvager" element={<PocketSalvagerPage />} /></Routes>
  </MemoryRouter>));
}
function button(label: string) {
  const target = [...container.querySelectorAll('button')].find(b => b.getAttribute('aria-label') === label || b.textContent?.includes(label));
  expect(target, label).toBeTruthy(); return target!;
}
async function click(label: string) { await act(async () => button(label).click()); }
const workspace = () => container.querySelector<HTMLDivElement>('.salvager-workspace')!;
async function key(value: string, target: HTMLElement = workspace(), type = 'keydown') {
  await act(async () => target.dispatchEvent(new KeyboardEvent(type, { key: value, bubbles: true, cancelable: true })));
}
describe('Pocket Salvager input and lifecycle (renderer mocked)', () => {
  it.each(['entry=home', 'entry=apps', 'standalone=1', 'embedded=1'])('supports shell presentation %s', async query => {
    await render(query);
    expect(container.querySelector('.salvager-page')).toBeTruthy();
    expect(Boolean(container.querySelector('[aria-label="返回应用"]'))).toBe(query === 'entry=apps');
    expect(container.querySelector('[role="dialog"]')).toBeTruthy();
  });
  it('starts, releases movement, pauses on Escape, and restores game focus on resume', async () => {
    await render(); expect(workspace().inert).toBe(true);
    await click('准备好了，出港'); expect(renderer.bridge!.state.phase).toBe('playing'); expect(workspace().inert).toBe(false);
    expect(document.activeElement).toBe(workspace());
    await key('d'); expect(renderer.bridge!.input.x).toBe(1);
    await key('d', workspace(), 'keyup'); expect(renderer.bridge!.input.x).toBe(0);
    await key('w'); await key('Escape'); expect(renderer.bridge!.input.y).toBe(0); expect(renderer.bridge!.state.phase).toBe('paused');
    await click('继续航行'); expect(document.activeElement).toBe(workspace()); expect(renderer.bridge!.state.phase).toBe('playing');
  });
  it('pauses on window blur and tab hiding without automatic resumption', async () => {
    await render(); await click('准备好了，出港'); await key('d');
    await act(async () => window.dispatchEvent(new Event('blur')));
    expect(renderer.bridge!.state.phase).toBe('paused'); expect(renderer.bridge!.input.x).toBe(0);
    await act(async () => window.dispatchEvent(new Event('focus')));
    expect(renderer.bridge!.state.phase).toBe('paused');
    await click('继续航行');
    vi.spyOn(document, 'hidden', 'get').mockReturnValue(true);
    await act(async () => document.dispatchEvent(new Event('visibilitychange')));
    expect(renderer.bridge!.state.phase).toBe('paused');
  });
  it('keeps modal focus inside the menu and lets Escape resume', async () => {
    await render(); await click('准备好了，出港'); await click('玩法说明');
    const dialog = container.querySelector<HTMLElement>('[role="dialog"]')!;
    expect(document.activeElement).toBe(dialog);
    await key('Tab', dialog); expect(document.activeElement).toBe(button('继续航行'));
    button('放弃本局').focus(); await key('Tab', button('放弃本局'));
    expect(document.activeElement).toBe(button('继续航行'));
    await key('Escape', dialog); expect(container.querySelector('[role="dialog"]')).toBeNull();
  });
  it('allows dock upgrades and resets only the run when retrying a result', async () => {
    await render(); await click('准备好了，出港');
    await act(async () => { renderer.bridge!.state.credits = 8; renderer.bridge!.publish(); });
    await click('船坞'); await click('扩展船舱'); expect(renderer.bridge!.state.upgrades.hold).toBe(1);
    await click('完成改装');
    await act(async () => {
      const b = renderer.bridge!; b.state.delivered = 29; b.state.cargo = 1; b.state.cargoValue = 1;
      step(b.state, { x: 0, y: 0, boost: false }, 1 / 60); b.publish();
    });
    expect(container.textContent).toContain('灯塔亮了'); expect(localStorage.length).toBe(1);
    await click('再出一趟海'); expect(renderer.bridge!.state.delivered).toBe(0); expect(renderer.bridge!.state.upgrades.hold).toBe(0);
  });
  it('retries renderer failures and disposes the active renderer on unmount', async () => {
    renderer.fail = true; await render(); expect(container.textContent).toContain('海面加载失败');
    renderer.fail = false; await click('重新加载海面'); expect(button('准备好了，出港').disabled).toBe(false);
    await act(async () => root.render(<div />)); expect(renderer.destroy).toHaveBeenCalledTimes(1);
  });
});
