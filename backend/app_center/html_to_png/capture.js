'use strict';

const fs = require('fs');
const { pathToFileURL } = require('url');
const { chromium } = require('playwright');

function emit(payload) {
  process.stdout.write(`${JSON.stringify(payload)}\n`);
}

async function main() {
  const config = JSON.parse(fs.readFileSync(0, 'utf8'));
  const browser = await chromium.launch({
    headless: true,
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu'],
  });
  let succeeded = 0;
  try {
    for (let index = 0; index < config.files.length; index += 1) {
      const file = config.files[index];
      emit({ type: 'started', index: index + 1, input: file.input });
      const context = await browser.newContext({
        viewport: { width: config.width, height: config.height },
        deviceScaleFactor: config.deviceScaleFactor,
      });
      const page = await context.newPage();
      try {
        await page.goto(pathToFileURL(file.input).href, {
          waitUntil: config.waitUntil,
          timeout: config.navigationTimeout,
        });
        if (config.noWebFonts) {
          await page.evaluate(() => {
            document.querySelectorAll(
              'link[rel="preconnect"], link[rel="stylesheet"][href*="fonts.googleapis"], link[rel="stylesheet"][href*="fonts.gstatic"]',
            ).forEach((element) => element.remove());
          });
        }
        await page.waitForTimeout(1000);
        let target = null;
        if (!config.fullPage && config.selector) {
          target = await page.$(config.selector);
        }
        if (target) {
          await target.screenshot({ path: file.output, omitBackground: config.transparent });
        } else {
          await page.screenshot({
            path: file.output,
            omitBackground: config.transparent,
            fullPage: config.fullPage || Boolean(config.selector),
          });
        }
        succeeded += 1;
        emit({ type: 'completed', index: index + 1, input: file.input, output: file.output });
      } catch (error) {
        emit({
          type: 'failed',
          index: index + 1,
          input: file.input,
          error: error instanceof Error ? error.message : String(error),
        });
      } finally {
        await context.close();
      }
    }
  } finally {
    await browser.close();
  }
  emit({ type: 'summary', succeeded, total: config.files.length });
}

main().catch((error) => {
  process.stderr.write(`${error instanceof Error ? error.stack : String(error)}\n`);
  process.exitCode = 1;
});
