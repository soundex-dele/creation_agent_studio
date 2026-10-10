import { readFileSync } from 'node:fs';
import postcss, { type Container } from 'postcss';
import { expect, it } from 'vitest';
import { applicationPath } from '@/lib/applicationCatalog';
import { resolveApplicationPresentation } from '@/lib/applicationPresentation';

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8');
const css = postcss.parse(read('../../styles/global.css') + read('../../pages/Apps/DiskCleanerPage.css'));
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

it.each([[320, 640], [375, 812], [390, 844], [767, 900], [768, 900], [1440, 900], [844, 390]])(
  'preserves the bounded page scroll owner and responsive controls at %i × %i (static CSS)', (width, height) => {
    const page = styles(['.app-scroll-page', '.disk-cleaner-page'], width, height);
    expect(page.height).toBe('100%'); expect(page['min-height']).toBe('0'); expect(page['overflow-y']).toBe('auto');
    expect(page.padding).toContain('safe-area-inset-bottom');
    expect(styles(['.disk-cleaner-filters'], width, height)['grid-template-columns']).toBe(width < 768 ? 'minmax(0, 1fr)' : 'minmax(0, 1fr) auto auto');
    expect(styles(['.disk-cleaner-entry .ant-checkbox-wrapper'], width, height).display).toBe('inline-flex');
    expect(styles(['.disk-cleaner-entry-info'], width, height)['min-width']).toBe('0');
    expect(styles(['.disk-cleaner-entry-info'], width, height)['overflow-wrap']).toBe('anywhere');
    const modal = styles(['.disk-cleaner-modal .ant-modal-body'], width, height);
    expect(modal['overflow-y']).toBe('auto'); expect(modal['max-height']).toBe(height <= 500 ? '45dvh' : '60dvh');
    if (width < 768) expect(styles(['.disk-cleaner-entry-size'], width, height).width).toBe('100%');
  },
);

it.each(['entry=home', 'entry=apps', 'standalone=1', 'embedded=1'])('attaches the full-bleed page for %s', query => {
  expect(read('../../router/index.tsx')).toContain('<ApplicationShell fullBleed>{page(<DiskCleanerPage />)}</ApplicationShell>');
  const page = read('../../pages/Apps/DiskCleanerPage.tsx');
  expect(page).toContain('className="disk-cleaner-page app-scroll-page"');
  expect(page).toContain('resolveApplicationPresentation(params).showApplicationHeader');
  const presentation = resolveApplicationPresentation(new URLSearchParams(query));
  expect(presentation.showApplicationHeader).toBe(query === 'entry=apps');
  expect(presentation.showPlatformChrome).toBe(query === 'entry=home');
  expect(presentation.embedded).toBe(query === 'embedded=1');
  expect(applicationPath({ id: 'disk-cleaner', applicationId: 12, kind: 'custom', rendererKey: 'disk-cleaner' }, query === 'entry=home' ? 'home' : 'apps')).toBe(`/applications/12/disk-cleaner?entry=${query === 'entry=home' ? 'home' : 'apps'}`);
});

it('uses readable light/dark secondary text and contrasting primary button colors', () => {
  const theme = postcss.parse(read('../../styles/variables.css'));
  const luminance = (hex: string) => {
    const rgb = [1, 3, 5].map(index => parseInt(hex.slice(index, index + 2), 16) / 255).map(value => value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4);
    return rgb[0] * .2126 + rgb[1] * .7152 + rgb[2] * .0722;
  };
  const contrast = (a: string, b: string) => (Math.max(luminance(a), luminance(b)) + .05) / (Math.min(luminance(a), luminance(b)) + .05);
  for (const selector of [':root', '.dark']) {
    const vars: Record<string, string> = {};
    theme.walkRules(selector, rule => { rule.walkDecls(declaration => { vars[declaration.prop] = declaration.value; }); });
    for (const bg of ['--color-bg-card', '--color-bg-surface']) expect(contrast(vars['--color-text-sec'], vars[bg])).toBeGreaterThanOrEqual(4.5);
    expect(contrast(vars['--color-on-primary'], vars['--color-primary-hover'])).toBeGreaterThanOrEqual(4.5);
  }
});
