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

const engine = path.dirname(fileURLToPath(import.meta.url));
let browserExecutable = process.env.ANIMATION_BROWSER_EXECUTABLE || undefined;
if (!browserExecutable && process.platform === 'win32') {
  for (const candidate of ['C:/Program Files/Google/Chrome/Application/chrome.exe', 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe']) {
    try { await fs.access(candidate); browserExecutable = candidate; break; } catch { /* next installed browser */ }
  }
}
const [mode, directory] = process.argv.slice(2);
if (!['preview', 'render', 'stills', 'cover'].includes(mode) || !directory) throw new Error('Usage: node runner.mjs preview|render|stills|cover <project>');
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
  await fs.writeFile(entry, `import React from 'react'; import {createRoot} from 'react-dom/client'; import {Player} from '@remotion/player'; import Scene from './Scene';
class Boundary extends React.Component {state={error:false}; static getDerivedStateFromError(){return {error:true}}; render(){return this.state.error ? <p role="alert">动画运行失败，请修改后重新生成。</p>:this.props.children}}
window.__animationPlayer = React.createRef();
createRoot(document.getElementById('root')).render(<Boundary><Player ref={window.__animationPlayer} component={Scene} {...${meta}} compositionWidth={${config.width}} compositionHeight={${config.height}} controls showVolumeControls style={{width:'100%',height:'100%'}}/></Boundary>);`);
  const result = await build({entryPoints:[entry],bundle:true,write:false,format:'iife',platform:'browser',jsx:'automatic',minify:true,nodePaths:[path.join(engine,'node_modules')],define:{'process.env.NODE_ENV':'"production"'}});
  const js = result.outputFiles[0].text.replace(/<\/script/gi, '<\\/script');
  const hash = createHash('sha256').update(js).digest('base64');
  const csp = `default-src 'none'; script-src 'sha256-${hash}'; style-src 'unsafe-inline'; img-src data: blob:; media-src data: blob:; font-src data:; connect-src 'none'; base-uri 'none'; form-action 'none'`;
  await fs.writeFile(path.join(output,'preview.html'), `<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8"><meta http-equiv="Content-Security-Policy" content="${csp}"><meta name="viewport" content="width=device-width,initial-scale=1"><title>动画预览</title><style>html,body,#root{margin:0;width:100%;height:100%;overflow:hidden;background:#10121b;color:white}*{box-sizing:border-box}</style></head><body><div id="root"></div><script>${js}</script></body></html>`);
  // Validate real playback before publishing; no MP4 or render bundle is created here.
  const browser = await openBrowser('chrome', {browserExecutable});
  try {
    const page = await browser.newPage({context:()=>null,logLevel:'error',indent:false,pageIndex:0,onBrowserLog:null,onLog:()=>{}});
    await page.setViewport({width:config.width,height:config.height,deviceScaleFactor:1});
    const html = await fs.readFile(path.join(output,'preview.html'),'utf8');
    await page.goto({url:'about:blank',timeout:30000});
    await page.evaluate((markup)=>{document.body.style.margin='0';const frame=document.createElement('iframe');frame.setAttribute('sandbox','allow-scripts');frame.style.cssText='position:fixed;inset:0;width:100%;height:100%;border:0';frame.srcdoc=markup;document.body.append(frame);},html);
    let playerFrame;
    for (let tries=0; tries<100; tries++) {
      playerFrame = page.mainFrame().childFrames()[0];
      if (playerFrame) break;
      await new Promise(resolve=>setTimeout(resolve,100));
    }
    if (!playerFrame) throw new Error('隔离预览框架未初始化。');
    for (let tries=0; tries<100; tries++) {
      if (await playerFrame.evaluate(()=>Boolean(window.__animationPlayer?.current))) break;
      await new Promise(resolve=>setTimeout(resolve,100));
    }
    const isolated = await playerFrame.evaluate(()=>{try{return !parent.document;}catch{return true;}});
    if (!isolated) throw new Error('HTML 预览未隔离。');
    for (const frame of frameList) {
      await playerFrame.evaluate((value)=>{if(!window.__animationPlayer?.current)throw new Error('HTML Player failed to initialize');window.__animationPlayer.current.seekTo(value);},frame);
      await playerFrame.evaluate(()=>document.fonts.ready.then(()=>true));
      await new Promise(resolve=>setTimeout(resolve,150));
      const valid = await playerFrame.evaluate(()=>Boolean(document.querySelector('[data-animation-scene]')) && !document.querySelector('[role="alert"]'));
      if (!valid) throw new Error(`HTML 动画在第 ${frame} 帧运行失败。`);
      if (process.env.ANIMATION_CAPTURE_FRAMES === '1') {
        const result = await page._client().send('Page.captureScreenshot', {format:'png'});
        await fs.writeFile(path.join(output,`preview-${frame}.png`),Buffer.from(result.value.data,'base64'));
      }
    }
    await playerFrame.evaluate(()=>window.__animationPlayer.current.seekTo(0));
    await playerFrame.evaluate(()=>window.__animationPlayer.current.play());
    await new Promise(resolve=>setTimeout(resolve,300));
    const advanced = await playerFrame.evaluate(()=>window.__animationPlayer.current.getCurrentFrame()>0);
    if (!advanced) throw new Error('HTML 动画播放未推进。');
    await playerFrame.evaluate(()=>window.__animationPlayer.current.pause());
  } finally { await browser.close({silent:true}); }
  console.log(JSON.stringify({stage:'preview_ready'}));
} else {
  const entry = path.join(project, 'Root.tsx');
  await fs.writeFile(entry, `import React from 'react';import {registerRoot,Composition} from 'remotion';import Scene from './Scene';registerRoot(()=> <Composition id="Animation" component={Scene} {...${meta}}/>);`);
  const serveUrl = await bundle({entryPoint:entry,outDir:path.join(output,'bundle'),webpackOverride:(configuration)=>({...configuration,resolve:{...configuration.resolve,modules:[path.join(engine,'node_modules'),'node_modules']}})});
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
