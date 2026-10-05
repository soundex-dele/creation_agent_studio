import { readFileSync } from 'node:fs';
import postcss, { type Container } from 'postcss';
import { expect, it } from 'vitest';
import { applicationPath } from '../../lib/applicationCatalog';
import { resolveApplicationPresentation } from '../../lib/applicationPresentation';
const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8');
const css = postcss.parse(read('../../styles/global.css') + read('../../pages/Apps/RentalGrowthPage.css'));
function styles(selectors: string[], width: number, height: number) {
  const result: Record<string, string> = {};
  function visit(container: Container) {
    container.nodes?.forEach(node => {
      if (node.type === 'atrule' && node.name === 'media') {
        const match = node.params.match(/^\((max|min)-(width|height):\s*(\d+)px\)$/);
        if (!match) return;
        const size = match[2] === 'width' ? width : height;
        if (match[1] === 'max' ? size <= +match[3] : size >= +match[3]) visit(node);
      } else if (node.type === 'rule' && node.selectors.some(selector => selectors.includes(selector))) {
        node.walkDecls(declaration => { result[declaration.prop] = declaration.value; });
      }
    });
  }
  visit(css); return result;
}
it.each([[320, 640], [375, 812], [390, 844], [767, 900], [768, 900], [1440, 900], [844, 390]])('keeps rental page, calendar and forms bounded at %i x %i (static inspection)', (width, height) => {
  const page = styles(['.app-scroll-page', '.rental-page'], width, height);
  expect(page.height).toBe('100%'); expect(page['min-height']).toBe('0'); expect(page['overflow-y']).toBe('auto');
  expect(styles(['.rental-container'], width, height).padding).toContain('env(safe-area-inset-bottom)');
  expect(styles(['.rental-modal .ant-modal-body'], width, height)['overflow-y']).toBe('auto');
  expect(styles(['.rental-modal .ant-modal-content'], width, height)['max-height']).toBe(height <= 480 ? 'calc(100dvh - 16px)' : width <= 767 ? 'calc(100dvh - 24px)' : 'calc(100dvh - 48px)');
  expect(styles(['.rental-modal .ant-checkbox-wrapper'], width, height).display).toBe('inline-flex');
  expect(styles(['.rental-form-grid'], width, height)['grid-template-columns']).toBe(width <= 767 ? 'minmax(0, 1fr)' : 'repeat(2, minmax(0, 1fr))');
  expect(styles(['.rental-filters'], width, height)['grid-template-columns']).toContain('minmax(0,');
  expect(styles(['.rental-card'], width, height)['overflow-wrap']).toBe('anywhere');
  expect(styles(['.rental-actions'], width, height)['flex-wrap']).toBe('wrap');
  const messages = styles(['.rental-message-output'], width, height);
  expect(messages['overflow-y']).toBe('auto');
  expect(messages['max-height']).toBe(width <= 767 ? '40dvh' : 'min(360px, 45dvh)');
  expect(messages['overflow-wrap']).toBe('anywhere');
});
it('attaches the scroll owner inside ApplicationShell for every entry presentation', () => {
  expect(read('../../pages/Apps/RentalGrowthPage.tsx')).toContain('className="rental-page app-scroll-page"');
  expect(read('../../router/index.tsx')).toContain('<ApplicationShell fullBleed>{page(<RentalGrowthPage />)}</ApplicationShell>');
  expect(resolveApplicationPresentation(new URLSearchParams('entry=home'))).toMatchObject({ showPlatformChrome: true, showApplicationHeader: false });
  expect(resolveApplicationPresentation(new URLSearchParams('entry=apps'))).toMatchObject({ showPlatformChrome: false, showApplicationHeader: true });
  for (const query of ['standalone=1', 'embedded=1']) expect(resolveApplicationPresentation(new URLSearchParams(query))).toMatchObject({ showPlatformChrome: false, showApplicationHeader: false });
  const app = { id: 'rental-growth-assistant', applicationId: 88, kind: 'custom' as const, rendererKey: 'rental-growth-assistant' };
  expect(applicationPath(app, 'home')).toBe('/applications/88/rental-growth-assistant?entry=home');
  expect(applicationPath(app, 'apps')).toBe('/applications/88/rental-growth-assistant?entry=apps');
});
it('uses existing semantic text tokens for light and dark contrast', () => {
  const source = read('../../pages/Apps/RentalGrowthPage.css');
  expect(source).not.toContain('var(--color-text-secondary)');
  css.walkRules(rule => { if (rule.selectors.some(selector => /(?:page|modal|filters) label$/.test(selector))) expect(rule.nodes.some(node => node.type === 'decl' && node.prop === 'display' && node.value === 'grid')).toBe(false); });
  const contrast = (first: string, second: string) => {
    const luminance = (hex: string) => { const c = hex.match(/[a-f\d]{2}/gi)!.map(x => parseInt(x, 16) / 255).map(x => x <= .04045 ? x / 12.92 : ((x + .055) / 1.055) ** 2.4); return .2126 * c[0] + .7152 * c[1] + .0722 * c[2]; };
    const a = luminance(first), b = luminance(second); return (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
  };
  expect(contrast('6B7280', 'F8F9FA')).toBeGreaterThanOrEqual(4.5);
  expect(contrast('9898A8', '14141C')).toBeGreaterThanOrEqual(4.5);
});
