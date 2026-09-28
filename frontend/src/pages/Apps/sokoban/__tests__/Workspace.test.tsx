// @vitest-environment jsdom
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import SokobanPage from '../../SokobanPage';
import { storageKey } from '../storage';
import { levels } from '../levels';
import solutions from './solutions.json';

let userId: string | null = 'player-one';
let organizationId: string | null = 'warehouse-org';
vi.mock('@/stores/useAuthStore', () => ({ useAuthStore: (selector: (state: unknown) => unknown) => selector({ user: userId ? { id: userId } : null }) }));
vi.mock('@/stores/useOrganizationStore', () => ({ useOrganizationStore: (selector: (state: unknown) => unknown) => selector({ currentOrganizationId: organizationId }) }));

let root: Root;
let container: HTMLDivElement;
beforeEach(() => {
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  localStorage.clear(); userId = 'player-one'; organizationId = 'warehouse-org';
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); vi.restoreAllMocks(); });

async function render(query = 'entry=apps', application = '42') {
  await act(async () => root.render(<MemoryRouter key={`${query}:${application}`} initialEntries={[`/applications/${application}/sokoban?${query}`]}>
    <Routes><Route path="/applications/:applicationId/sokoban" element={<SokobanPage />} /></Routes>
  </MemoryRouter>));
}
function button(label: string) {
  const found = Array.from(container.querySelectorAll('button')).find(item => item.getAttribute('aria-label') === label || item.textContent === label);
  expect(found, label).toBeTruthy(); return found!;
}
async function click(label: string) { await act(async () => button(label).click()); }
async function chooseLevel(index: number) {
  await click('选择关卡');
  const level = levels[index - 1];
  const select = container.querySelector<HTMLSelectElement>('[aria-label="关卡难度"]')!;
  await act(async () => { select.value = level.difficulty; select.dispatchEvent(new Event('change', { bubbles: true })); });
  if (levels.filter(item => item.difficulty === level.difficulty).indexOf(level) >= 5) await click('下一页关卡');
  const target = Array.from(container.querySelectorAll<HTMLButtonElement>('.sokoban-level')).find(item => item.getAttribute('aria-label')?.startsWith(`第 ${index} 关 `))!;
  expect(target).toBeTruthy();
  await act(async () => target.click());
}
const moves = () => container.querySelector('[data-testid="moves"]')?.textContent;
const game = () => container.querySelector<HTMLElement>('[aria-label="推箱子游戏操作区"]')!;
async function key(value: string, target: HTMLElement = game(), init: KeyboardEventInit = {}) {
  await act(async () => target.dispatchEvent(new KeyboardEvent('keydown', { key: value, bubbles: true, cancelable: true, ...init })));
}

describe('Sokoban interaction', () => {
  it('keeps selection off the game screen and reaches all 20 levels through bounded pages', async () => {
    await render();
    expect(container.querySelector('.sokoban-level-grid')).toBeNull();
    for (let index = 1; index <= levels.length; index += 1) {
      await chooseLevel(index);
      expect(container.querySelector('[role="dialog"]')).toBeNull();
      expect(container.querySelector('h2[aria-current="step"]')?.textContent).toContain(levels[index - 1].name);
      expect(document.activeElement).toBe(game());
    }
  });
  it('traps modal focus, suspends keyboard moves, and restores the opener on Escape', async () => {
    await render();
    button('选择关卡').focus();
    await click('选择关卡');
    const dialog = container.querySelector<HTMLElement>('[role="dialog"]')!;
    expect(dialog.getAttribute('aria-modal')).toBe('true');
    expect(container.querySelector<HTMLElement>('.sokoban-content')?.inert).toBe(true);
    expect(container.querySelectorAll('.sokoban-level').length).toBeLessThanOrEqual(5);
    await key('d', game()); expect(moves()).toBe('0');
    const last = button('下一页关卡'); last.focus();
    await key('Tab', last);
    expect(document.activeElement).toBe(container.querySelector('[aria-label="关卡难度"]'));
    await key('Tab', document.activeElement as HTMLElement, { shiftKey: true });
    expect(document.activeElement).toBe(last);
    await key('Escape', dialog);
    expect(container.querySelector('[role="dialog"]')).toBeNull();
    expect(container.querySelector<HTMLElement>('.sokoban-content')?.inert).toBe(false);
    expect(document.activeElement).toBe(button('选择关卡'));
  });
  it('pages instructions and shows storage errors without adding game rows', async () => {
    localStorage.setItem(storageKey('warehouse-org', 'player-one', '42'), '{broken');
    await render(); await click('查看存档提示');
    expect(container.querySelector('[role="dialog"]')?.textContent).toContain('已恢复初始状态');
    await click('关闭弹层'); await click('玩法说明');
    expect(container.querySelector('[role="dialog"]')?.textContent).toContain('菱形目标点');
    await click('下一页说明'); expect(container.querySelector('[role="dialog"]')?.textContent).toContain('WASD');
    await click('下一页说明'); expect(container.querySelector('[role="dialog"]')?.textContent).toContain('不跨设备同步');
    expect(button('下一页说明').disabled).toBe(true);
    await click('关闭弹层'); await click('向右移动'); expect(moves()).toBe('1');
  });
  it('plays with keyboard and touch controls, wins, undoes and advances', async () => {
    await render(); expect(moves()).toBe('0'); expect(button('撤销一步').disabled).toBe(true);
    await key('ArrowRight'); expect(moves()).toBe('1');
    await click('向右移动'); expect(moves()).toBe('2');
    expect(container.querySelector('[role="status"]')?.textContent).toContain('所有木箱已归位');
    expect(button('向右移动').disabled).toBe(true);
    await key('a'); expect(moves()).toBe('2');
    await click('撤销一步'); expect(moves()).toBe('1');
    expect(container.querySelector('[role="status"]')?.textContent).toBe('');
    await key('d'); await click('下一关'); expect(moves()).toBe('0');
    expect(container.querySelector('[aria-current="step"]')?.textContent).toContain('02');
  });
  it('persists each level and restores undo history after remount', async () => {
    await render(); await click('向右移动');
    await chooseLevel(2); await key('d');
    await render('entry=home'); expect(moves()).toBe('1');
    await click('撤销一步'); expect(moves()).toBe('0');
    await chooseLevel(1); expect(moves()).toBe('1');
    await click('重新开始'); expect(moves()).toBe('0');
    await chooseLevel(2); expect(moves()).toBe('0');
  });
  it('does not intercept keys outside the game, input controls, or system shortcuts', async () => {
    await render();
    await key('ArrowRight', container); expect(moves()).toBe('0');
    await key('d', game(), { ctrlKey: true });
    await key('d', game(), { metaKey: true });
    await key('d', game(), { altKey: true });
    const input = document.createElement('input'); game().appendChild(input);
    await key('d', input); input.remove(); expect(moves()).toBe('0');
    await key('D'); expect(moves()).toBe('1'); await key('z'); expect(moves()).toBe('0');
  });
  it('keeps users, organizations and application instances isolated during switching', async () => {
    await render(); await key('d');
    userId = 'player-two'; await render(); expect(moves()).toBe('0');
    userId = 'player-one'; await render(); expect(moves()).toBe('1');
    organizationId = 'another-org'; await render(); expect(moves()).toBe('0');
    organizationId = 'warehouse-org'; await render(); expect(moves()).toBe('1');
    await render('entry=apps', '43'); expect(moves()).toBe('0');
  });
  it('survives corrupt data and storage read/write failures', async () => {
    localStorage.setItem(storageKey('warehouse-org', 'player-one', '42'), '{broken');
    await render(); expect(container.querySelector('[role="alert"]')?.textContent).toContain('已恢复初始状态');
    expect(moves()).toBe('0');
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked'); });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('quota'); });
    await render('standalone=1'); await click('向右移动'); expect(moves()).toBe('1');
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('无法保存');
  });
  it('finishes the last level without claiming skipped levels were completed', async () => {
    const id = levels[19].id;
    localStorage.setItem(storageKey('warehouse-org', 'player-one', '42'), JSON.stringify({ version: 1, currentLevelId: id, sessions: { [id]: { path: solutions[id as keyof typeof solutions] } } }));
    await render();
    expect(container.querySelector('[role="status"]')?.textContent).toContain('最后一关完成');
    expect(container.querySelector('[role="status"]')?.textContent).not.toContain('全部通关');
    await click('挑战未完成关卡'); expect(container.querySelector('[aria-current="step"]')?.textContent).toContain('01');
  });
  it('celebrates completing all 20 levels', async () => {
    const sessions = Object.fromEntries(levels.map(level => [level.id, { path: solutions[level.id as keyof typeof solutions] }]));
    localStorage.setItem(storageKey('warehouse-org', 'player-one', '42'), JSON.stringify({ version: 1, currentLevelId: levels[19].id, sessions }));
    await render(); expect(container.querySelector('[role="status"]')?.textContent).toContain('全部通关');
    await click('从第一关再挑战'); await click('重新开始'); expect(moves()).toBe('0');
    await click('选择关卡'); expect(button('第 1 关 第一只木箱，已通关')).toBeTruthy();
  });
  it.each([
    ['entry=apps', true], ['entry=home', false], ['entry=apps&standalone=1', false], ['entry=apps&embedded=1', false],
  ])('uses the shell navigation contract for %s', async (query, back) => {
    await render(query); expect(Boolean(container.querySelector('a[href="/apps"]'))).toBe(back);
    expect(container.querySelector('.sokoban-page')).toBeTruthy();
    expect(container.querySelector('.app-scroll-page')).toBeNull();
  });
  it('has an accessible empty state until the organization is ready', async () => {
    organizationId = null; await render(); expect(container.querySelector('[role="status"]')?.textContent).toContain('请选择组织');
    expect(container.querySelector('.sokoban-page')).toBeTruthy();
    expect(container.querySelector('.sokoban-game')).toBeNull();
  });
});
