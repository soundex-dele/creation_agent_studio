import { readFileSync } from 'node:fs';
import postcss, { type Container } from 'postcss';
import { describe, it, expect } from 'vitest';
const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8');
const css = read('../../pages/Apps/AnimationStudioPage.css') + read('../../pages/Apps/animation/StudioEditor.css') + read('../../pages/Apps/animation/AnimationTaskDetails.css');
function declarations(selectors: string[], width: number, height = 900) {
  const values: Record<string, string> = {};
  const visit = (container: Container) => container.nodes?.forEach(node => {
    if (node.type === 'atrule' && node.name === 'media') {
      const max = node.params.match(/max-width:\s*(\d+)px/); const min = node.params.match(/min-width:\s*(\d+)px/);
      const maxHeight = node.params.match(/max-height:\s*(\d+)px/); const minHeight = node.params.match(/min-height:\s*(\d+)px/);
      if ((!max || width <= +max[1]) && (!min || width >= +min[1]) && (!maxHeight || height <= +maxHeight[1]) && (!minHeight || height >= +minHeight[1])) visit(node);
    }
    else if (node.type === 'rule' && node.selectors.some(selector => selectors.includes(selector))) node.walkDecls(item => { values[item.prop] = item.value; });
  });
  visit(postcss.parse(css)); return values;
}
describe('animation workspace scroll contract', () => {
  it.each([320, 375, 390, 767, 768, 1440])('keeps menus and file controls within narrow panes at %ipx', width => {
    expect(declarations(['.studio-select-field'], width)['min-width']).toBe('0');
    expect(declarations(['.studio-select-popup.ant-select-dropdown'], width)['max-width']).toBe('calc(100vw - 28px)');
    expect(declarations(['.studio-select-popup .ant-select-item'], width)['min-height']).toBe('44px');
    expect(declarations(['.studio-select-popup .ant-select-item-option-content'], width)['overflow-wrap']).toBe('anywhere');
    expect(declarations(['.studio-workspace .studio-file-picker'], width)['grid-template-columns']).toBe(width <= 767 ? '40px minmax(0, 1fr)' : '48px minmax(0, 1fr) auto');
    expect(declarations(['.studio-file-copy'], width)['min-width']).toBe('0');
    expect(read('../../pages/Apps/animation/StudioPanels.tsx')).not.toContain('<select');
    expect(read('../../pages/Apps/animation/AnimationStudioEditor.tsx')).not.toContain('<select');
  });
  it.each([[320, 568], [375, 667], [390, 844], [767, 600], [768, 600], [844, 320], [1440, 900]])('bounds long task details while keeping modal actions reachable at %i × %i', (width, height) => {
    const styles = (selectors: string[]) => declarations(selectors, width, height);
    expect(styles(['.animation-task-modal .ant-modal-content'])['max-height']).toBe('calc(100dvh - 48px)');
    expect(styles(['.animation-task-modal .ant-modal-content']).overflow).toBe('hidden');
    expect(styles(['.animation-task-modal .ant-modal-body'])['min-height']).toBe('0');
    expect(styles(['.animation-task-modal .ant-modal-body'])['overflow-y']).toBe('auto');
    expect(styles(['.animation-task-modal .ant-modal-footer'])['flex-shrink']).toBe('0');
    expect(styles(['.animation-task-modal .ant-btn'])['min-height']).toBe('44px');
    expect(styles(['.animation-task-error pre'])['white-space']).toBe('pre-wrap');
    expect(styles(['.animation-task-error pre'])['overflow-wrap']).toBe('anywhere');
    expect(styles(['.animation-task-error summary'])['min-height']).toBe('44px');
  });
  it.each([[320, 568], [375, 667], [390, 844], [767, 600], [768, 600], [844, 320], [1440, 900]])('keeps the storyboard inside the scrolling pane at %i × %i', (width, height) => {
    const styles = (selectors: string[]) => declarations(selectors, width, height);
    const board = styles(['.studio-storyboard-layout']);
    expect(board['grid-template-columns']).toBe(width <= 1100 ? 'minmax(0,1fr)' : '240px minmax(0,1fr)');
    expect(board['min-width']).toBe('0');
    expect(board['overflow-y']).toBeUndefined();
    expect(styles(['.studio-scene-list'])['min-width']).toBe('0');
    expect(styles(['.studio-card', '.studio-scene-editor'])['min-width']).toBe('0');
    expect(styles(['.studio-project-toolbar'])['flex-wrap']).toBe('wrap');
    expect(styles(['.studio-page-heading'])['flex-shrink']).toBe('0');
    const editor = read('../../pages/Apps/animation/AnimationStudioEditor.tsx');
    expect(editor).toContain('className="studio-storyboard-layout"');
    expect(editor).toContain('className="studio-card studio-scene-editor"');
    if (height <= 500) expect(styles(['.studio-page-heading p']).display).toBe('none');
  });

  it.each([[320, 568], [375, 667], [390, 844], [767, 600], [768, 600], [844, 320], [1440, 900]])('bounds sidebar and current content at %i × %i without introducing viewport height', (width, height) => {
    const styles = (selectors: string[]) => declarations(selectors, width, height);
    const root = styles(['.animation-workspace', '.studio-workspace']);
    expect(root.height).toBe('100%'); expect(root.overflow).toBe('hidden');
    const body = styles(['.studio-body']);
    expect(body['grid-template-columns']).toBe(width <= 767 ? 'minmax(0,1fr)' : '220px minmax(0,1fr)');
    expect(body['grid-template-rows']).toBe('minmax(0,1fr)');
    for (const selector of ['.studio-body', '.studio-content']) {
      const value = styles([selector]);
      expect(value['min-height']).toBe('0'); expect(value['min-width']).toBe('0'); expect(value.overflow).toBe('hidden');
    }
    for (const selector of ['.studio-projects', '.studio-editor-pane', '.studio-preview-pane']) {
      const value = styles([selector]);
      expect(value.flex).toBe('1'); expect(value.display).toBe('flex');
      expect(value['overflow-y']).toBe('auto'); expect(value['min-height']).toBe('0');
    }
    for (const selector of ['.studio-sidebar', '.studio-menu-drawer .ant-drawer-body']) {
      const value = styles([selector]);
      expect(value['overflow-y']).toBe('auto'); expect(value['min-height']).toBe('0');
      expect(value.padding).toContain('safe-area-inset-bottom');
    }
    expect(styles(['.studio-workspace [hidden]']).display).toBe('none');
    expect(styles(['.studio-notices'])['max-height']).toBe('25%');
    expect(styles(['.studio-notices'])['overflow-y']).toBe('auto');
    expect(styles(['.studio-navigation button'])['min-height']).toBe('44px');
    expect(read('../../pages/Apps/animation/StudioEditor.css')).not.toMatch(/\b100(?:d|s|l)?vh\b/);
  });

  it('attaches sidebar, bounded content and retained panels without legacy pane selectors', () => {
    const editor = read('../../pages/Apps/animation/AnimationStudioEditor.tsx');
    expect(editor).toContain('className="studio-body"');
    expect(editor).toContain('className="studio-content"');
    expect(editor).toContain('className="studio-sidebar"');
    expect(editor).toContain('rootClassName="studio-menu-drawer"');
    expect(editor).toContain('hidden={!active}');
    expect(editor).not.toContain('className="animation-form');
    expect(editor).not.toContain('className="animation-history');
    expect(editor).not.toContain('className="animation-results');
    const hidden = postcss.parse(css).nodes.find(node => node.type === 'rule' && node.selector === '.studio-workspace [hidden]');
    expect(hidden?.type === 'rule' && hidden.nodes.some(node => node.type === 'decl' && node.prop === 'display' && node.important)).toBe(true);
  });

  it('attaches a bounded pane workspace to ApplicationShell fullBleed', () => {
    expect(read('../../router/index.tsx')).toContain('<ApplicationShell fullBleed>{page(<AnimationStudioPage />)}</ApplicationShell>');
    expect(read('../../pages/Apps/AnimationStudioPage.tsx')).toContain('className="animation-workspace"');
    expect(read('../../pages/Apps/AnimationStudioPage.tsx')).toContain('resolveApplicationPresentation(params)');
  });
  it.each([320, 375, 390, 767, 768, 844, 1440])('keeps pane heights bounded at %ipx including short parent viewports', width => {
    const root = declarations(['.animation-workspace'], width);
    expect(root.height).toBe('100%'); expect(root['min-height']).toBe('0'); expect(root.overflow).toBe('hidden');
    const body = declarations(['.animation-body'], width);
    expect(body['min-height']).toBe('0'); expect(body.flex).toBe('1');
    const heading = declarations(['.animation-section-title', '.animation-preview-heading'], width);
    expect(heading['flex-wrap']).toBe('wrap'); expect(heading['flex-shrink']).toBe('0');
    expect(declarations(['.animation-preview-heading > div:first-child'], width)['min-width']).toBe('0');
    const studioBody = declarations(['.studio-body'], width);
    expect(studioBody['min-height']).toBe('0'); expect(studioBody.flex).toBe('1');
    expect(read('../../pages/Apps/animation/AnimationStudioEditor.tsx')).toContain('className="animation-workspace studio-workspace"');
    for (const pane of ['.studio-projects', '.studio-editor-pane', '.studio-preview-pane']) {
      const styles = declarations([pane], width);
      expect(styles['overflow-y']).toBe('auto'); expect(styles['min-height']).toBe('0'); expect(styles.height).not.toBe('auto');
      expect(styles['padding-bottom'] || styles.padding).toContain('safe-area-inset-bottom');
    }
    for (const pane of ['.animation-form', '.animation-results', '.animation-history']) {
      const values = declarations([pane], width);
      expect(values['overflow-y']).toBe('auto'); expect(values['min-height']).toBe('0'); expect(values.height).not.toBe('auto');
      expect(values['touch-action']).not.toBe('none');
    }
    if (width <= 767) {
      expect(declarations(['.animation-form'], width).display).toBe('none');
      expect(declarations(['.animation-workspace[data-tab="create"] .animation-form'], width).display).toBe('flex');
      expect(declarations(['.animation-form'], width).padding).toContain('safe-area-inset-bottom');
    }
  });
});
