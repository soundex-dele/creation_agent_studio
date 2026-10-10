import { readFileSync } from 'node:fs';
import postcss from 'postcss';
import { describe, expect, it } from 'vitest';
const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8');
describe('Topic radar static layout contract (not visual verification)', () => {
  it.each([320, 375, 390, 767, 768, 1280])('keeps shrinkable columns at width %s', width => {
    const css = postcss.parse(read('../../pages/Apps/douyin/TopicRadar.css'));
    const columns: Record<string, string> = {};
    css.walkRules(rule => {
      if (rule.parent?.type === 'atrule' && rule.parent.name === 'media') {
        const max = rule.parent.params.match(/max-width:\s*(\d+)px/);
        if (max && width > Number(max[1])) return;
      }
      for (const name of ['.douyin-radar-grid', '.douyin-radar-search', '.douyin-radar-create']) {
        if (rule.selectors.includes(name)) rule.walkDecls('grid-template-columns', decl => { columns[name] = decl.value; });
      }
      rule.walkDecls('height', decl => expect(['100vh', '100dvh']).not.toContain(decl.value));
    });
    expect(columns['.douyin-radar-grid']).toBe(width <= 767 ? 'minmax(0, 1fr)' : 'repeat(2, minmax(0, 1fr))');
    for (const name of ['.douyin-radar-search', '.douyin-radar-create']) expect(columns[name]).toBe(width <= 767 ? 'minmax(0, 1fr)' : 'minmax(0, 1fr) auto');
  });
  it('inherits the existing bounded scroll owner including short landscape and embedded layouts', () => {
    expect(read('../../pages/Apps/DouyinBenchmarkPage.tsx')).toContain('douyin-host app-scroll-page');
    const css = read('../../pages/Apps/douyin/TopicRadar.css');
    expect(css).not.toMatch(/overflow(?:-y)?:\s*hidden|height:\s*(?:100vh|100dvh)/);
    expect(css).toContain('overflow-wrap: anywhere');
    expect(css).toContain('.douyin-radar .ant-checkbox-wrapper { display: inline-flex; align-items: center;');
    expect(css).toContain('min-height: 44px');
    expect(css).not.toMatch(/(?:^|\})\s*(?:body|#root|\.app-main)\s*\{/);
  });
});
