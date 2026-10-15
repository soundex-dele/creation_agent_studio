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
    for (const key of ['kitchen-assistant', 'douyin-benchmark']) {
      const application = applications.find(item => item.rendererKey === key)!;
      expect(application.launch({ applicationId: 17 }, 'home')).toBe(`/applications/17/${key}?entry=home`);
      expect(application.routes[0]).toMatchObject({ path: `/applications/:applicationId/${key}`, fullBleed: true });
    }
    const routes = applications.flatMap(application => application.routes.map(route => route.path));
    expect(new Set(routes).size).toBe(routes.length);
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
