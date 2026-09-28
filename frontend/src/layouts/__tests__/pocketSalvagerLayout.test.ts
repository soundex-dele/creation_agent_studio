import { readFileSync } from 'node:fs';
import postcss, { type Container } from 'postcss';
import { describe, expect, it } from 'vitest';
const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8');
const styles = read('../../pages/Apps/PocketSalvagerPage.css');
// Static contracts only: jsdom cannot establish real layout or touch scrolling.
function declarations(selector: string, width: number, height: number) {
  const result: Record<string, string> = {};
  const visit = (container: Container) => container.nodes?.forEach(node => {
    if (node.type === 'atrule' && node.name === 'container') {
      const conditions = [...node.params.matchAll(/\((min|max)-(width|height):\s*(\d+)px\)/g)];
      if (conditions.every(([, bound, axis, value]) => bound === 'min' ? (axis === 'width' ? width : height) >= Number(value) : (axis === 'width' ? width : height) <= Number(value))) visit(node);
    } else if (node.type === 'rule' && node.selectors.includes(selector)) node.walkDecls(d => { result[d.prop] = d.value; });
  });
  visit(postcss.parse(styles)); return result;
}
describe('Pocket Salvager bounded playfield', () => {
  it('attaches the game to a full-bleed application shell', () => {
    expect(read('../../router/index.tsx')).toContain('<ApplicationShell fullBleed>{page(<PocketSalvagerPage />)}</ApplicationShell>');
    expect(read('../../pages/Apps/pocket-salvager/Workspace.tsx')).toContain('className="salvager-page"');
    expect(read('../../pages/Apps/PocketSalvagerPage.tsx')).toContain('resolveApplicationPresentation(params).showApplicationHeader');
  });
  it.each([320, 375, 390, 767, 768, 844, 1440])('keeps menus scrollable without growing the playfield at width %i', width => {
    for (const height of [240, 375, 700]) {
      for (const selector of ['.salvager-page', '.salvager-workspace']) {
        const root = declarations(selector, width, height);
        expect(root.height).toBe('100%'); expect(root['min-height']).toBe('0'); expect(root['min-width']).toBe('0'); expect(root.overflow).toBe('hidden');
        expect(root['touch-action']).toBeUndefined();
      }
      const dialog = declarations('.salvager-dialog', width, height);
      expect(dialog['max-height']).toBe('100%'); expect(dialog['overflow-y']).toBe('auto');
      expect(dialog['touch-action']).toBeUndefined();
    }
  });
  it('limits special gestures to the joystick, reserves safe areas, and bounds loading/error states', () => {
    expect(declarations('.salvager-stick', 375, 700)['touch-action']).toBe('none');
    expect(declarations('.salvager-overlay', 375, 240).padding).toContain('env(safe-area-inset-bottom)');
    expect(declarations('.salvager-bottom', 375, 240).bottom).toContain('env(safe-area-inset-bottom)');
    expect(declarations('.salvager-empty', 375, 240)['overflow-y']).toBe('auto');
    expect(styles).not.toMatch(/100d?vh/);
  });
  it('keeps the harbor bearing visible when short screens collapse the chart', () => {
    expect(declarations('.salvager-minimap', 844, 240).display).not.toBe('none');
    expect(declarations('.salvager-minimap > svg', 844, 240).display).toBe('none');
    expect(declarations('.salvager-minimap span svg', 844, 240).width).toBe('16px');
  });
});
