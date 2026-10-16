import { readFileSync } from 'node:fs';
import postcss, { type Container } from 'postcss';
import { expect, it } from 'vitest';
import applications from 'virtual:application-packages';
import { resolveApplicationPresentation } from '@/lib/applicationPresentation';
import { THEME_PRESETS } from '@/components/Theme/themePresets';

const source = readFileSync(new URL('../../../../app_center/community_chat/frontend/pages/CommunityChatPage.tsx', import.meta.url), 'utf8');
const css = postcss.parse(readFileSync(new URL('../../../../app_center/community_chat/frontend/pages/CommunityChatPage.css', import.meta.url), 'utf8'));
function styles(selector: string, width: number, height: number) {
  const result: Record<string, string> = {};
  function visit(container: Container) {
    container.nodes?.forEach(node => {
      if (node.type === 'atrule' && node.name === 'media') {
        const match = node.params.match(/^\(max-(width|height):\s*(\d+)px\)$/);
        if (match && (match[1] === 'width' ? width : height) <= +match[2]) visit(node);
      } else if (node.type === 'rule' && node.selectors.includes(selector)) {
        node.walkDecls(decl => { result[decl.prop] = decl.value; });
      }
    });
  }
  visit(css); return result;
}

function contrast(foreground: string, background: string) {
  const luminance = (hex: string) => {
    const rgb = hex.slice(1).match(/.{2}/g)!.map(channel => {
      const value = parseInt(channel, 16) / 255;
      return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
    });
    return rgb[0] * 0.2126 + rgb[1] * 0.7152 + rgb[2] * 0.0722;
  };
  const values = [luminance(foreground), luminance(background)];
  return (Math.max(...values) + 0.05) / (Math.min(...values) + 0.05);
}

it.each(THEME_PRESETS)('keeps chat placeholders, avatar initials and bubble text readable in $id (static contrast)', ({ colors }) => {
  const tokens: Record<string, string> = {
    'var(--color-text)': colors.text,
    'var(--color-text-sec)': colors.textSecondary,
    'var(--color-bg-elevated)': colors.bgElevated,
  };
  for (const scope of ['.community-page', '.community-drawer', '.community-modal']) {
    for (const control of ['.ant-input::placeholder', '.ant-select-selection-placeholder']) {
      const placeholder = styles(`${scope} ${control}`, 390, 844);
      expect(placeholder.opacity).toBe('1');
      for (const background of [colors.bgCard, colors.bgElevated]) {
        expect(contrast(tokens[placeholder.color], background)).toBeGreaterThanOrEqual(4.5);
      }
    }
    const avatar = styles(`${scope} .ant-avatar`, 390, 844);
    expect(contrast(tokens[avatar.color], tokens[avatar.background])).toBeGreaterThanOrEqual(4.5);
  }
  const bubble = styles('.community-message--mine .community-bubble', 390, 844);
  for (const foreground of [colors.text, colors.textSecondary]) {
    expect(contrast(foreground, tokens[bubble.background])).toBeGreaterThanOrEqual(4.5);
  }
});

it.each([[320, 640], [375, 812], [390, 844], [767, 900], [768, 900], [1440, 900], [844, 390]])('retains bounded panes at %i × %i (static inspection)', (width, height) => {
  const page = styles('.community-page', width, height);
  expect(page.height).toBe('100%'); expect(page['min-height']).toBe('0'); expect(page.overflow).toBe('hidden');
  for (const pane of ['.community-workspace', '.community-chat-pane', '.community-sidebar']) expect(styles(pane, width, height)['min-height']).toBe('0');
  for (const pane of ['.community-message-list', '.community-room-list']) {
    expect(styles(pane, width, height)['overflow-y']).toBe('auto');
    expect(styles(pane, width, height)['min-height']).toBe('0');
  }
  expect(styles('.community-workspace', width, height)['grid-template-columns']).toBe(width < 768 ? 'minmax(0, 1fr)' : '300px minmax(0, 1fr)');
  expect(styles('.community-composer', width, height)['flex-shrink']).toBe('0');
  expect(styles('.community-composer', width, height).padding).toContain('safe-area-inset-bottom');
  const footer = styles('.community-message-footer', width, height);
  expect(footer.contain).toBe('inline-size');
  expect(footer.height).toBe(width < 768 ? '44px' : '24px');
  expect(styles('.community-message-action-space', width, height).height).toBe(footer.height);
  if (width < 768) {
    expect(styles('.community-page--selected .community-sidebar', width, height).display).toBe('none');
    expect(styles('.community-composer textarea', width, height)['font-size']).toBe('16px');
  }
  if (height <= 480) expect(styles('.community-composer textarea', width, height)['overflow-y']).toBe('auto');
});

it.each(['entry=home', 'entry=apps', 'standalone=1', 'embedded=1'])('uses the application shell for %s', query => {
  const app = applications.find(a => a.rendererKey === 'community-chat')!;
  expect(app.routes.every(r => r.fullBleed)).toBe(true);
  expect(app.routes.some(r => r.path === '/community-chat')).toBe(true);
  expect(source).toContain('className={`community-page');
  expect(source).toContain('resolveApplicationPresentation(params)');
  expect(resolveApplicationPresentation(new URLSearchParams(query)).showApplicationHeader).toBe(query === 'entry=apps');
});
