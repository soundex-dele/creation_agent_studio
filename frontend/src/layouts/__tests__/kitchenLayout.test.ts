import { readFileSync } from 'node:fs';
import postcss, { type Container } from 'postcss';
import { expect, it } from 'vitest';

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8');
const css = postcss.parse(read('../../styles/global.css') + read('../../pages/Apps/KitchenAssistantPage.css'));
function styles(selectors: string[], width: number, height: number) {
  const result: Record<string, string> = {};
  function visit(container: Container) {
    container.nodes?.forEach(node => {
      if (node.type === 'atrule' && node.name === 'media') {
        const condition = node.params.match(/^\((max|min)-(width|height):\s*(\d+)px\)$/);
        if (!condition) return;
        const size = condition[2] === 'width' ? width : height;
        if (condition[1] === 'max' ? size <= +condition[3] : size >= +condition[3]) visit(node);
      } else if (node.type === 'rule' && node.selectors.some(selector => selectors.includes(selector))) {
        node.walkDecls(declaration => { result[declaration.prop] = declaration.value; });
      }
    });
  }
  visit(css);
  return result;
}

it.each([[320, 640], [375, 812], [390, 844], [767, 900], [768, 900], [1440, 900], [844, 390]])(
  'keeps kitchen scrolling, dish reflow and floating timer clearance at %i × %i (static CSS)', (width, height) => {
    const page = styles(['.app-scroll-page', '.kitchen-page'], width, height);
    expect(page.height).toBe('100%');
    expect(page['min-height']).toBe('0');
    expect(page['overflow-y']).toBe('auto');
    expect(page['padding-bottom']).toBe('calc(120px + env(safe-area-inset-bottom))');
    const cooking = styles(['.kitchen-cooking'], width, height);
    expect(cooking.width).toBe('100%');
    expect(cooking['max-width']).toBeUndefined();
    const footer = styles(['.kitchen-cooking-footer'], width, height);
    expect(footer['margin-top']).toBe('24px');
    expect(footer['padding-top']).toBe('20px');
    expect(footer['flex-wrap']).toBe('wrap');
    expect(footer.gap).toBe('12px');
    const board = styles(['.kitchen-dish-board'], width, height);
    expect(board['grid-template-columns']).toBe(width < 360 ? 'minmax(0, 1fr)' : width < 768 ? 'repeat(2, minmax(0, 1fr))' : 'repeat(3, minmax(0, 1fr))');
    const dock = styles(['.kitchen-timer-dock'], width, height);
    expect(dock.position).toBe('relative');
    expect(dock.height).toBe('0');
    expect(dock['flex-shrink']).toBe('0');
    const button = styles(['.kitchen-timer-fab'], width, height);
    expect(button.position).toBe('absolute');
    expect(button.bottom).toContain('env(safe-area-inset-bottom)');
    const modal = styles(['.kitchen-timer-modal .ant-modal-body'], width, height);
    expect(modal['overflow-y']).toBe('auto');
    expect(modal['max-height']).toBe(height <= 480 ? 'calc(100dvh - 130px)' : 'calc(100dvh - 180px)');
    expect(styles(['.kitchen-dish-card'], width, height)['overflow-wrap']).toBe('anywhere');
  },
);

it('retains the full-bleed root and anchors timers outside its scrolling content', () => {
  const source = read('../../pages/Apps/KitchenAssistantPage.tsx');
  expect(source).toContain('className="kitchen-page app-scroll-page"');
  expect(source.indexOf('<FloatingTimers')).toBeGreaterThan(source.indexOf('</main>'));
  expect(source.indexOf('<FloatingTimers')).toBeLessThan(source.indexOf('<nav className="kitchen-bottom-navigation"'));
  expect(read('../../router/index.tsx')).toContain('<ApplicationShell fullBleed>{page(<KitchenAssistantPage />)}</ApplicationShell>');
});
