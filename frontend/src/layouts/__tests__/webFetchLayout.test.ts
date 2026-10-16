import applications from 'virtual:application-packages';
import { readFileSync } from 'node:fs';
import postcss, { type Container } from 'postcss';
import { expect, it } from 'vitest';
import { applicationPath } from '../../lib/applicationCatalog';
import { resolveApplicationPresentation } from '../../lib/applicationPresentation';
const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8');
const source = read('../../../../app_center/web_fetch/frontend/pages/WebFetchPage.css');
const css = postcss.parse(read('../../styles/global.css') + source);
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
it.each([[320, 640], [375, 812], [390, 844], [767, 900], [768, 900], [1440, 900], [844, 390]])('preserves bounded scroll and content at %i x %i (static CSS check)', (width, height) => {
  const page = styles(['.app-scroll-page', '.web-fetch-page'], width, height);
  expect(page.height).toBe('100%'); expect(page['min-height']).toBe('0'); expect(page['overflow-y']).toBe('auto');
  expect(styles(['.web-fetch-container'], width, height).padding).toContain('env(safe-area-inset-bottom)');
  expect(styles(['.web-fetch-input-row'], width, height)['grid-template-columns']).toBe(width <= 767 ? 'minmax(0, 1fr)' : 'minmax(0, 1fr) auto');
  expect(styles(['.web-fetch-card'], width, height)['overflow-wrap']).toBe('anywhere');
  expect(styles(['.web-fetch-code'], width, height)['overflow-x']).toBe('auto');
  expect(styles(['.web-fetch-table'], width, height)['overflow-x']).toBe('auto');
  expect(styles(['.web-fetch-actions'], width, height)['flex-wrap']).toBe('wrap');
  expect(styles(['.web-fetch-card .ant-btn'], width, height)['min-height']).toBe('44px');
});
it('registers every entry through the shell with the page as scroll owner', () => {
  const page = read('../../../../app_center/web_fetch/frontend/pages/WebFetchPage.tsx');
  expect(page).toContain('className="web-fetch-page app-scroll-page"');
  expect(applications.find(app => app.rendererKey === 'web-fetch')?.routes[0].fullBleed).toBe(true);
  expect(resolveApplicationPresentation(new URLSearchParams('entry=home'))).toMatchObject({ showPlatformChrome: true });
  expect(resolveApplicationPresentation(new URLSearchParams('entry=apps'))).toMatchObject({ showApplicationHeader: true });
  for (const query of ['standalone=1', 'embedded=1']) expect(resolveApplicationPresentation(new URLSearchParams(query))).toMatchObject({ showPlatformChrome: false, showApplicationHeader: false });
  const app = { id: 'web-fetch', applicationId: 88, kind: 'custom' as const, rendererKey: 'web-fetch' };
  expect(applicationPath(app, 'home')).toBe('/applications/88/web-fetch?entry=home');
  expect(applicationPath(app, 'apps')).toBe('/applications/88/web-fetch?entry=apps');
  expect(source).not.toMatch(/(?:^|\})\s*(body|#root|\.app-main)\s*\{/);
  expect(source).not.toMatch(/height:\s*(auto|100[vds]*vh)/);
});
it('uses defined semantic tokens in both themes', () => {
  const variables = read('../../styles/variables.css');
  for (const token of source.matchAll(/var\((--[\w-]+)\)/g)) expect(variables).toContain(`${token[1]}:`);
  const luminance = (hex: string) => {
    const rgb = hex.match(/[a-f\d]{2}/gi)!.map(value => parseInt(value, 16) / 255).map(value => value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4);
    return .2126 * rgb[0] + .7152 * rgb[1] + .0722 * rgb[2];
  };
  for (const [text, background] of [['6B7280', 'F8F9FA'], ['9898A8', '14141C'], ['FFFFFF', 'B45309'], ['241700', 'F0C060']]) {
    const a = luminance(text), b = luminance(background);
    expect((Math.max(a, b) + .05) / (Math.min(a, b) + .05)).toBeGreaterThanOrEqual(4.5);
  }
});
