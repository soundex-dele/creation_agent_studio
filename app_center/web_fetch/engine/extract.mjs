import { JSDOM, VirtualConsole } from 'jsdom';
import { Defuddle } from 'defuddle/node';
import { Readability } from '@mozilla/readability';
import TurndownService from 'turndown';
import { gfm } from 'turndown-plugin-gfm';

export const MAX_DOM_BYTES = 5 * 1024 * 1024;

export function safeUrl(value, base) {
  if (!value?.trim()) return null;
  try {
    const url = new URL(value, base);
    return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password ? url.href : null;
  } catch { return null; }
}

function meta(doc, ...names) {
  for (const name of names) {
    const value = doc.querySelector(`meta[property="${name}"], meta[name="${name}"]`)?.getAttribute('content')?.trim();
    if (value) return value;
  }
  return null;
}

export function detectGate(doc, url) {
  const text = doc.body?.textContent?.trim() || '';
  const title = doc.title || '';
  const wechat = new URL(url).hostname === 'mp.weixin.qq.com';
  if (wechat && /该内容已被发布者删除|此内容因违规无法查看|该内容暂时无法查看|内容已删除|此内容已被发布者删除/.test(text)) return 'ARTICLE_UNAVAILABLE';
  const hasArticle = Boolean(doc.querySelector('#js_content, article, main')) && text.length > 400;
  const gate = doc.querySelector('#challenge-running, #challenge-form, .g-recaptcha, #captcha, input[type="password"]');
  if ((!hasArticle && gate) || /just a moment|access denied|verify you are human|安全验证|访问受限/i.test(title)
      || (wechat && !doc.querySelector('#js_content') && /环境异常|访问过于频繁|验证后继续|完成验证/.test(text))) return 'INTERACTION_REQUIRED';
  if (!hasArticle && text.length < 3000 && /登录后(?:查看|继续|阅读)|请先登录|sign in to (?:continue|read)|log in to (?:continue|read)|subscribe to continue|订阅后阅读/i.test(text)) return 'INTERACTION_REQUIRED';
  return null;
}

export async function extract({ html, url, requestedUrl = url }, dependencies = {}) {
  if (Buffer.byteLength(html, 'utf8') > MAX_DOM_BYTES) throw new Error('DOM_TOO_LARGE');
  // jsdom never executes scripts or loads external resources here.
  const dom = new JSDOM(html, { url, virtualConsole: new VirtualConsole() });
  try {
    const doc = dom.window.document;
    const gate = detectGate(doc, url);
    if (gate) throw new Error(gate);
    const wechat = new URL(url).hostname === 'mp.weixin.qq.com' && doc.querySelector('#js_content');
    const metadata = {
      title: doc.querySelector('#activity-name')?.textContent.trim() || meta(doc, 'og:title') || doc.title?.trim() || null,
      author: doc.querySelector('#js_author_name')?.textContent.trim() || meta(doc, 'author', 'article:author'),
      publishedAt: doc.querySelector('#publish_time')?.textContent.trim() || meta(doc, 'article:published_time', 'date', 'pubdate'),
      siteName: doc.querySelector('#js_name')?.textContent.trim() || meta(doc, 'og:site_name'),
      summary: meta(doc, 'description', 'og:description'),
      canonicalUrl: safeUrl(doc.querySelector('link[rel="canonical"]')?.getAttribute('href') || meta(doc, 'og:url'), url),
      language: doc.documentElement.lang || null,
    };
    if (metadata.canonicalUrl) doc.querySelector('link[rel="canonical"]')?.setAttribute('href', metadata.canonicalUrl);
    // Normalize lazy media BEFORE readability/Defuddle can remove their attributes.
    for (const img of doc.querySelectorAll('img')) {
      const source = safeUrl(img.getAttribute('data-src') || img.getAttribute('data-original') || img.getAttribute('src'), url);
      if (source) img.setAttribute('src', source); else img.remove();
      img.removeAttribute('srcset');
    }
    for (const link of doc.querySelectorAll('a')) {
      const href = safeUrl(link.getAttribute('href'), url);
      if (href) link.setAttribute('href', href); else link.removeAttribute('href');
    }
    const linkedMedia = new Map();
    for (const node of doc.querySelectorAll('video, audio')) {
      const source = safeUrl(node.getAttribute('src') || node.querySelector('source')?.getAttribute('src'), url);
      if (!source) { node.remove(); continue; }
      const type = node.tagName.toLowerCase();
      linkedMedia.set(source, { type, url: source, alt: null });
      const anchor = doc.createElement('a');
      anchor.href = source; anchor.textContent = type === 'video' ? '视频链接' : '音频链接';
      node.replaceWith(anchor);
    }
    let content;
    let method;
    const warnings = [];
    if (wechat) {
      content = wechat.innerHTML;
      method = 'wechat';
      if (!metadata.publishedAt) {
        const timestamp = html.match(/\b(?:ct|create_time)\s*[:=]\s*["']?(\d{10})\b/)?.[1];
        if (timestamp) metadata.publishedAt = new Date(Number(timestamp) * 1000).toISOString();
      }
    } else {
      try {
        const parse = dependencies.defuddle || ((document) => Defuddle(document, url, {
          markdown: false, useAsync: false, includeReplies: false,
          fetch: async () => { throw new Error('External extraction is disabled'); },
        }));
        const result = await parse(doc.cloneNode(true));
        if (result?.content?.trim()) {
          content = result.content; method = 'defuddle';
          metadata.title ||= result.title || null;
          metadata.author ||= result.author || null;
          metadata.publishedAt ||= result.published || null;
        }
      } catch { /* Local fallback; never send the page to a conversion service. */ }
      if (!content) {
        const result = new Readability(doc.cloneNode(true), { keepClasses: true }).parse();
        if (result?.content?.trim()) {
          content = result.content; method = 'readability';
          metadata.title ||= result.title || null;
          metadata.author ||= result.byline || null;
        }
      }
      if (!content) {
        content = doc.querySelector('main, article')?.innerHTML;
        method = 'semantic-html';
        warnings.push('使用页面正文区域提取，可能包含少量导航内容。');
      }
    }
    if (!content) throw new Error('EMPTY_CONTENT');
    const fragment = doc.createElement('div');
    fragment.innerHTML = content;
    fragment.querySelectorAll('script, style, noscript, iframe, form, nav, footer, svg, button, object, embed, input, link, meta, base').forEach(node => node.remove());
    for (const node of fragment.querySelectorAll('*')) {
      for (const attribute of [...node.attributes]) {
        if (/^on/i.test(attribute.name) || ['style', 'srcdoc'].includes(attribute.name)) node.removeAttribute(attribute.name);
      }
    }
    const media = [];
    for (const node of fragment.querySelectorAll('img, video, audio')) {
      const source = safeUrl(node.getAttribute('src') || node.querySelector('source')?.getAttribute('src'), url);
      if (!source) { node.remove(); continue; }
      const type = node.tagName.toLowerCase() === 'img' ? 'image' : node.tagName.toLowerCase();
      if (!media.some(item => item.url === source)) media.push({ type, url: source, alt: node.getAttribute('alt') || null });
      if (type === 'image') node.setAttribute('src', source);
      else { const anchor = doc.createElement('a'); anchor.href = source; anchor.textContent = type === 'video' ? '视频链接' : '音频链接'; node.replaceWith(anchor); }
    }
    for (const link of fragment.querySelectorAll('a')) {
      const href = safeUrl(link.getAttribute('href'), url);
      if (href) link.setAttribute('href', href); else link.removeAttribute('href');
      if (linkedMedia.has(href) && !media.some(item => item.url === href)) media.push(linkedMedia.get(href));
    }
    const converter = new TurndownService({ headingStyle: 'atx', codeBlockStyle: 'fenced', bulletListMarker: '-' });
    converter.use(gfm);
    converter.addRule('fencedCodeLanguage', {
      filter: node => node.nodeName === 'PRE' && Boolean(node.querySelector('code')),
      replacement: (_text, node) => {
        const code = node.querySelector('code');
        const language = code.className.match(/(?:language|lang)-([\w+-]+)/)?.[1] || '';
        const body = code.textContent.replace(/\n$/, '');
        const fence = '`'.repeat(Math.max(3, ...[...body.matchAll(/`+/g)].map(match => match[0].length + 1)));
        return `\n\n${fence}${language}\n${body}\n${fence}\n\n`;
      },
    });
    const markdown = converter.turndown(fragment.innerHTML).trim();
    if (!markdown || (!fragment.textContent.trim() && media.length === 0)) throw new Error('EMPTY_CONTENT');
    return { version: 1, requestedUrl, url, ...metadata, capturedAt: new Date().toISOString(),
      adapter: wechat ? 'wechat' : 'generic', extractionMethod: method, markdown, media, warnings };
  } finally { dom.window.close(); }
}
