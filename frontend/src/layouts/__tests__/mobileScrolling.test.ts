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

  it.each([320, 375, 390, 767, 768, 844, 1440])('bounds form templates and manual workflow setup at %ipx', (width) => {
    const chat = readSource('../../pages/Apps/ChatApplicationRuntimePage.css');
    const root = declarationsAt([chat], ['.chat-app-page'], width);
    const builder = declarationsAt([chat], ['.chat-app-builder'], width);
    expect(root.height).toBe('100%');
    expect(root['min-height']).toBe('0');
    expect(builder.flex).toBe('1');
    expect(builder['min-height']).toBe('0');
    expect(builder['min-width']).toBe('0');
    expect(builder['overflow-y']).toBe('auto');
    const manual = readSource('../../pages/Workflows/WorkflowManualRunnerPage.tsx');
    expect(manual).toContain('className="workflow-manual-setup app-scroll-page"');
    const modal = declarationsAt([readSource('../../components/FormPresetPicker.css')], ['.form-preset-editor'], width);
    expect(modal['overflow-y']).toBe('auto');
    expect(modal['max-height']).toBe('65dvh');
    expect(modal.padding).toContain('safe-area-inset-bottom');
  });

  it.each([320, 375, 390, 767, 768, 844, 1440])('keeps form chat actions clear of the sidebar and preserves message scrolling at %ipx', (width) => {
    const page = readSource('../../pages/Apps/ChatApplicationRuntimePage.css');
    const chat = readSource('../../components/Chat/ChatContainer.css');
    const tools = declarationsAt([page], ['.chat-app-tools'], width);
    const toolbar = declarationsAt([chat], ['.chat-workspace-toolbar'], width);
    const button = declarationsAt([chat], ['.chat-workspace-toolbar .ant-btn'], width);
    const rightPadding = Number.parseFloat(toolbar.padding.split(' ')[1]);
    expect(Number.parseFloat(tools.right)).toBeGreaterThanOrEqual(rightPadding + Number.parseFloat(button.width) + 8);
    expect(declarationsAt([page], ['.chat-app-page'], width).height).toBe('100%');
    expect(declarationsAt([page], ['.chat-app-chat'], width)['min-height']).toBe('0');
    expect(declarationsAt([chat], ['.chat-container'], width).height).toBe('100%');
    expect(declarationsAt([chat, page], ['.chat-messages', '.chat-app-chat .chat-messages'], width)['overflow-y']).toBe('auto');
  });

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

  it.each([320, 375, 390, 767, 768, 844, 1440])('reserves kitchen bottom navigation outside the scroll pane at %ipx', (width) => {
    const styles = readSource('../../pages/Apps/KitchenAssistantPage.css');
    const workspace = declarationsAt([styles], ['.kitchen-workspace'], width);
    const page = declarationsAt([globalStyles, styles], ['.app-scroll-page', '.kitchen-page'], width);
    const navigation = declarationsAt([styles], ['.kitchen-bottom-navigation'], width);
    // Include the nav ancestor so this outranks Ant Design's three-class
    // selector, even when its runtime stylesheet is injected after page CSS.
    const tabs = declarationsAt([styles], ['.kitchen-bottom-navigation .kitchen-primary-tabs > .ant-tabs-nav .ant-tabs-nav-list'], width);

    expect(workspace.display).toBe('flex');
    expect(workspace['flex-direction']).toBe('column');
    expect(workspace.height).toBe('100%');
    expect(workspace['min-height']).toBe('0');
    expect(workspace.overflow).toBe('hidden');
    expect(page.flex).toBe('1');
    expect(page['min-height']).toBe('0');
    expect(page['overflow-y']).toBe('auto');
    expect(navigation['flex-shrink']).toBe('0');
    expect(navigation.position).toBeUndefined();
    expect(navigation.padding).toContain('env(safe-area-inset-bottom)');
    expect(tabs['grid-template-columns']).toBe('repeat(5, minmax(0, 1fr))');
    expect(tabs.display).toBe('grid');
    expect(tabs.gap).toBe('8px');
  });

  it.each([320, 375, 390, 767])('separates mobile kitchen actions from search and gives them room at %ipx', width => {
    const styles = readSource('../../pages/Apps/KitchenAssistantPage.css');
    const actions = declarationsAt([styles], ['.kitchen-actions', '.kitchen-recipe-actions'], width);
    const primary = declarationsAt([styles], ['.kitchen-recipe-actions > .ant-btn-primary'], width);
    const hero = declarationsAt([styles], ['.kitchen-hero .kitchen-actions'], width);
    expect(actions.display).toBe('grid');
    expect(actions.gap).toBe('12px');
    expect(actions['grid-template-columns']).toBe('repeat(2, minmax(0, 1fr))');
    expect(primary['grid-column']).toBe('1 / -1');
    expect(hero['grid-template-columns']).toBe('minmax(0, 1fr)');
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
