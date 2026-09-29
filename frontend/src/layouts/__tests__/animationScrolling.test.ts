import { readFileSync } from 'node:fs';
import postcss, { type Container } from 'postcss';
import { describe, it, expect } from 'vitest';
const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8');
const css = read('../../pages/Apps/AnimationStudioPage.css');
function declarations(selectors: string[], width: number) {
  const values: Record<string, string> = {};
  const visit = (container: Container) => container.nodes?.forEach(node => {
    if (node.type === 'atrule' && node.name === 'media') { const match = node.params.match(/max-width:\s*(\d+)px/); if (match && width <= +match[1]) visit(node); }
    else if (node.type === 'rule' && node.selectors.some(selector => selectors.includes(selector))) node.walkDecls(item => { values[item.prop] = item.value; });
  });
  visit(postcss.parse(css)); return values;
}
describe('animation workspace scroll contract', () => {
  it('attaches a bounded pane workspace to ApplicationShell fullBleed', () => {
    expect(read('../../router/index.tsx')).toContain('<ApplicationShell fullBleed>{page(<AnimationStudioPage />)}</ApplicationShell>');
    expect(read('../../pages/Apps/AnimationStudioPage.tsx')).toContain('className="animation-workspace"');
    expect(read('../../pages/Apps/AnimationStudioPage.tsx')).toContain('resolveApplicationPresentation(params)');
  });
  it.each([320, 375, 390, 767, 768, 844, 1440])('keeps pane heights bounded at %ipx including short parent viewports', width => {
    const root = declarations(['.animation-workspace'], width);
    expect(root.height).toBe('100%'); expect(root['min-height']).toBe('0'); expect(root.overflow).toBe('hidden');
    const body = declarations(['.animation-body'], width);
    expect(body['min-height']).toBe('0'); expect(body.flex).toBe('1');
    for (const pane of ['.animation-form', '.animation-results', '.animation-history']) {
      const values = declarations([pane], width);
      expect(values['overflow-y']).toBe('auto'); expect(values['min-height']).toBe('0'); expect(values.height).not.toBe('auto');
      expect(values['touch-action']).not.toBe('none');
    }
    if (width <= 767) {
      expect(declarations(['.animation-form'], width).display).toBe('none');
      expect(declarations(['.animation-workspace[data-tab="create"] .animation-form'], width).display).toBe('flex');
      expect(declarations(['.animation-form'], width).padding).toContain('safe-area-inset-bottom');
    }
  });
});
