export type ThemeId = 'light' | 'dark' | 'ocean' | 'forest' | 'violet';

export interface ThemeColors {
  bgVoid: string;
  bgSurface: string;
  bgCard: string;
  bgElevated: string;
  border: string;
  borderLit: string;
  text: string;
  textSecondary: string;
  textDim: string;
  primary: string;
  onPrimary: string;
  shadowSm: string;
  shadowMd: string;
  shadowLg: string;
}

export interface ThemePreset {
  id: ThemeId;
  name: string;
  description: string;
  mode: 'light' | 'dark';
  colors: ThemeColors;
}

export const THEME_PRESETS: readonly ThemePreset[] = [
  {
    id: 'light',
    name: '晨光',
    description: '明亮清爽的暖白工作区',
    mode: 'light',
    colors: {
      bgVoid: '#FFFFFF', bgSurface: '#F8F9FA', bgCard: '#FFFFFF', bgElevated: '#F1F3F5',
      border: '#E2E5E9', borderLit: '#C9CED6', text: '#20252D', textSecondary: '#5F6875',
      textDim: '#87909D', primary: '#B45309', onPrimary: '#FFFFFF',
      shadowSm: '0 1px 2px rgba(15, 23, 42, 0.05)',
      shadowMd: '0 4px 12px rgba(15, 23, 42, 0.08)',
      shadowLg: '0 12px 28px rgba(15, 23, 42, 0.12)',
    },
  },
  {
    id: 'dark',
    name: '曜石',
    description: '专注沉稳的中性暗色主题',
    mode: 'dark',
    colors: {
      bgVoid: '#0C0C11', bgSurface: '#14141C', bgCard: '#1C1C28', bgElevated: '#242434',
      border: '#2C2C3C', borderLit: '#3A3A4E', text: '#EAEAF0', textSecondary: '#A5A5B4',
      textDim: '#737386', primary: '#E8A838', onPrimary: '#241700',
      shadowSm: '0 1px 2px rgba(0, 0, 0, 0.3)',
      shadowMd: '0 4px 12px rgba(0, 0, 0, 0.38)',
      shadowLg: '0 12px 28px rgba(0, 0, 0, 0.48)',
    },
  },
  {
    id: 'ocean',
    name: '深海',
    description: '冷静通透的蓝黑工作区',
    mode: 'dark',
    colors: {
      bgVoid: '#07131D', bgSurface: '#0B1B28', bgCard: '#102433', bgElevated: '#173246',
      border: '#24465D', borderLit: '#35627D', text: '#EAF6FB', textSecondary: '#A7C0CE',
      textDim: '#7592A2', primary: '#38BDF8', onPrimary: '#052332',
      shadowSm: '0 1px 2px rgba(1, 8, 15, 0.34)',
      shadowMd: '0 4px 14px rgba(1, 8, 15, 0.42)',
      shadowLg: '0 14px 32px rgba(1, 8, 15, 0.52)',
    },
  },
  {
    id: 'forest',
    name: '青森',
    description: '柔和自然的浅绿工作区',
    mode: 'light',
    colors: {
      bgVoid: '#F7FAF7', bgSurface: '#EEF5EF', bgCard: '#FFFFFF', bgElevated: '#E7F0E9',
      border: '#D1E0D4', borderLit: '#B2CAB7', text: '#203129', textSecondary: '#596E61',
      textDim: '#7F9285', primary: '#1F7550', onPrimary: '#FFFFFF',
      shadowSm: '0 1px 2px rgba(24, 66, 43, 0.05)',
      shadowMd: '0 4px 12px rgba(24, 66, 43, 0.08)',
      shadowLg: '0 12px 28px rgba(24, 66, 43, 0.12)',
    },
  },
  {
    id: 'violet',
    name: '暮紫',
    description: '柔和雅致的紫黑工作区',
    mode: 'dark',
    colors: {
      bgVoid: '#120F18', bgSurface: '#19141F', bgCard: '#221B2A', bgElevated: '#2D2436',
      border: '#3B3047', borderLit: '#514160', text: '#F4EFF7', textSecondary: '#B9ABC2',
      textDim: '#87768F', primary: '#C4B5FD', onPrimary: '#25153B',
      shadowSm: '0 1px 2px rgba(5, 2, 8, 0.32)',
      shadowMd: '0 4px 14px rgba(5, 2, 8, 0.4)',
      shadowLg: '0 14px 32px rgba(5, 2, 8, 0.5)',
    },
  },
] as const;

export const THEME_PRESET_MAP = Object.fromEntries(
  THEME_PRESETS.map((preset) => [preset.id, preset]),
) as Record<ThemeId, ThemePreset>;

// Keep additional palettes available for future rollout while exposing only
// the two established themes in user-facing selectors for now.
export const SELECTABLE_THEME_PRESETS = THEME_PRESETS.slice(0, 2);

export const isThemeId = (value: unknown): value is ThemeId => (
  typeof value === 'string' && value in THEME_PRESET_MAP
);

export const isSelectableThemeId = (value: unknown): value is ThemeId => (
  isThemeId(value) && SELECTABLE_THEME_PRESETS.some((preset) => preset.id === value)
);

export const getThemePreset = (theme: ThemeId): ThemePreset => THEME_PRESET_MAP[theme];
