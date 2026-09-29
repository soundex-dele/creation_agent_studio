import { readFileSync } from 'node:fs';
import postcss from 'postcss';
import { describe, expect, it } from 'vitest';
import { resolveApplicationPresentation } from '@/lib/applicationPresentation';
const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8');
describe('Douyin document workspace layout contract', () => {
  it.each(['entry=home', 'entry=apps', 'standalone=1', 'embedded=1'])('uses the common shell presentation for %s', query => {
    expect(resolveApplicationPresentation(new URLSearchParams(query))).toBeDefined();
    expect(read('../../pages/Apps/DouyinBenchmarkPage.tsx')).toContain('resolveApplicationPresentation(params)');
  });
  it('keeps stacked content parent bounded and limits long dialogs in short viewports', () => {
    const css = postcss.parse(read('../../pages/Apps/DouyinBenchmarkPage.css'));
    css.walkRules(rule => {
      if (rule.selectors.includes('.douyin-host')) rule.walkDecls(decl => {
        if (decl.prop === 'height') expect(decl.value).not.toMatch(/auto|vh/);
      });
      if (rule.selector === '.douyin-modal .ant-modal-body') {
        const values = Object.fromEntries(rule.nodes.filter(node => node.type === 'decl').map(node => [node.prop, node.value]));
        expect(values['overflow-y']).toBe('auto');
        expect(values['max-height']).toBe('min(70dvh, 720px)');
      }
    });
    expect(read('../../pages/Apps/DouyinBenchmarkPage.css')).toContain('env(safe-area-inset-bottom)');
    expect(read('../../pages/Apps/DouyinBenchmarkPage.css')).toContain('grid-template-columns: minmax(0, 1fr)');
  });
});
