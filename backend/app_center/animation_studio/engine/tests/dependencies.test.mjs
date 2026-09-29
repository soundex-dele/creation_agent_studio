import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {engineDependencies} from '../dependencies.mjs';

const engine = fileURLToPath(new URL('..', import.meta.url));

for (const brokenPackage of ['react', 'react-dom', 'remotion', '@remotion/player']) {
  test(`a mismatched ${brokenPackage} install is not sent back to AI for scene repair`, async()=>{
    const root = await fs.mkdtemp(path.join(os.tmpdir(), 'animation-dependency-test-'));
    try {
      const manifest = JSON.parse(await fs.readFile(path.join(engine, 'package.json'), 'utf8'));
      await fs.writeFile(path.join(root, 'package.json'), JSON.stringify(manifest));
      for (const name of ['react', 'react-dom', 'remotion', '@remotion/player']) {
        const pkg = path.join(root, 'node_modules', name);
        await fs.mkdir(pkg, {recursive:true});
        await fs.writeFile(path.join(pkg, 'package.json'), JSON.stringify({version:name === brokenPackage ? '0.0.0' : manifest.dependencies[name]}));
      }
      await assert.rejects(engineDependencies(root), error => {
        assert.equal(error.code, 'engine_dependency_error');
        assert.equal(error.retryable, false);
        assert.ok(error.message.includes(brokenPackage));
        assert.match(error.message, /npm ci/);
        return true;
      });
    } finally {await fs.rm(root, {recursive:true,force:true});}
  });
}

test('missing local dependencies do not silently fall back to ancestor installations', async()=>{
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'animation-dependency-test-'));
  try {
    await fs.copyFile(path.join(engine, 'package.json'), path.join(root, 'package.json'));
    await assert.rejects(engineDependencies(root), error => error.code === 'engine_dependency_error' && error.retryable === false);
  } finally {await fs.rm(root, {recursive:true,force:true});}
});
