import { readFileSync } from 'node:fs';
import { expect, it } from 'vitest';
import postcss, { type Container } from 'postcss';
import applications from 'virtual:application-packages';
import { applicationPath } from '../../lib/applicationCatalog';
import { resolveApplicationPresentation } from '../../lib/applicationPresentation';
const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8');
const css = postcss.parse(read('../../styles/global.css') + read('../../../../app_center/song_curator/frontend/pages/SongCuratorPage.css'));
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
it.each([[320, 640], [375, 812], [390, 844], [767, 900], [768, 900], [1440, 900], [844, 390]])('bounds song page and forms at %i x %i (static CSS inspection)', (width, height) => {
  const page = styles(['.app-scroll-page', '.song-page'], width, height);
  expect(page.height).toBe('100%'); expect(page['min-height']).toBe('0'); expect(page['overflow-y']).toBe('auto');
  expect(styles(['.song-container'], width, height).padding).toContain('env(safe-area-inset-bottom)');
  expect(styles(['.song-filters'], width, height)['grid-template-columns']).toBe(width <= 767 ? 'minmax(0, 1fr)' : 'repeat(3, minmax(0, 1fr))');
  expect(styles(['.song-review-grid'], width, height)['grid-template-columns']).toBe(width <= 767 ? 'minmax(0, 1fr)' : 'minmax(0, 1fr) minmax(0, 2fr)');
  expect(styles(['.song-page .ant-checkbox-wrapper'], width, height).display).toBe('inline-flex');
  expect(styles(['.song-track'], width, height)['overflow-wrap']).toBe('anywhere');
  expect(styles(['.song-actions'], width, height)['flex-wrap']).toBe('wrap');
  expect(styles(['.song-modal .ant-modal-body'], width, height)['overflow-y']).toBe('auto');
  expect(styles(['.song-modal .ant-modal-content'], width, height)['max-height']).toBe(height <= 480 ? 'calc(100dvh - 16px)' : width <= 767 ? 'calc(100dvh - 24px)' : 'calc(100dvh - 48px)');
});
it('registers page scrolling through ApplicationShell for all presentation modes', () => {
  expect(read('../../../../app_center/song_curator/frontend/pages/SongCuratorPage.tsx')).toContain('className="song-page app-scroll-page"');
  expect(applications.find(app => app.rendererKey === 'song-curator')?.routes[0].fullBleed).toBe(true);
  expect(resolveApplicationPresentation(new URLSearchParams('entry=home')).showPlatformChrome).toBe(true);
  expect(resolveApplicationPresentation(new URLSearchParams('entry=apps')).showApplicationHeader).toBe(true);
  for (const query of ['standalone=1', 'embedded=1']) expect(resolveApplicationPresentation(new URLSearchParams(query)).showApplicationHeader).toBe(false);
  expect(applicationPath({ id: 'song-curator', applicationId: 42, kind: 'custom', rendererKey: 'song-curator' }, 'apps')).toBe('/applications/42/song-curator?entry=apps');
});
