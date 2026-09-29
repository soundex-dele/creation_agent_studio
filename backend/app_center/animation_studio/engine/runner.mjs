import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {build} from 'esbuild';
import {bundle} from '@remotion/bundler';
import {openBrowser, renderMedia, renderStill, selectComposition} from '@remotion/renderer';
import {validateSource} from './validate.mjs';
import {fontCss} from './fonts.mjs';
import {buildStructured} from './structured.mjs';
import {previewBootstrap, previewEntry, verifyPreview, PreviewError} from './preview.mjs';
import {engineDependencies, engineWebpackOverride} from './dependencies.mjs';

const engine = path.dirname(fileURLToPath(import.meta.url));
let browserExecutable = process.env.ANIMATION_BROWSER_EXECUTABLE || undefined;
if (!browserExecutable && process.platform === 'win32') {
  for (const candidate of ['C:/Program Files/Google/Chrome/Application/chrome.exe', 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe']) {
    try { await fs.access(candidate); browserExecutable = candidate; break; } catch { /* next installed browser */ }
  }
}
try {
const [mode, directory] = process.argv.slice(2);
if (!['preview', 'render', 'stills', 'cover'].includes(mode) || !directory) throw new Error('Usage: node runner.mjs preview|render|stills|cover <project>');
const dependencies = await engineDependencies(engine);
const project = path.resolve(directory);
const output = path.join(project, 'out');
await fs.mkdir(output, {recursive: true});
const config = JSON.parse(await fs.readFile(path.join(project, 'composition.json'), 'utf8'));
if (![720, 1080, 1280, 1920].includes(config.width) || ![720, 1080, 1280, 1920].includes(config.height) || config.fps !== 30 || !Number.isInteger(config.durationInFrames) || config.durationInFrames < 150 || config.durationInFrames > 3600) throw new Error('Invalid composition metadata');
let document;
try {document=JSON.parse(await fs.readFile(path.join(project,'project.json'),'utf8'));} catch(e) {if(e.code!=='ENOENT')throw e;}
const source = document ? await buildStructured(project, document) : await fs.readFile(path.join(project, 'Animation.tsx'), 'utf8');
if (!document) validateSource(source);
const fonts = await fontCss(engine, source);
const manifest = JSON.parse(await fs.readFile(path.join(project, 'assets.json'), 'utf8'));
const assets = {};
for (const item of manifest) {
  if (!/^[a-f0-9-]+\.(png|jpeg|webp|mp3|wav|m4a)$/.test(item.file) || !/^(image\/(png|jpeg|webp)|audio\/(mpeg|wav|mp4))$/.test(item.mime_type)) throw new Error('Invalid asset manifest');
  const bytes = await fs.readFile(path.join(project, 'assets', item.file));
  assets[item.id] = `data:${item.mime_type};base64,${bytes.toString('base64')}`;
}
await fs.writeFile(path.join(project, 'assets.ts'), `export const assets: Record<string, string> = ${JSON.stringify(assets)};`);
// A trusted wrapper owns audio, duration, typography and fonts for both outputs.
await fs.writeFile(path.join(project, 'Scene.tsx'), `import React from 'react';
import {AbsoluteFill, Audio, delayRender, continueRender, cancelRender} from 'remotion';
import Animation from './Animation';
import {assets} from './assets';
const fonts = ${JSON.stringify(fonts)};
export default function Scene() {const [handle]=React.useState(()=>delayRender('Load archived fonts'));React.useEffect(()=>{document.fonts.ready.then(()=>continueRender(handle)).catch(cancelRender)},[handle]);return <AbsoluteFill data-animation-scene style={{background:'#fff',fontFamily:'"Noto Sans SC", sans-serif',overflow:'hidden'}}><style>{fonts}</style><Animation/>${config.audioId ? `<Audio src={assets[${JSON.stringify(config.audioId)}]}/>` : ''}</AbsoluteFill>}`);
const meta = `{width:${config.width},height:${config.height},fps:30,durationInFrames:${config.durationInFrames}}`;
const frameList = [0, Math.floor(config.durationInFrames / 2), config.durationInFrames - 1];

if (mode === 'preview') {
  const entry = path.join(project, 'Preview.tsx');
  await fs.writeFile(entry, previewEntry(config));
  const result = await build({entryPoints:[entry],bundle:true,write:false,format:'iife',platform:'browser',jsx:'automatic',minify:true,banner:{js:previewBootstrap},alias:dependencies.aliases,nodePaths:[dependencies.modules],define:{'process.env.NODE_ENV':'"production"'}});
  const js = result.outputFiles[0].text.replace(/<\/script/gi, '<\\/script');
  const hash = createHash('sha256').update(js).digest('base64');
  const csp = `default-src 'none'; script-src 'sha256-${hash}'; style-src 'unsafe-inline'; img-src data: blob:; media-src data: blob:; font-src data:; connect-src 'none'; base-uri 'none'; form-action 'none'`;
  await fs.writeFile(path.join(output,'preview.html'), `<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8"><meta http-equiv="Content-Security-Policy" content="${csp}"><meta name="viewport" content="width=device-width,initial-scale=1"><title>动画预览</title><style>html,body,#root{margin:0;width:100%;height:100%;overflow:hidden;background:#10121b;color:white}*{box-sizing:border-box}</style></head><body><div id="root"></div><script>${js}</script></body></html>`);
  // Validate real playback before publishing; no MP4 or render bundle is created here.
  let browser;
  try {
    browser = await openBrowser('chrome', {browserExecutable});
    const html = await fs.readFile(path.join(output,'preview.html'),'utf8');
    await verifyPreview(browser, html, config, output, {captureFrames:process.env.ANIMATION_CAPTURE_FRAMES === '1'});
  } catch (error) {
    if (error instanceof PreviewError) throw error;
    throw new PreviewError('预览浏览器执行失败：' + error.message, 'preview_browser_error', false);
  } finally { if (browser) await browser.close({silent:true}); }
  console.log(JSON.stringify({stage:'preview_ready'}));
} else {
  const entry = path.join(project, 'Root.tsx');
  await fs.writeFile(entry, `import React from 'react';import {registerRoot,Composition} from 'remotion';import Scene from './Scene';registerRoot(()=> <Composition id="Animation" component={Scene} {...${meta}}/>);`);
  const serveUrl = await bundle({entryPoint:entry,outDir:path.join(output,'bundle'),webpackOverride:configuration=>engineWebpackOverride(configuration, dependencies)});
  const indexPath = path.join(serveUrl, 'index.html');
  const index = (await fs.readFile(indexPath, 'utf8')).replace(/<link[^>]*id="__remotion_favicon"[^>]*>/,'');
  await fs.writeFile(indexPath,index.replace('<head>',`<head><link rel="icon" href="data:,"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; media-src data: blob:; font-src data:; connect-src 'none'; base-uri 'none'; form-action 'none'">`));
  const options = {serveUrl, id:'Animation', browserExecutable, timeoutInMilliseconds:60000};
  const composition = await selectComposition(options);
  if (mode === 'cover') {
    await renderStill({...options,composition,frame:Math.min(config.coverFrame||0,config.durationInFrames-1),output:path.join(output,'cover.png')});
  } else if (mode === 'stills') {
    for (const frame of frameList) await renderStill({...options,composition,frame,output:path.join(output,`frame-${frame}.png`)});
  } else {
    let previous = -1;
    await renderMedia({...options,composition,codec:'h264',pixelFormat:'yuv420p',crf:config.quality==='high'?16:20,concurrency:2,outputLocation:path.join(output,'animation.mp4'),
      onProgress:({progress})=>{const percent=Math.floor(progress*100);if(percent!==previous){previous=percent;console.log(JSON.stringify({stage:'rendering',percent}))}}});
    await renderStill({...options,composition,frame:Math.min(config.coverFrame??30,config.durationInFrames-1),output:path.join(output,'cover.png')});
  }
}

} catch (error) {
  console.error('ANIMATION_BUILD_ERROR ' + JSON.stringify({code:error.code || 'scene_build_error', retryable:error.retryable !== false, message:String(error.message || error).slice(0, 3000)}));
  process.exitCode = 1;
}
