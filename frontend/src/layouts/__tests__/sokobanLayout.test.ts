import { readFileSync } from 'node:fs';
import postcss, { type Container } from 'postcss';
import { describe, expect, it } from 'vitest';

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8');
const styles = read('../../pages/Apps/SokobanPage.css');

// CSS contract checks, not a browser layout simulation. Query the application's
// available area, which can be much shorter than the device screen in a shell.
function declarations(selector: string, width: number, height: number) {
  const result: Record<string, string> = {};
  const visit = (container: Container) => container.nodes?.forEach(node => {
    if (node.type === 'atrule' && node.name === 'container') {
      const conditions = [...node.params.matchAll(/\((min|max)-(width|height):\s*(\d+)px\)/g)];
      if (conditions.length && conditions.every(([, bound, axis, size]) => {
        const available = axis === 'width' ? width : height;
        return bound === 'min' ? available >= Number(size) : available <= Number(size);
      })) visit(node);
    } else if (node.type === 'rule' && node.selectors.includes(selector)) {
      node.walkDecls(item => { result[item.prop] = item.value; });
    }
  });
  visit(postcss.parse(styles));
  return result;
}

describe('Sokoban fixed-screen layout contract', () => {
  it('uses the full-bleed shell and replaces the old document scroll container', () => {
    const workspace = read('../../pages/Apps/sokoban/Workspace.tsx');
    const page = read('../../pages/Apps/SokobanPage.tsx');
    const routes = read('../../router/index.tsx');
    for (const source of [workspace, page]) {
      expect(source).toContain('className="sokoban-page"');
      expect(source).not.toContain('app-scroll-page');
    }
    expect(routes).toContain('<ApplicationShell fullBleed>{page(<SokobanPage />)}</ApplicationShell>');
    expect(workspace).not.toMatch(/onTouchMove|onWheel|document\.addEventListener/);
    expect(styles).not.toMatch(/100(?:d)?vh|overflow(?:-y)?:\s*(auto|scroll)|touch-action:\s*none/);
  });

  it.each([
    [320, 436], [375, 527], [390, 680], [320, 280], [560, 304], [601, 320],
    [767, 240], [768, 310], [844, 190], [844, 390], [1440, 740],
  ])('bounds the board and keeps controls reserved within %i × %i available pixels', (width, height) => {
    const page = declarations('.sokoban-page', width, height);
    expect(page.height).toBe('100%');
    expect(page.width).toBe('100%');
    expect(page.overflow).toBe('hidden');
    expect(page['container-type']).toBe('size');
    expect(page.padding).toContain('env(safe-area-inset-bottom)');
    for (const selector of ['.sokoban-page', '.sokoban-content', '.sokoban-game', '.sokoban-board-frame', '.sokoban-board']) {
      const style = declarations(selector, width, height);
      expect(style['min-height'], selector).toBe('0');
      expect(style['min-width'], selector).toBe('0');
      expect(style.height, selector).toBe('100%');
    }
    const game = declarations('.sokoban-game', width, height);
    const controls = declarations('.sokoban-controls', width, height);
    expect(game['grid-template-rows']).toContain('minmax(0, 1fr)');
    expect(declarations('.sokoban-content', width, height)['grid-template-rows']).toBe('44px minmax(0, 1fr)');
    expect(declarations('.sokoban-page button', width, height)['min-height']).toBe('44px');
    expect(declarations('.sokoban-page button', width, height)['min-width']).toBe('44px');
    if (width >= 560 && height <= 460) {
      expect(game['grid-template-columns']).toBe('minmax(0, 1fr) 196px');
      expect(controls['grid-column']).toBe('2');
      expect(controls['grid-row']).toBe('1 / -1');
    } else {
      expect(game['grid-template-rows']).toBe('auto minmax(0, 1fr) auto');
    }
    if (height <= 300 || (width <= 559 && height <= 400)) {
      expect(declarations('.sokoban-dpad', width, height)['grid-template-rows']).toBe('44px');
    }
  });

  it('fits all rectangular maps by both dimensions, with no cropped or stretched tiles', () => {
    const board = read('../../pages/Apps/sokoban/Board.tsx');
    expect(board).toContain('preserveAspectRatio="xMidYMid meet"');
    expect(board).toContain('viewBox=');
    expect(declarations('.sokoban-board', 375, 527)['max-height']).toBe('100%');
  });

  it('takes completion, storage errors and paged dialogs out of the game sizing flow', () => {
    expect(declarations('.sokoban-result', 320, 436).position).toBe('absolute');
    expect(declarations('.sokoban-overlay', 320, 436).position).toBe('absolute');
    expect(declarations('.sokoban-dialog', 844, 190)['max-height']).toBe('100%');
    expect(declarations('.sokoban-sr-only', 320, 436).position).toBe('absolute');
    expect(declarations('.sokoban-level-grid', 320, 436)['grid-template-columns']).toBe('repeat(5, minmax(44px, 1fr))');
  });
});
