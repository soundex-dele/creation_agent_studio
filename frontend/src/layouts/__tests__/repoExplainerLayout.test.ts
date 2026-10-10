import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { applicationPath } from '@/lib/applicationCatalog';
const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8');
describe('repository workspace scroll and route contracts (static checks)', () => {
  it('registers a full-bleed route with a bounded page scroll owner', () => {
    const page = read('../../pages/Apps/RepoExplainerPage.tsx');
    const routes = read('../../router/index.tsx');
    const css = read('../../pages/Apps/RepoExplainerPage.css');
    expect(page).toContain('repo-page app-scroll-page');
    expect(routes).toContain('<ApplicationShell fullBleed>{page(<RepoExplainerPage />)}');
    expect(css).not.toMatch(/\.repo-page\s*\{[^}]*height:\s*(auto|100[vds]*vh)/);
    expect(css).toContain('max-width: 767px');
    expect(css).toContain('max-height: 480px');
    expect(css).toContain('grid-template-columns: minmax(0, 1fr)');
    expect(css).toContain('env(safe-area-inset-bottom)');
    expect(css).toContain('.ant-checkbox-wrapper { display: inline-flex');
    expect(css).not.toMatch(/(?:^|\})\s*(?:body|#root|\.app-main)\s*\{/);
    expect(applicationPath({ id: 'repo-explainer', applicationId: 5, kind: 'custom', rendererKey: 'repo-explainer' }, 'home')).toBe('/applications/5/repo-explainer?entry=home');
  });
  it('aligns creation controls without inheriting field bottom spacing', () => {
    const css = read('../../pages/Apps/RepoExplainerPage.css');
    const page = read('../../pages/Apps/RepoExplainerPage.tsx');
    expect(css).toMatch(/\.repo-project-controls\s*\{[^}]*align-items:\s*end/);
    expect(css).toMatch(/\.repo-project-controls\s*>\s*\.repo-field\s*\{\s*margin-bottom:\s*0;/);
    expect(css).toMatch(/\.repo-task-header\s*\{[^}]*flex-wrap:\s*wrap/);
    expect(css).toMatch(/\.repo-task-header\s*>\s*strong\s*\{[^}]*min-width:\s*0/);
    expect(page).toContain('htmlFor="repo-project-name"');
  });
  it('keeps topic cards in the page scroll owner and reflows long text at phone widths', () => {
    const css = read('../../pages/Apps/RepoExplainerPage.css');
    const global = read('../../styles/global.css');
    const page = read('../../pages/Apps/RepoExplainerPage.tsx');
    const cards = read('../../pages/Apps/repo/RepoTopicCards.tsx');
    expect(css).toMatch(/\.repo-topic-grid\s*\{[^}]*grid-template-columns:\s*repeat\(2, minmax\(0, 1fr\)\)/);
    expect(css).toMatch(/@media \(max-width: 767px\)[\s\S]*\.repo-grid, \.repo-project-controls, \.repo-topic-grid\s*\{\s*grid-template-columns:\s*minmax\(0, 1fr\)/);
    expect(css).toMatch(/\.repo-topic-card \.ant-btn\s*\{[^}]*white-space:\s*normal/);
    expect(css).toMatch(/\.repo-topic-card li, \.repo-selected-topic li\s*\{[^}]*overflow-wrap:\s*anywhere/);
    expect(global).toMatch(/\.app-scroll-page\s*\{[^}]*height:\s*100%[^}]*overflow-y:\s*auto/s);
    expect(css).not.toMatch(/\.repo-topic[^}]*overflow(?:-y)?:\s*(?:hidden|auto)/);
    expect(page).toContain('htmlFor="repo-topic-direction"');
    expect(cards).toContain('aria-pressed={selectedId === topic.id}');
    expect(cards).toContain('<ol>');
  });
});
