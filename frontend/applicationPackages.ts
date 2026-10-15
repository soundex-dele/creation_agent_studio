import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { parse } from 'yaml';
import type { Plugin } from 'vite';

const frontendRoot = path.dirname(fileURLToPath(import.meta.url));
const appRoot = path.resolve(frontendRoot, '../app_center');
const moduleId = 'virtual:application-packages';

export function discoverApplicationFrontends(root = appRoot) {
  const entries: { id: string; rendererKey: string; entrypoint: string }[] = [];
  const keys = new Set<string>();
  for (const directory of fs.readdirSync(root).sort()) {
    const manifestPath = path.join(root, directory, 'application.yaml');
    if (!fs.existsSync(manifestPath)) continue;
    const manifest = parse(fs.readFileSync(manifestPath, 'utf8'));
    for (const frontend of manifest.spec?.frontends ?? []) {
      if (frontend.type !== 'react' || !frontend.entrypoint) continue;
      const packageRoot = fs.realpathSync(path.dirname(manifestPath));
      const entrypoint = fs.realpathSync(path.resolve(packageRoot, frontend.entrypoint));
      if (!entrypoint.startsWith(packageRoot + path.sep)) throw new Error(`Frontend escapes package: ${manifestPath}`);
      if (!frontend.renderer_key || keys.has(frontend.renderer_key)) throw new Error(`Duplicate or missing renderer: ${manifestPath}`);
      keys.add(frontend.renderer_key);
      entries.push({ id: manifest.metadata.id, rendererKey: frontend.renderer_key, entrypoint });
    }
  }
  return entries;
}

/** All environments compile the same trusted, local manifest entrypoints. */
export function applicationPackages(): Plugin {
  return {
    name: 'application-packages',
    resolveId(id) { if (id === moduleId) return '\0' + moduleId; },
    load(id) {
      if (id !== '\0' + moduleId) return;
      const entries = discoverApplicationFrontends();
      const imports = entries.map((entry, i) => `import app${i} from ${JSON.stringify(entry.entrypoint.replace(/\\/g, '/'))};`);
      const checks = entries.map((entry, i) => `if (app${i}.rendererKey !== ${JSON.stringify(entry.rendererKey)}) throw new Error(${JSON.stringify(`Manifest renderer mismatch: ${entry.id}`)});`);
      return [...imports, ...checks, `export default [${entries.map((_, i) => `app${i}`).join(',')}];`].join('\n');
    },
  };
}

const dependencies = JSON.parse(fs.readFileSync(path.join(frontendRoot, 'package.json'), 'utf8')).dependencies;
export const applicationAliases = {
  ...Object.fromEntries(Object.keys(dependencies).map(name => [name, path.join(frontendRoot, 'node_modules', name)])),
  '@platform': path.join(frontendRoot, 'src/platform'),
  '@applications': appRoot,
  'vitest': path.join(frontendRoot, 'node_modules/vitest'),
  'postcss': path.join(frontendRoot, 'node_modules/postcss'),
};
