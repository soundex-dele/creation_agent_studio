// @vitest-environment jsdom
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import postcss, { type Container } from 'postcss';
import { describe, expect, it } from 'vitest';
import { CreationMasterApp, type CreationMasterAppProps } from '../../../../../backend/app_center/creation_master/react/src/main';

const styles = postcss.parse(readFileSync(resolve(
  dirname(fileURLToPath(import.meta.url)),
  '../../../../../backend/app_center/creation_master/react/src/styles.css',
), 'utf8'));

function declarationsAt(width: number, selector: string) {
  const declarations: Record<string, string> = {};
  const visit = (container: Container) => container.nodes?.forEach((node) => {
    if (node.type === 'atrule' && node.name === 'media') {
      const maximum = node.params.match(/^\(max-width:\s*(\d+)px\)$/);
      if (maximum && width <= Number(maximum[1])) visit(node);
    } else if (node.type === 'rule' && node.selectors.includes(selector)) {
      node.walkDecls((declaration) => { declarations[declaration.prop] = declaration.value; });
    }
  });
  visit(styles);
  return declarations;
}

describe('creation master responsive layout', () => {
  it('isolates styles without requiring CSS scope support', () => {
    const scopes: string[] = [];
    styles.walkAtRules('scope', (rule) => { scopes.push(rule.params); });
    expect(scopes).toEqual([]);
    styles.walkRules((rule) => {
      if (rule.parent?.type === 'atrule' && rule.parent.name.endsWith('keyframes')) return;
      for (const selector of rule.selectors) expect(selector).toMatch(/^\.creation-master-app(?:\s|$)/);
    });
  });

  it.each([320, 375, 390, 560])('keeps phone content shrinkable at %ipx', (width) => {
    for (const selector of ['.workbench', '.field-grid', '.scan-row .path-field']) {
      expect(declarationsAt(width, `.creation-master-app ${selector}`)['grid-template-columns'])
        .toBe('minmax(0, 1fr)');
    }
    expect(declarationsAt(width, '.creation-master-app .source-row')['min-width']).toBe('0');
    expect(declarationsAt(width, '.creation-master-app .source-row > b')['white-space']).toBe('normal');
    expect(declarationsAt(width, '.creation-master-app .dialog-toolbar')['flex-wrap']).toBe('wrap');
  });

  it('stacks the tablet workbench but retains desktop columns', () => {
    expect(declarationsAt(768, '.creation-master-app .workbench')['grid-template-columns'])
      .toBe('minmax(0, 1fr)');
    expect(declarationsAt(1440, '.creation-master-app .workbench')['grid-template-columns'])
      .toBe('minmax(0, 1fr) 284px');
    expect(declarationsAt(1440, '.creation-master-app .mobile-topbar').display).toBe('none');
  });

  it('hides the closed mobile drawer and keeps the directory list scrollable', () => {
    expect(declarationsAt(390, '.creation-master-app .sidebar-wrap').visibility).toBe('hidden');
    expect(declarationsAt(390, '.creation-master-app .sidebar-wrap.open').visibility).toBe('visible');
    const directory = declarationsAt(390, '.creation-master-app .directory-grid');
    expect(directory['min-height']).toBe('0');
    expect(directory['overflow-y']).toBe('auto');
  });

  it.each([true, false])('preserves feature navigation with showHeader=%s', (showHeader) => {
    const container = document.createElement('div');
    container.innerHTML = renderToStaticMarkup(createElement<CreationMasterAppProps>(CreationMasterApp, { showHeader }));
    const menu = container.querySelector('nav.mobile-topbar button[aria-label="打开导航"]');
    expect(menu).not.toBeNull();
    expect(menu?.getAttribute('aria-expanded')).toBe('false');
    expect(container.querySelector(`#${menu?.getAttribute('aria-controls')}`)).not.toBeNull();
  });
});
