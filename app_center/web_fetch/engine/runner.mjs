import { chromium } from 'playwright';
import { capture } from './browser.mjs';
import { resolveTarget, startProxy } from './network.mjs';

const emit = data => process.stdout.write(`${JSON.stringify(data)}\n`);
let browser;
let proxy;
let shuttingDown;
async function close() {
  if (!shuttingDown) shuttingDown = (async () => {
    await browser?.close().catch(() => {});
    await proxy?.close().catch(() => {});
  })();
  await shuttingDown;
}
for (const signal of ['SIGTERM', 'SIGINT']) process.on(signal, () => void close().finally(() => process.exit(1)));

try {
  let input = '';
  for await (const chunk of process.stdin) {
    input += chunk;
    if (input.length > 20_000) throw new Error('UNSAFE_URL');
  }
  const { url } = JSON.parse(input);
  await resolveTarget(url);
  proxy = await startProxy();
  emit({ type: 'progress', stage: 'starting' });
  browser = await chromium.launch({ headless: true, proxy: proxy.settings,
    args: ['--proxy-bypass-list=<-loopback>', '--disable-quic', '--disable-background-networking',
      '--force-webrtc-ip-handling-policy=disable_non_proxied_udp', '--disable-features=WebRtcHideLocalIpsWithMdns'],
  });
  const context = await browser.newContext({ serviceWorkers: 'block', acceptDownloads: false,
    viewport: { width: 1280, height: 900 }, locale: 'zh-CN', javaScriptEnabled: true });
  await context.route('**/*', route => {
    const request = route.request();
    try {
      parseRequest(request);
      return route.continue();
    } catch { return route.abort('blockedbyclient'); }
  });
  await context.routeWebSocket('**/*', socket => socket.close());
  const page = await context.newPage();
  context.on('page', extra => { if (extra !== page) void extra.close(); });
  const document = await capture(page, url, stage => emit({ type: 'progress', stage }));
  if (proxy.limited) throw new Error('RESOURCE_LIMIT');
  if (proxy.blocked) document.warnings.push('页面部分请求指向非公网地址，已阻止加载。');
  emit({ type: 'result', document });
} catch (error) {
  const codes = ['UNSAFE_URL', 'ARTICLE_UNAVAILABLE', 'INTERACTION_REQUIRED', 'DOM_TOO_LARGE', 'EMPTY_CONTENT', 'HTTP_ERROR', 'RESOURCE_LIMIT'];
  const code = proxy?.limited ? 'RESOURCE_LIMIT' : proxy?.blocked ? 'UNSAFE_URL' : codes.includes(error.message) ? error.message
    : error.name === 'TimeoutError' ? 'TIMEOUT'
    : /Executable doesn't exist|browserType.launch/.test(error.message) ? 'BROWSER_UNAVAILABLE' : 'FETCH_FAILED';
  emit({ type: 'error', code });
  process.exitCode = 1;
} finally { await close(); }

function parseRequest(request) {
  const url = new URL(request.url());
  if (!['http:', 'https:'].includes(url.protocol) || ['media', 'font'].includes(request.resourceType())) throw new Error('BLOCKED');
}
