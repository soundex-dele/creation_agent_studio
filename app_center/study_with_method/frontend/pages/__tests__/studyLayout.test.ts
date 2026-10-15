import { readFileSync } from 'node:fs';
import postcss, { type Container } from 'postcss';
import { describe, expect, it } from 'vitest';

const styles = postcss.parse(readFileSync(new URL('../StudyWithMethodPage.css', import.meta.url), 'utf8'));

function declarationsAt(width: number, selector: string) {
  const declarations: Record<string, string> = {};
  const visit = (container: Container) => container.nodes?.forEach((node) => {
    if (node.type === 'atrule' && node.name === 'media') {
      const breakpoint = node.params.match(/^\((max|min)-width:\s*(\d+)px\)$/);
      if (breakpoint && (breakpoint[1] === 'max'
        ? width <= Number(breakpoint[2])
        : width >= Number(breakpoint[2]))) visit(node);
    } else if (node.type === 'rule' && node.selectors.includes(selector)) {
      node.walkDecls((declaration) => { declarations[declaration.prop] = declaration.value; });
    }
  });
  visit(styles);
  return declarations;
}

describe('study card layout', () => {
  it.each([320, 375, 390, 640, 768, 1024])('separates top-level cards at %ipx', (width) => {
    expect(declarationsAt(width, '.swm-view')).toMatchObject({
      display: 'grid',
      'grid-template-columns': 'minmax(0, 1fr)',
      'align-content': 'start',
      gap: '16px',
    });
  });

  it('replaces legacy card margins instead of stacking them with the gap', () => {
    const spacingRule = styles.nodes.find((node) => node.type === 'rule'
      && node.selector.startsWith('.swm-view > :is('));
    expect(spacingRule?.type).toBe('rule');
    if (spacingRule?.type !== 'rule') return;
    for (const selector of ['.swm-quick-start', '.swm-due-review', '.swm-insights',
      '.swm-week-check-in', '.swm-mistake-card', '.swm-review-card', '.swm-report-card']) {
      expect(spacingRule.selector).toContain(selector);
    }
    expect(declarationsAt(375, spacingRule.selector)['margin-block']).toBe('0');
    expect(declarationsAt(375, '.swm-view > .swm-section-title').margin).toBe('16px 0 0');
  });

  it('retains tutor spacing and mobile single-column action cards', () => {
    expect(declarationsAt(375, '.swm-tutor-view').gap).toBe('18px');
    for (const selector of ['.swm-quick-start', '.swm-action-grid']) {
      expect(declarationsAt(375, selector)['grid-template-columns']).toBe('1fr');
      expect(parseInt(declarationsAt(375, selector).gap, 10)).toBeGreaterThanOrEqual(10);
    }
  });
});
