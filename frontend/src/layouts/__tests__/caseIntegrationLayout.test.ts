import { readFileSync } from 'node:fs';
import postcss from 'postcss';
import { describe, expect, it } from 'vitest';

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8');
describe('Case integration CSS/scroll contract (static, not rendered verification)', () => {
  it('attaches bounded page scrolling only for embedded case views, including loading/error states', () => {
    for (const page of ['TemplatesPage', 'TemplateDetailPage']) {
      const source = read(`../../pages/Templates/${page}.tsx`);
      expect(source).toContain('app-scroll-page case-library-embedded');
      expect(source).toContain('embedded');
      const css = read(`../../pages/Templates/${page}.css`);
      expect(css).toContain('env(safe-area-inset-bottom)');
      postcss.parse(css).walkRules(rule => {
        if (rule.selectors.some(s => /\.(templates-page|template-detail-page|template-detail-state)(?:\.|$)/.test(s))) {
          rule.walkDecls('height', d => { expect(d.value).not.toMatch(/^(auto|100d?vh)$/); });
        }
      });
    }
    expect(read('../../pages/Templates/TemplateDetailPage.tsx')).toContain('`${rootClass} template-detail-state`');
    expect(read('../../pages/Apps/DouyinBenchmarkPage.tsx')).toContain('douyin-host app-scroll-page');
  });
  it.each([320, 375, 390, 767, 768, 1280])('wraps actions and keeps touch targets usable at %spx', width => {
    const css = postcss.parse(read('../../pages/Apps/douyin/CaseIntegration.css'));
    let height = ''; let wrap = '';
    css.walkRules(rule => {
      if (rule.parent?.type === 'atrule' && rule.parent.name === 'media') {
        const max = rule.parent.params.match(/max-width:\s*(\d+)px/);
        if (max && width > Number(max[1])) return;
      }
      if (rule.selectors.includes('.case-inline-actions')) rule.walkDecls('flex-wrap', d => { wrap = d.value; });
      if (rule.selectors.includes('.case-inline-actions .ant-btn')) rule.walkDecls('min-height', d => { height = d.value; });
    });
    expect(wrap).toBe('wrap'); expect(height).toBe(width <= 767 ? '44px' : '32px');
  });
  it('bounds long previews by available viewport height and scopes field styling', () => {
    const css = read('../../pages/Apps/douyin/CaseIntegration.css');
    expect(css).toContain('max-height: 35dvh'); expect(css).toContain('overflow-y: auto');
    expect(css).toContain('overflow-wrap: anywhere'); expect(css).not.toMatch(/\slabel\s*\{/);
  });
});
