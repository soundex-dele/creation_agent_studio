import { readFileSync } from 'node:fs';
import postcss from 'postcss';
import { describe, expect, it } from 'vitest';

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8');
const source = read('../../pages/Apps/douyin/CreationKnowledge.css');
describe('Creative knowledge scroll and responsive contract (static)', () => {
  it.each([320, 375, 390, 767, 768, 1280])('keeps cards shrinkable and reflows at %spx', width => {
    const columns: Record<string, string> = {};
    postcss.parse(source).walkRules(rule => {
      if (rule.parent?.type === 'atrule' && rule.parent.name === 'media') {
        const max = rule.parent.params.match(/max-width:\s*(\d+)px/);
        if (max && width > Number(max[1])) return;
      }
      for (const name of ['.douyin-knowledge-grid', '.douyin-knowledge-filters']) {
        if (rule.selectors.includes(name)) rule.walkDecls('grid-template-columns', decl => { columns[name] = decl.value; });
      }
    });
    expect(columns['.douyin-knowledge-grid']).toBe(width <= 767 ? 'minmax(0, 1fr)' : 'repeat(2, minmax(0, 1fr))');
    expect(columns['.douyin-knowledge-filters']).toBe(width <= 767 ? 'minmax(0, 1fr)' : 'minmax(0, 2fr) minmax(0, 1fr) minmax(0, 1fr)');
  });
  it('inherits the shell scroll owner and bounds drawer content at short heights', () => {
    expect(read('../../pages/Apps/DouyinBenchmarkPage.tsx')).toContain('douyin-host app-scroll-page');
    expect(source).toContain('.ant-drawer-body { min-height: 0; overflow-y: auto; }');
    expect(source).toContain('@media (max-height: 500px)');
    expect(source).toContain('env(safe-area-inset-bottom)');
    expect(source).not.toMatch(/height:\s*(auto|100d?vh)/);
    expect(source).toContain('display: inline-flex; align-items: flex-start');
    expect(source).not.toMatch(/\slabel\s*\{/);
  });
});
