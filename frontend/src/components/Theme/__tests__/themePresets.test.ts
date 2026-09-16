import { describe, expect, it } from 'vitest';
import {
  getThemePreset,
  isSelectableThemeId,
  isThemeId,
  SELECTABLE_THEME_PRESETS,
  THEME_PRESETS,
} from '../themePresets';

const relativeLuminance = (hex: string) => {
  const channels = hex.match(/[\da-f]{2}/gi)?.map((value) => {
    const channel = Number.parseInt(value, 16) / 255;
    return channel <= 0.04045
      ? channel / 12.92
      : ((channel + 0.055) / 1.055) ** 2.4;
  });
  if (!channels || channels.length !== 3) throw new Error(`Invalid color: ${hex}`);
  return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
};

const contrastRatio = (foreground: string, background: string) => {
  const light = Math.max(relativeLuminance(foreground), relativeLuminance(background));
  const dark = Math.min(relativeLuminance(foreground), relativeLuminance(background));
  return (light + 0.05) / (dark + 0.05);
};

describe('theme presets', () => {
  it('provides unique, resolvable theme ids', () => {
    const ids = THEME_PRESETS.map((preset) => preset.id);
    expect(new Set(ids).size).toBe(ids.length);
    expect(ids.every(isThemeId)).toBe(true);
    expect(ids.every((id) => getThemePreset(id).id === id)).toBe(true);
  });

  it('defines complete semantic colors for every theme', () => {
    for (const preset of THEME_PRESETS) {
      expect(Object.values(preset.colors).every(Boolean)).toBe(true);
      expect(['light', 'dark']).toContain(preset.mode);
    }
  });

  it('exposes only the established light and dark themes', () => {
    expect(SELECTABLE_THEME_PRESETS.map((preset) => preset.id)).toEqual(['light', 'dark']);
    expect(isSelectableThemeId('light')).toBe(true);
    expect(isSelectableThemeId('ocean')).toBe(false);
  });

  it('keeps text and solid controls at WCAG AA contrast', () => {
    for (const preset of THEME_PRESETS) {
      const { colors } = preset;
      expect(contrastRatio(colors.text, colors.bgCard), preset.name).toBeGreaterThanOrEqual(4.5);
      expect(contrastRatio(colors.textSecondary, colors.bgCard), preset.name).toBeGreaterThanOrEqual(4.5);
      expect(contrastRatio(colors.primary, colors.bgCard), preset.name).toBeGreaterThanOrEqual(4.5);
      expect(contrastRatio(colors.onPrimary, colors.primary), preset.name).toBeGreaterThanOrEqual(4.5);
    }
  });
});
