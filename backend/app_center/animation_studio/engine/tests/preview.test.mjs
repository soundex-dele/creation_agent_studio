import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {openBrowser} from '@remotion/renderer';
import {verifyPreview} from '../preview.mjs';

const engine = fileURLToPath(new URL('..', import.meta.url));
const execute = promisify(execFile);
const config = {schema_version:2,width:1280,height:720,fps:30,durationInFrames:150};

async function preview(source) {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'animation-preview-test-'));
  const dir = path.join(root, 'project');
  try {
    await fs.mkdir(dir);
    await fs.writeFile(path.join(dir, 'composition.json'), JSON.stringify(config));
    await fs.writeFile(path.join(dir, 'assets.json'), '[]');
    await fs.writeFile(path.join(dir, 'project.json'), JSON.stringify({schema_version:2,
      scenes:[{id:'one',title:'动画',frames:150,source}], audio:[],subtitles:[],subtitle_style:{enabled:false},brand:{}}));
    try {
      const result = await execute(process.execPath, [path.join(engine, 'runner.mjs'), 'preview', dir], {cwd:engine,timeout:90000});
      return {success:true,stdout:result.stdout,html:await fs.readFile(path.join(dir,'out/preview.html'),'utf8')};
    } catch (error) {
      const line = error.stderr?.split('\n').find(item => item.startsWith('ANIMATION_BUILD_ERROR '));
      assert.ok(line, error.stderr || error.message);
      return {success:false,...JSON.parse(line.slice('ANIMATION_BUILD_ERROR '.length))};
    }
  } finally {await fs.rm(root,{recursive:true,force:true});}
}

test('real isolated preview plays and keeps CSP with diagnostic bootstrap', {timeout:120000}, async()=>{
  const result = await preview(`import {useCurrentFrame} from 'remotion';export default ({scene})=><div>{scene.title} {useCurrentFrame()}</div>`);
  assert.equal(result.success, true, JSON.stringify(result));
  assert.match(result.stdout, /preview_ready/);
  assert.match(result.html, /script-src 'sha256-/);
  assert.doesNotMatch(result.html, /script-src[^;]*unsafe-inline/);
});

for (const [name, source, message] of [
  ['module initialization', `const value=missingSceneValue;export default ()=>null`, /missingSceneValue is not defined/],
  ['first render', `export default ()=>{throw new Error('场景数据缺少 title')}`, /场景数据缺少 title/],
  ['later frame', `import {useCurrentFrame} from 'remotion';export default ()=>{if(useCurrentFrame()>=75)throw new Error('中间帧数据错误');return <div>正常</div>}`, /中间帧数据错误/],
]) test(`reports the actual ${name} failure to the repair loop`, {timeout:120000}, async()=>{
  const result = await preview(source);
  assert.equal(result.success, false);
  assert.equal(result.retryable, true);
  assert.equal(result.code, 'preview_runtime_error');
  assert.match(result.message, message);
  assert.doesNotMatch(result.message, /HTML Player failed to initialize/);
});

test('missing player reports a non-repairable timeout instead of blindly seeking', {timeout:120000}, async()=>{
  const browser = await openBrowser('chrome', {browserExecutable:process.env.ANIMATION_BROWSER_EXECUTABLE || undefined});
  try {
    await assert.rejects(verifyPreview(browser, '<!doctype html><div>尚未启动</div>', config, os.tmpdir(), {timeoutMs:500}), error => {
      assert.equal(error.code, 'preview_timeout');
      assert.equal(error.retryable, false);
      assert.match(error.message, /初始化超时/);
      return true;
    });
  } finally {await browser.close({silent:true});}
});
