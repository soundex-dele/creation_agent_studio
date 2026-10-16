import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { extract, MAX_DOM_BYTES } from '../extract.mjs';
const fixture = name => readFile(new URL(`fixtures/${name}.html`, import.meta.url), 'utf8');

test('generic article preserves Chinese, table, code and absolute lazy media', async () => {
  const result = await extract({ html: await fixture('article'), url: 'https://example.com/posts/article' });
  assert.equal(result.title, '网页提取测试');
  assert.equal(result.author, '示例作者');
  assert.equal(result.canonicalUrl, 'https://example.com/article');
  assert.equal(result.language, 'zh-CN');
  assert.equal(result.extractionMethod, 'defuddle');
  for (const expected of ['步骤', 'Markdown', 'print(', 'https://example.com/cover.png', 'https://example.com/related']) assert.ok(result.markdown.includes(expected), result.markdown);
  assert.doesNotMatch(result.markdown, /隐私政策|首页 登录/);
});
test('Readability is a local fallback when Defuddle fails', async () => {
  const result = await extract({ html: await fixture('article'), url: 'https://example.com/' }, { defuddle: () => { throw new Error('failed'); } });
  assert.equal(result.extractionMethod, 'readability');
  assert.match(result.markdown, /```python/);
  assert.match(result.markdown, /\| 项目/);
});
test('generic extraction preserves direct video/audio links without players', async () => {
  const html = (await fixture('article')).replace('</article>', '<video src="/clip.mp4"></video><audio><source src="/voice.mp3"></audio></article>');
  const result = await extract({ html, url: 'https://example.com/' });
  assert.ok(result.media.some(item => item.type === 'video' && item.url === 'https://example.com/clip.mp4'));
  assert.ok(result.media.some(item => item.type === 'audio' && item.url === 'https://example.com/voice.mp3'));
  assert.match(result.markdown, /视频链接/); assert.match(result.markdown, /音频链接/);
});
test('WeChat adapter keeps metadata, media links, removes scripts and unsafe URLs', async () => {
  const result = await extract({ html: await fixture('wechat'), url: 'https://mp.weixin.qq.com/s/abc' });
  assert.equal(result.adapter, 'wechat');
  assert.equal(result.author, '小明');
  assert.equal(result.siteName, '示例公众号');
  assert.equal(result.publishedAt, '2026年10月16日');
  assert.equal(result.media.length, 2);
  assert.match(result.markdown, /视频链接/);
  assert.doesNotMatch(result.markdown, /javascript:|alert\(|广告与菜单/);
});
test('missing metadata stays null; no guessed dates or author', async () => {
  const result = await extract({ html: '<div id="js_content"><p>很短的文章。</p></div>', url: 'https://mp.weixin.qq.com/s/a' });
  assert.equal(result.title, null); assert.equal(result.author, null); assert.equal(result.publishedAt, null);
});
test('Defuddle never performs external async extraction, even for a known adapter URL', async () => {
  const originalFetch = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async () => { calls++; throw new Error('unexpected external request'); };
  try {
    await extract({ html: await fixture('article'), url: 'https://www.youtube.com/watch?v=abcdefghijk' }).catch(error => {
      assert.match(error.message, /EMPTY_CONTENT/);
    });
    assert.equal(calls, 0);
  } finally { globalThis.fetch = originalFetch; }
});
test('empty content and oversized DOM fail explicitly', async () => {
  await assert.rejects(extract({ html: '<html><body></body></html>', url: 'https://example.com/' }), /EMPTY_CONTENT/);
  await assert.rejects(extract({ html: 'x'.repeat(MAX_DOM_BYTES + 1), url: 'https://example.com/' }), /DOM_TOO_LARGE/);
});
for (const [html, url, error] of [
  ['<title>Just a moment...</title>', 'https://example.com/', 'INTERACTION_REQUIRED'],
  ['<p>请先登录后查看全文</p>', 'https://example.com/', 'INTERACTION_REQUIRED'],
  ['<p>环境异常，请完成验证后继续</p>', 'https://mp.weixin.qq.com/s/a', 'INTERACTION_REQUIRED'],
  ['<p>该内容已被发布者删除</p>', 'https://mp.weixin.qq.com/s/a', 'ARTICLE_UNAVAILABLE'],
]) test(`reports ${error}: ${html}`, async () => {
  await assert.rejects(extract({ html, url }), new RegExp(error));
});
