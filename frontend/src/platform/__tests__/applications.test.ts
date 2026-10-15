import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';
import applications from 'virtual:application-packages';
import { discoverApplicationFrontends } from '../../../applicationPackages';

const temporary: string[] = [];
afterEach(() => temporary.splice(0).forEach(directory => rmSync(directory, { recursive: true, force: true })));

describe('manifest application host', () => {
  it('keeps existing launch URLs and full-bleed routing without platform app branches', () => {
    for (const key of [
      'ai-drawing', 'animation-studio', 'brand-library', 'creation-master', 'creation-toolbox',
      'disk-cleaner', 'documents', 'douyin-benchmark', 'ideas-todos', 'kitchen-assistant',
      'meeting-assistant', 'my-drive', 'project-promotion', 'prompt-master',
      'rental-growth-assistant', 'repo-explainer', 'research-assistant', 'sokoban',
      'study-with-method', 'wechat-assistant',
    ]) {
      const application = applications.find(item => item.rendererKey === key)!;
      expect(application.launch({ applicationId: 17 }, 'home')).toBe(`/applications/17/${key}?entry=home`);
      expect(application.routes[0]).toMatchObject({ path: `/applications/:applicationId/${key}`, fullBleed: true });
    }
    const routes = applications.flatMap(application => application.routes.map(route => route.path));
    expect(new Set(routes).size).toBe(routes.length);
  });

  it('preserves legacy entrypoints and task renderer registration', () => {
    const get = (key: string) => applications.find(app => app.rendererKey === key)!;
    expect(get('cowork').launch({ applicationId: 17 }, 'home')).toBe('/chat?entry=home');
    expect(get('cowork').routes[0]).toMatchObject({ path: '/apps/cowork', shell: 'none' });
    expect(get('my-computer').routes).toHaveLength(6);
    expect(get('my-computer').routes.every(route => route.shell === 'main' && route.hideSidebar && route.fullBleed)).toBe(true);
    expect(get('case-library').routes.map(route => route.path)).toEqual(['/templates', '/templates/:id', '/apps/case-library', '/apps/case-library/:id']);
    expect(get('case-library').routes.every(route => !route.fullBleed)).toBe(true);
    expect(get('pocket-salvager').routes.map(route => route.path)).toEqual(['/apps/pocket-salvager', '/applications/:applicationId/pocket-salvager']);
    expect(get('html-to-png').taskView).toBeDefined();
    expect(get('html-to-png').launch({ applicationId: 17 }, 'apps')).toBe('/applications/17/run?entry=apps');
  });

  it.each(['duplicate', 'missing', 'escape'])('rejects %s frontend registration before bundling', failure => {
    const root = mkdtempSync(path.join(tmpdir(), 'application-registry-'));
    temporary.push(root);
    writeFileSync(path.join(root, 'outside.ts'), 'export default {};');
    for (const name of ['first', 'second']) {
      const directory = path.join(root, name);
      mkdirSync(directory);
      writeFileSync(path.join(directory, 'index.ts'), 'export default {};');
      const entrypoint = name === 'second' && failure === 'missing' ? 'missing.ts' : failure === 'escape' ? '../outside.ts' : 'index.ts';
      writeFileSync(path.join(directory, 'application.yaml'), JSON.stringify({
        metadata: { id: name }, spec: { frontends: [{ type: 'react', renderer_key: 'duplicate', entrypoint }] },
      }));
    }
    expect(() => discoverApplicationFrontends(root)).toThrow();
  });
});
