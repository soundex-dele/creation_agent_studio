import fs from 'node:fs/promises';
import path from 'node:path';

export class PreviewError extends Error {
  constructor(message, code = 'preview_runtime_error', retryable = true) {
    super(message);
    this.code = code;
    this.retryable = retryable;
  }
}

// Runs before bundled imports, so even a scene throwing at module scope is reported.
export const previewBootstrap = `
window.__animationErrors = [];
window.__reportAnimationError = (error, kind = 'runtime') => {
  const message = String(error?.message || error || '未知运行错误').slice(0, 2000);
  if (window.__animationErrors.length < 8 && !window.__animationErrors.some(item => item.message === message)) window.__animationErrors.push({message, kind});
};
window.addEventListener('error', event => window.__reportAnimationError(event.error || event.message));
window.addEventListener('unhandledrejection', event => window.__reportAnimationError(event.reason));
window.addEventListener('securitypolicyviolation', event => window.__reportAnimationError('预览资源被安全策略阻止：' + event.violatedDirective, 'policy'));
`;

export function previewEntry(config) {
  return `import React from 'react'; import {createRoot} from 'react-dom/client'; import {Player} from '@remotion/player'; import Scene from './Scene';
function failure(error) {window.__reportAnimationError(error);return <p role="alert">动画运行失败：{String(error?.message || error)}</p>}
class Boundary extends React.Component {state={error:null}; static getDerivedStateFromError(error){return {error}}; componentDidCatch(error){window.__reportAnimationError(error)}; render(){return this.state.error ? failure(this.state.error):this.props.children}}
window.__animationPlayer = React.createRef();
createRoot(document.getElementById('root')).render(<Boundary><Player ref={window.__animationPlayer} component={Scene} durationInFrames={${config.durationInFrames}} fps={${config.fps}} compositionWidth={${config.width}} compositionHeight={${config.height}} errorFallback={({error})=>failure(error)} controls showVolumeControls style={{width:'100%',height:'100%'}}/></Boundary>);`;
}

export async function verifyPreview(browser, html, config, output, {timeoutMs = 30000, captureFrames = false} = {}) {
  const logs = [];
  let crash;
  const page = await browser.newPage({context:()=>null,logLevel:'error',indent:false,pageIndex:0,
    onBrowserLog: log => {if (log.type === 'error') {logs.push(log.text.slice(0, 1000)); if (logs.length > 8) logs.shift();}}, onLog:()=>{}});
  page.on('error', error => {crash = error.message;});
  await page.setViewport({width:config.width,height:config.height,deviceScaleFactor:1});
  await page.goto({url:'about:blank',timeout:timeoutMs});
  await page.evaluate(markup=>{document.body.style.margin='0';const frame=document.createElement('iframe');frame.setAttribute('sandbox','allow-scripts');frame.style.cssText='position:fixed;inset:0;width:100%;height:100%;border:0';frame.srcdoc=markup;document.body.append(frame);},html);
  const pause = () => new Promise(resolve => setTimeout(resolve, 100));
  let playerFrame;
  async function waitFor(check, phase) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      if (crash) throw new PreviewError(`预览浏览器异常：${crash}`, 'preview_browser_error', false);
      playerFrame = page.mainFrame().childFrames()[0];
      if (playerFrame) {
        const state = await playerFrame.evaluate(()=>({
          errors: window.__animationErrors || [], ready: Boolean(window.__animationPlayer?.current),
          frame: window.__animationPlayer?.current?.getCurrentFrame(),
          scene: Boolean(document.querySelector('[data-animation-scene]')),
          alert: document.querySelector('[role="alert"]')?.textContent,
          fonts: document.fonts.status,
        }));
        if (state.errors.length) {
          const first = state.errors[0];
          throw new PreviewError(`动画预览${phase}失败：${first.message}`, first.kind === 'policy' ? 'preview_policy_error' : 'preview_runtime_error', first.kind !== 'policy');
        }
        if (state.alert) throw new PreviewError(`动画预览${phase}失败：${state.alert}`);
        if (check(state)) return;
      }
      await pause();
    }
    const detail = logs.slice(-3).join('；');
    throw new PreviewError(`动画预览${phase}超时（${timeoutMs / 1000} 秒）${detail ? `：${detail}` : '，未收到具体脚本异常，请检查浏览器运行环境或资源加载。'}`, 'preview_timeout', false);
  }
  await waitFor(state => state.ready && state.scene && state.fonts === 'loaded', '初始化');
  const isolated = await playerFrame.evaluate(()=>{try{return !parent.document;}catch{return true;}});
  if (!isolated) throw new PreviewError('HTML 预览未隔离。', 'preview_isolation_error', false);
  for (const frame of [0, Math.floor(config.durationInFrames / 2), config.durationInFrames - 1]) {
    await playerFrame.evaluate(value=>window.__animationPlayer.current.seekTo(value),frame);
    await pause();
    await waitFor(state => state.ready && state.scene && state.frame === frame && state.fonts === 'loaded', `第 ${frame} 帧`);
    if (captureFrames) {
      const result = await page._client().send('Page.captureScreenshot', {format:'png'});
      await fs.writeFile(path.join(output,`preview-${frame}.png`),Buffer.from(result.value.data,'base64'));
    }
  }
  await playerFrame.evaluate(()=>{window.__animationPlayer.current.seekTo(0);window.__animationPlayer.current.play();});
  await waitFor(state => state.ready && state.scene && state.frame > 0, '播放');
  await playerFrame.evaluate(()=>window.__animationPlayer.current.pause());
}
