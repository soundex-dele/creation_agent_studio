import { readFileSync } from 'node:fs';
import postcss from 'postcss';
import { describe, expect, it } from 'vitest';
import { resolveApplicationPresentation } from '@/lib/applicationPresentation';
const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8');
describe('Douyin document workspace layout contract', () => {
  it('bounds generation previews inside the existing page scroll owner', () => {
    const source = read('../../pages/Apps/douyin/GenerationPreview.css');
    expect(source).toContain('max-height: min(24rem, 45dvh)');
    expect(source).toContain('overflow-y: auto');
    expect(source).toContain('overflow-wrap: anywhere');
    expect(source).toContain('white-space: pre-wrap');
    expect(source).toContain('min-width: 0');
    expect(source).not.toMatch(/height:\s*(100vh|100dvh|auto)/);
    expect(read('../../pages/Apps/DouyinBenchmarkPage.tsx')).toContain('douyin-host app-scroll-page');
  });
  it.each([320, 375, 390, 767, 768, 1280])('keeps owned-account content in the page scroll container at %spx', width => {
    const css = postcss.parse(read('../../pages/Apps/douyin/OwnedAccounts.css'));
    let columns = '';
    css.walkRules(rule => {
      if (rule.parent?.type === 'atrule' && rule.parent.name === 'media') {
        const max = rule.parent.params.match(/max-width:\s*(\d+)px/);
        if (max && width > Number(max[1])) return;
      }
      if (rule.selectors.includes('.douyin-owned-grid')) rule.walkDecls('grid-template-columns', decl => { columns = decl.value; });
      rule.walkDecls('height', decl => { expect(['100vh', '100dvh']).not.toContain(decl.value); });
    });
    expect(columns).toBe(width <= 767 ? 'minmax(0, 1fr)' : 'repeat(2, minmax(0, 1fr))');
    expect(read('../../pages/Apps/DouyinBenchmarkPage.tsx')).toContain('douyin-host app-scroll-page');
    expect(read('../../pages/Apps/DouyinBenchmarkPage.tsx')).toContain("view === 'owned' ? <OwnedAccounts");
  });
  it('bounds the owned sample editor at short viewport heights', () => {
    const source = read('../../pages/Apps/douyin/OwnedAccounts.css');
    expect(source).toContain('max-height: 65dvh; overflow-y: auto;');
    expect(source).toContain('@media (max-height: 500px)');
    expect(source).toContain('max-height: 50dvh;');
  });
  it('lets the account report action wrap without changing the document scroll owner', () => {
    const source = read('../../pages/Apps/DouyinBenchmarkPage.css');
    expect(source).toContain('.douyin-task > .douyin-section-title { flex-wrap: wrap; }');
    expect(source).toContain('.douyin-analysis-export { display: flex; flex-wrap: wrap;');
    expect(source).toContain('.douyin-analysis-export .ant-btn { min-height: 44px; }');
    expect(read('../../pages/Apps/DouyinBenchmarkPage.tsx')).toContain('douyin-host app-scroll-page');
  });
  it.each([320, 375, 390, 767, 768, 1280])('reflows research columns at %spx without changing scroll ownership', width => {
    const css = postcss.parse(read('../../pages/Apps/douyin/ResearchHub.css'));
    const columns: Record<string, string> = {};
    const names = ['.douyin-research-filters', '.douyin-idea-board', '.douyin-research-metrics'];
    css.walkRules(rule => {
      if (rule.parent?.type === 'atrule' && rule.parent.name === 'media') {
        const max = rule.parent.params.match(/max-width:\s*(\d+)px/);
        if (max && width > Number(max[1])) return;
      }
      for (const name of names) if (rule.selectors.includes(name)) rule.walkDecls('grid-template-columns', decl => { columns[name] = decl.value; });
    });
    expect(columns['.douyin-research-filters']).toBe(width <= 767 ? 'minmax(0, 1fr)' : 'repeat(3, minmax(0, 1fr))');
    expect(columns['.douyin-idea-board']).toBe(width <= 767 ? 'minmax(0, 1fr)' : width <= 1100 ? 'repeat(2, minmax(0, 1fr))' : 'repeat(4, minmax(0, 1fr))');
    expect(columns['.douyin-research-metrics']).toBe(width <= 767 ? 'repeat(2, minmax(0, 1fr))' : 'repeat(4, minmax(0, 1fr))');
  });
  it('uses text and chart tokens with sufficient light and dark card contrast', () => {
    const variables = postcss.parse(read('../../styles/variables.css'));
    const luminance = (hex: string) => {
      const channels = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255).map(v => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4);
      return channels[0] * .2126 + channels[1] * .7152 + channels[2] * .0722;
    };
    let themes = 0;
    variables.walkRules(rule => {
      const tokens: Record<string, string> = {};
      rule.walkDecls(decl => { tokens[decl.prop] = decl.value; });
      if (!tokens['--color-bg-card'] || !tokens['--color-text-sec']) return;
      const ratio = (a: string, b: string) => (Math.max(luminance(a), luminance(b)) + .05) / (Math.min(luminance(a), luminance(b)) + .05);
      for (const surface of ['--color-bg-card', '--color-bg-surface']) {
        expect(ratio(tokens['--color-text'], tokens[surface])).toBeGreaterThanOrEqual(4.5);
        expect(ratio(tokens['--color-text-sec'], tokens[surface])).toBeGreaterThanOrEqual(4.5);
      }
      expect(ratio(tokens['--color-primary'], tokens['--color-bg-card'])).toBeGreaterThanOrEqual(3);
      themes++;
    });
    expect(themes).toBe(2);
  });
  it('keeps research filters, board and metric cards shrinkable and responsive', () => {
    const source = read('../../pages/Apps/douyin/ResearchHub.css');
    const css = postcss.parse(source);
    expect(source).toContain('grid-template-columns: repeat(3, minmax(0, 1fr))');
    expect(source).toContain('.douyin-research-card .ant-checkbox-wrapper { display: inline-flex; align-items: center');
    expect(source).toContain('.douyin-research-field');
    expect(source).not.toMatch(/\.douyin-research-hub\s+label\s*\{/);
    expect(source).toContain('var(--color-bg-card)');
    css.walkRules(rule => {
      if (rule.selector.includes('.douyin-research-hub')) rule.walkDecls('height', decl => expect(decl.value).not.toMatch(/vh/));
    });
    expect(source).toContain('@media (max-width: 767px)');
    expect(source).toContain('.douyin-research-filters, .douyin-research-grid, .douyin-comparison-grid, .douyin-idea-board { grid-template-columns: minmax(0, 1fr); }');
    expect(source).toContain('min-height: 44px');
    expect(read('../../pages/Apps/DouyinBenchmarkPage.tsx')).toContain('douyin-host app-scroll-page');
  });
  it.each([320, 375, 390, 767, 768, 1280])('keeps replication text columns within the scroll page at %spx', width => {
    const css = postcss.parse(read('../../pages/Apps/DouyinBenchmarkPage.css'));
    let columns = '';
    css.walkRules(rule => {
      if (!rule.selectors.includes('.douyin-rewrite-columns')) return;
      const parent = rule.parent;
      if (parent?.type === 'atrule' && parent.name === 'media') {
        const max = parent.params.match(/max-width:\s*(\d+)px/);
        if (max && width > Number(max[1])) return;
      }
      rule.walkDecls('grid-template-columns', decl => { columns = decl.value; });
      rule.walkDecls('height', decl => { expect(decl.value).not.toMatch(/vh|auto/); });
    });
    expect(columns).toBe(width <= 767 ? 'minmax(0, 1fr)' : 'repeat(2, minmax(0, 1fr))');
    const panel = read('../../pages/Apps/douyin/RewritePanel.tsx');
    expect(panel).toContain('douyin-rewrite-columns');
    expect(panel).toContain('aria-label="口播原文"');
    expect(panel).toContain('aria-label="改写正文"');
    expect(read('../../pages/Apps/DouyinBenchmarkPage.tsx')).toContain('douyin-host app-scroll-page');
  });
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
