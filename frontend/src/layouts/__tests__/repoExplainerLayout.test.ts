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
});
