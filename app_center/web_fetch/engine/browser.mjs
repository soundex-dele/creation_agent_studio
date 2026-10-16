import { MAX_DOM_BYTES, extract } from './extract.mjs';
import { parseTarget } from './network.mjs';

export async function capture(page, url, emit, { extractDocument = extract } = {}) {
  emit('loading');
  const response = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30_000 });
  if (response && response.status() >= 400) {
    throw new Error([401, 403, 429].includes(response.status()) ? 'INTERACTION_REQUIRED' : 'HTTP_ERROR');
  }
  emit('rendering');
  // A busy analytics connection must not make a readable page wait forever.
  await page.waitForLoadState('networkidle', { timeout: 4000 }).catch(() => {});
  for (let i = 0; i < 4; i++) {
    await page.evaluate(() => window.scrollBy(0, Math.max(window.innerHeight, 600)));
    await page.waitForTimeout(300);
  }
  await page.waitForLoadState('networkidle', { timeout: 2000 }).catch(() => {});
  const finalUrl = page.url();
  parseTarget(finalUrl);
  // Avoid transferring an oversized serialization out of the browser process.
  const html = await page.evaluate(max => {
    const content = document.documentElement.outerHTML;
    return new TextEncoder().encode(content).length > max ? null : content;
  }, MAX_DOM_BYTES);
  if (html === null) throw new Error('DOM_TOO_LARGE');
  emit('extracting');
  return extractDocument({ html, url: finalUrl, requestedUrl: url });
}
