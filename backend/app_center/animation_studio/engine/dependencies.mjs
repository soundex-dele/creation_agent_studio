import fs from 'node:fs/promises';
import path from 'node:path';

const browserPackages = ['react', 'react-dom', 'remotion', '@remotion/player'];

// nodePaths is only a fallback in esbuild. A task below another node_modules
// directory must not inherit that directory's React or renderer (or JSX runtime).
export async function engineDependencies(engine) {
  const manifest = JSON.parse(await fs.readFile(path.join(engine, 'package.json'), 'utf8'));
  const modules = path.join(engine, 'node_modules');
  const aliases = {};
  for (const name of browserPackages) {
    const directory = path.join(modules, name);
    const expected = manifest.dependencies[name];
    let installed;
    try {
      installed = JSON.parse(await fs.readFile(path.join(directory, 'package.json'), 'utf8')).version;
    } catch { /* Report missing and incomplete installs as environment errors. */ }
    if (!expected || installed !== expected) {
      throw Object.assign(new Error(`动画引擎依赖 ${name} 版本不匹配（需要 ${expected || '锁定版本'}，实际 ${installed || '未安装'}）。请在动画引擎目录执行 npm ci 后重试。`), {
        code: 'engine_dependency_error', retryable: false,
      });
    }
    aliases[name] = directory;
  }
  return {modules, aliases};
}

export function engineWebpackOverride(configuration, dependencies) {
  return {
    ...configuration,
    resolve: {
      ...configuration.resolve,
      alias: {...configuration.resolve?.alias, ...dependencies.aliases},
      modules: [dependencies.modules, 'node_modules'],
    },
  };
}
