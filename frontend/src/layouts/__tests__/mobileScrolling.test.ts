import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const readSource = (relativePath: string) => readFileSync(
  new URL(relativePath, import.meta.url),
  'utf8',
);

describe('mobile page scrolling', () => {
  it('keeps all five primary destinations reachable on narrow screens', () => {
    const styles = readSource('../../components/Navigation/MobileNavigation.css');
    const mobileRule = styles.match(
      /@media\s*\(max-width:\s*767px\)[\s\S]*?\.mobile-navigation\s*\{([^}]*)\}/,
    )?.[1] ?? '';

    expect(mobileRule).toMatch(/grid-template-columns:\s*repeat\(5,\s*minmax\(56px,\s*1fr\)\)/);
    expect(mobileRule).toMatch(/overflow-x:\s*auto/);
  });

  it('keeps full-bleed capability hubs vertically scrollable', () => {
    const styles = readSource('../../pages/Hubs/CapabilityHubPage.css');
    const rootRule = styles.match(/\.capability-hub\s*\{([^}]*)\}/)?.[1] ?? '';

    expect(rootRule).toMatch(/height:\s*100%/);
    expect(rootRule).toMatch(/min-height:\s*0/);
    expect(rootRule).toMatch(/overflow-y:\s*auto/);
  });

  it('gives the stacked delegate task view its own mobile scroll container', () => {
    const styles = readSource('../../pages/Delegates/Delegates.css');
    const mobileRule = styles.match(
      /@media\s*\(max-width:\s*900px\)[\s\S]*?\.delegate-task-page\s*\{([^}]*)\}/,
    )?.[1] ?? '';

    expect(mobileRule).toMatch(/grid-template-columns:\s*minmax\(0,\s*1fr\)/);
    expect(mobileRule).toMatch(/overflow-y:\s*auto/);
  });

  it('keeps compact mobile filters and relation controls touch friendly', () => {
    const appStyles = readSource('../../pages/Apps/AppsPage.css');
    const agentStyles = readSource('../../pages/Agents/AgentsPage.css');
    const taskStyles = readSource('../../pages/Tasks/TaskCenterPage.css');

    expect(appStyles).toMatch(/\.apps-category-strip button\s*\{\s*min-height:\s*44px/);
    expect(agentStyles).toMatch(/\.agents-category-strip button\s*\{\s*min-height:\s*44px/);
    expect(taskStyles).toMatch(/\.task-mobile-title,[\s\S]*?\.task-relation-part button\s*\{\s*min-height:\s*44px/);
  });
});
