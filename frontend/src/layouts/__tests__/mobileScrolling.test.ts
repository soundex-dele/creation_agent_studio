import { readFileSync } from 'node:fs';
import postcss, { type Container } from 'postcss';
import { describe, expect, it } from 'vitest';

const readSource = (relativePath: string) => readFileSync(
  new URL(relativePath, import.meta.url),
  'utf8',
);

// Inspect the actual CSS declarations at each breakpoint. This guards the
// shell/page scroll contract; jsdom cannot measure layout or simulate panning.
function declarationsAt(sources: string[], selectors: string[], width: number) {
  const declarations: Record<string, string> = {};
  const visit = (container: Container) => container.nodes?.forEach((node) => {
    if (node.type === 'atrule' && node.name === 'media') {
      const condition = node.params.match(/^\((min|max)-width:\s*(\d+)px\)$/);
      if (condition && (condition[1] === 'min'
        ? width >= Number(condition[2]) : width <= Number(condition[2]))) visit(node);
    } else if (node.type === 'rule' && node.selectors.some(selector => selectors.includes(selector))) {
      node.walkDecls(declaration => { declarations[declaration.prop] = declaration.value; });
    }
  });
  sources.forEach(source => visit(postcss.parse(source)));
  return declarations;
}

describe('mobile page scrolling', () => {
  const globalStyles = readSource('../../styles/global.css');

  it('keeps viewport clipping in the shell and assigns scrolling to padded views', () => {
    for (const selector of ['body', '#root', '.app-main']) {
      expect(declarationsAt([globalStyles], [selector], 390).overflow).toBe('hidden');
    }
    expect(declarationsAt([globalStyles], ['.app-main', '.app-main--padded'], 390)['overflow-y']).toBe('auto');
  });

  describe.each([
    ['KitchenAssistantPage', 'kitchen-page'],
    ['ResearchAssistantPage', 'research-host'],
  ])('%s full-bleed scroll owner', (page, rootClass) => {
    const pageStyles = readSource(`../../pages/Apps/${page}.css`);

    it('attaches the shared scroll container at the full-bleed route root', () => {
      const source = readSource(`../../pages/Apps/${page}.tsx`);
      const routes = readSource('../../router/index.tsx');
      expect(source).toContain(`className="${rootClass} app-scroll-page"`);
      expect(routes).toContain(`<ApplicationShell fullBleed>{page(<${page} />)}</ApplicationShell>`);
    });

    it.each([320, 375, 390, 767, 768, 844, 1440])('retains parent-bounded scrolling at %ipx', (width) => {
      const declarations = declarationsAt([globalStyles, pageStyles], ['.app-scroll-page', `.${rootClass}`], width);
      expect(declarations.width).toBe('100%');
      expect(declarations.height).toBe('100%');
      expect(declarations['min-height']).toBe('0');
      expect(declarations['min-width']).toBe('0');
      expect(declarations['overflow-y']).toBe('auto');
      expect(declarations.overflow).not.toBe('hidden');
      expect(declarations['touch-action']).not.toBe('none');
      // Parent-relative sizing also fits the smaller content height with
      // navigation visible, in an embed, or on a short landscape viewport.
      expect(declarations.height).not.toMatch(/vh|dvh/);
    });
  });

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
    expect(taskStyles).toMatch(/\.task-mobile-title,\s*\.task-relation-link\s*\{\s*min-height:\s*44px/);
  });

  it('separates bulk permission controls from their tables on every viewport', () => {
    const styles = readSource('../../pages/Enterprise/EnterprisePage.css');
    const toolbarRule = styles.match(/\.enterprise-bulk-toolbar\s*\{([^}]*)\}/)?.[1] ?? '';
    const mobileRule = styles.match(
      /@media\s*\(max-width:\s*640px\)[\s\S]*?\.enterprise-bulk-toolbar \.ant-btn\s*\{([^}]*)\}/,
    )?.[1] ?? '';

    expect(toolbarRule).toMatch(/gap:\s*16px/);
    expect(toolbarRule).toMatch(/margin-bottom:\s*16px/);
    expect(mobileRule).toMatch(/min-height:\s*44px/);
  });
});

it.each([320, 375, 390, 767, 768, 844, 1440])('keeps agent plans and interaction forms inside the chat scroll pane at %ipx', width => {
  const chatStyles = readSource('../../components/Chat/ChatContainer.css');
  const activityStyles = readSource('../../components/Chat/AgentActivityPanel.css');
  const source = readSource('../../components/Chat/ChatContainer.tsx');
  expect(source.indexOf('className="chat-messages"')).toBeLessThan(source.indexOf('<AgentQuestionCard'));
  const container = declarationsAt([chatStyles], ['.chat-container'], width);
  const messages = declarationsAt([chatStyles], ['.chat-messages'], width);
  expect(container.height).toBe('100%');
  expect(container['min-height']).toBe('0');
  expect(messages['min-height']).toBe('0');
  expect(messages['overflow-y']).toBe('auto');
  const output = declarationsAt([activityStyles], ['.agent-activity-panel pre'], width);
  expect(output['max-height']).toBe('320px');
  expect(output.overflow).toBe('auto');
  const actions = declarationsAt([activityStyles], ['.agent-mcp-form .agent-question-actions'], width);
  expect(actions['flex-wrap']).toBe('wrap');
});
