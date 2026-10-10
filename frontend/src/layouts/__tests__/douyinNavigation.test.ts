import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { douyinLocation, primarySection } from '../../pages/Apps/douyin/navigation';
import { douyinSections } from '../../pages/Apps/douyin/DouyinNavigation';
const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8');

describe('Creator-first navigation and scroll contract', () => {
  it('has five primary destinations and groups legacy views without deleting capabilities', () => {
    expect(douyinSections.map(s => s.label)).toEqual(['我的账号', '发现与研究', '选题库', '创作中心', '素材库']);
    for (const view of ['accounts', 'research', 'radar', '']) expect(primarySection(view)).toBe('accounts');
    for (const view of ['owned', 'review', 'profiles']) expect(primarySection(view)).toBe('owned');
    for (const view of ['materials', 'inspirations', 'knowledge']) expect(primarySection(view)).toBe('materials');
  });
  it.each(['entry=home', 'entry=apps', 'standalone=1', 'embedded=1'])('preserves %s and creator selection but clears stale sources', presentation => {
    const params = new URLSearchParams(`${presentation}&view=research&owned=a1&task=t1&account=ref1&source=s1&work=w1&idea=i1&mode=rewrite`);
    const next = douyinLocation(params, 'create', { idea: 'i2' });
    expect(next.toString()).toContain(presentation);
    expect(next.get('owned')).toBe('a1'); expect(next.get('idea')).toBe('i2');
    for (const key of ['task', 'account', 'source', 'work', 'mode']) expect(next.has(key)).toBe(false);
    expect(params.get('task')).toBe('t1');
  });
  it('keeps section navigation inside the existing full-height scroll owner', () => {
    const page = read('../../pages/Apps/DouyinBenchmarkPage.tsx');
    expect(page).toContain('douyin-host app-scroll-page');
    expect(page.match(/className="douyin-section-tabs"/g)).toHaveLength(3);
    const css = read('../../pages/Apps/DouyinBenchmarkPage.css');
    expect(css).toContain('.douyin-section-tabs { width: 100%; min-width: 0; }');
    expect(css).toContain('.douyin-section-tabs .ant-tabs-tab { min-height: 44px; }');
    expect(css).toContain('grid-template-rows: auto minmax(0, 1fr)');
    expect(css).toContain('env(safe-area-inset-bottom)');
    expect(read('../../router/index.tsx')).toContain('<ApplicationShell fullBleed>{page(<DouyinBenchmarkPage />)}</ApplicationShell>');
  });
});
