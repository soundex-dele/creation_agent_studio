import { readFileSync } from 'node:fs';
import postcss, { type Container } from 'postcss';
import { expect, it } from 'vitest';
import { applicationPath } from '../../lib/applicationCatalog';
import { resolveApplicationPresentation } from '../../lib/applicationPresentation';
const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8');
const css = postcss.parse(read('../../styles/global.css') + read('../../pages/Apps/ProjectPromotionPage.css'));
function styles(selectors: string[], width: number, height: number) {
  const result: Record<string, string> = {};
  function visit(container: Container) {
    container.nodes?.forEach(node => {
      if (node.type === 'atrule' && node.name === 'media') {
        const m = node.params.match(/^\((max|min)-(width|height):\s*(\d+)px\)$/); if (!m) return;
        const size = m[2] === 'width' ? width : height;
        if (m[1] === 'max' ? size <= +m[3] : size >= +m[3]) visit(node);
      } else if (node.type === 'rule' && node.selectors.some(s => selectors.includes(s))) {
        node.walkDecls(d => { result[d.prop] = d.value; });
      }
    });
  }
  visit(css); return result;
}
it.each([[320, 640], [375, 812], [390, 844], [767, 900], [768, 900], [1440, 900], [844, 390]])('bounds the page, cards and forms at %i x %i (static CSS check)', (width, height) => {
  const page = styles(['.app-scroll-page', '.promotion-page'], width, height);
  expect(page.height).toBe('100%'); expect(page['min-height']).toBe('0'); expect(page['overflow-y']).toBe('auto');
  expect(styles(['.promotion-source'], width, height)['min-width']).toBe('0');
  expect(styles(['.promotion-source'], width, height)['overflow-wrap']).toBe('anywhere');
  expect(styles(['.promotion-source pre'], width, height)['white-space']).toBe('pre-wrap');
  expect(styles(['.promotion-container'], width, height).padding).toContain('env(safe-area-inset-bottom)');
  expect(styles(['.promotion-grid'], width, height)['grid-template-columns']).toBe(width <= 767 ? 'minmax(0, 1fr)' : width <= 1023 ? 'repeat(2, minmax(0, 1fr))' : 'repeat(3, minmax(0, 1fr))');
  expect(styles(['.promotion-modal .ant-modal-body'], width, height)['overflow-y']).toBe('auto');
  expect(styles(['.promotion-modal .ant-modal-body'], width, height)['min-height']).toBe('0');
  expect(styles(['.promotion-modal .ant-modal-content'], width, height)['max-height']).toBe(height <= 480 ? 'calc(100dvh - 16px)' : width <= 767 ? 'calc(100dvh - 24px)' : 'calc(100dvh - 48px)');
  expect(styles(['.promotion-modal .ant-checkbox-wrapper'], width, height).display).toBe('inline-flex');
  expect(styles(['.promotion-card'], width, height)['overflow-wrap']).toBe('anywhere');
  expect(styles(['.promotion-actions'], width, height)['flex-wrap']).toBe('wrap');
});
it('registers a full-bleed route with a page-owned scroll container in all entry modes', () => {
  expect(read('../../pages/Apps/ProjectPromotionPage.tsx')).toContain('className="promotion-page app-scroll-page"');
  expect(read('../../router/index.tsx')).toContain('<ApplicationShell fullBleed>{page(<ProjectPromotionPage />)}</ApplicationShell>');
  expect(resolveApplicationPresentation(new URLSearchParams('entry=home')).showPlatformChrome).toBe(true);
  for (const entry of ['entry=apps', 'standalone=1', 'embedded=1']) expect(resolveApplicationPresentation(new URLSearchParams(entry)).showPlatformChrome).toBe(false);
  const app = { id: 'project-promotion', applicationId: 88, kind: 'custom' as const, rendererKey: 'project-promotion' };
  for (const entry of ['home', 'apps'] as const) expect(applicationPath(app, entry)).toBe(`/applications/88/project-promotion?entry=${entry}`);
});
