import test from 'node:test';
import assert from 'node:assert/strict';
import { capture } from '../browser.mjs';
function page() {
  let evaluations = 0;
  return { goto: async () => ({ status: () => 200 }), waitForLoadState: async () => { throw new Error('busy connection'); },
    evaluate: async () => ++evaluations > 4 ? '<article>动态正文</article>' : undefined,
    waitForTimeout: async () => {}, url: () => 'https://example.com/final', get evaluations() { return evaluations; } };
}
test('bounded rendering waits and scrolling precede final extraction', async () => {
  const browser = page(); const stages = [];
  const result = await capture(browser, 'https://example.com/', stage => stages.push(stage), { extractDocument: async value => value });
  assert.equal(browser.evaluations, 5); assert.equal(result.html, '<article>动态正文</article>');
  assert.equal(result.url, 'https://example.com/final');
  assert.deepEqual(stages, ['loading', 'rendering', 'extracting']);
});
test('navigation timeout and HTTP denial never become successful articles', async () => {
  const browser = page();
  browser.goto = async () => { throw Object.assign(new Error('timeout'), { name: 'TimeoutError' }); };
  await assert.rejects(capture(browser, 'https://example.com/', () => {}), /timeout/);
  browser.goto = async () => ({ status: () => 403 });
  await assert.rejects(capture(browser, 'https://example.com/', () => {}), /INTERACTION_REQUIRED/);
});
