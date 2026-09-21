export type ThemeId = 'light' | 'ink' | 'dark' | 'midnight' | 'ocean' | 'forest' | 'violet' | 'sage' | 'lavender'
  | 'sky' | 'oat' | 'rose' | 'terracotta' | 'pine' | 'mocha';

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
  primaryHover: string;
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

export const DEFAULT_THEME_ID: ThemeId = 'light';

export const THEME_PRESETS: readonly ThemePreset[] = [
  {
    id: 'light',
    name: '晨光',
    description: '明亮清爽的暖白工作区',
    mode: 'light',
    colors: {
      bgVoid: '#FFFFFF', bgSurface: '#F8F9FA', bgCard: '#FFFFFF', bgElevated: '#F1F3F5',
      border: '#E2E5E9', borderLit: '#C9CED6', text: '#20252D', textSecondary: '#5F6875',
      textDim: '#87909D', primary: '#B45309', primaryHover: '#92400E', onPrimary: '#FFFFFF',
      shadowSm: '0 1px 2px rgba(15, 23, 42, 0.05)',
      shadowMd: '0 4px 12px rgba(15, 23, 42, 0.08)',
      shadowLg: '0 12px 28px rgba(15, 23, 42, 0.12)',
    },
  },
  {
    id: 'ink',
    name: '纸墨',
    description: '清晰克制的黑白工作区',
    mode: 'light',
    colors: {
      bgVoid: '#F5F5F5', bgSurface: '#FAFAFA', bgCard: '#FFFFFF', bgElevated: '#E7E7E9',
      border: '#D1D1D6', borderLit: '#76767F', text: '#18181B', textSecondary: '#4B4B52',
      textDim: '#5F5F66', primary: '#18181B', primaryHover: '#3F3F46', onPrimary: '#FFFFFF',
      shadowSm: '0 1px 2px rgba(9, 9, 11, 0.06)',
      shadowMd: '0 5px 16px rgba(9, 9, 11, 0.09)',
      shadowLg: '0 16px 36px rgba(9, 9, 11, 0.13)',
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
      textDim: '#737386', primary: '#E8A838', primaryHover: '#F0C060', onPrimary: '#241700',
      shadowSm: '0 1px 2px rgba(0, 0, 0, 0.3)',
      shadowMd: '0 4px 12px rgba(0, 0, 0, 0.38)',
      shadowLg: '0 12px 28px rgba(0, 0, 0, 0.48)',
    },
  },
  {
    id: 'midnight',
    name: '午夜靛蓝',
    description: '深邃专注的蓝紫工作区',
    mode: 'dark',
    colors: {
      bgVoid: '#0F0F23', bgSurface: '#15152B', bgCard: '#1B1B30', bgElevated: '#27273B',
      border: '#34345A', borderLit: '#6667A2', text: '#F8FAFC', textSecondary: '#B8BED2',
      textDim: '#9AA3BD', primary: '#818CF8', primaryHover: '#A5B4FC', onPrimary: '#101128',
      shadowSm: '0 1px 2px rgba(3, 3, 15, 0.38)',
      shadowMd: '0 5px 16px rgba(3, 3, 15, 0.46)',
      shadowLg: '0 16px 36px rgba(3, 3, 15, 0.58)',
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
      textDim: '#91ADBD', primary: '#38BDF8', primaryHover: '#7DD3FC', onPrimary: '#052332',
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
      textDim: '#5D7063', primary: '#1F7550', primaryHover: '#185E41', onPrimary: '#FFFFFF',
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
      textDim: '#AC99B6', primary: '#C4B5FD', primaryHover: '#DDD6FE', onPrimary: '#25153B',
      shadowSm: '0 1px 2px rgba(5, 2, 8, 0.32)',
      shadowMd: '0 4px 14px rgba(5, 2, 8, 0.4)',
      shadowLg: '0 14px 32px rgba(5, 2, 8, 0.5)',
    },
  },
  {
    id: 'sage',
    name: '雾松',
    description: '克制柔和的灰绿工作区',
    mode: 'light',
    colors: {
      bgVoid: '#F3F5F1', bgSurface: '#E9EDE7', bgCard: '#FCFDFB', bgElevated: '#DFE5DC',
      border: '#C5CEC1', borderLit: '#849480', text: '#202820', textSecondary: '#536153',
      textDim: '#5C695A', primary: '#3F6B55', primaryHover: '#335845', onPrimary: '#FFFFFF',
      shadowSm: '0 1px 2px rgba(42, 58, 44, 0.07)',
      shadowMd: '0 5px 16px rgba(42, 58, 44, 0.1)',
      shadowLg: '0 16px 36px rgba(42, 58, 44, 0.14)',
    },
  },
  {
    id: 'lavender',
    name: '云紫',
    description: '清透雅致的白紫工作区',
    mode: 'light',
    colors: {
      bgVoid: '#F8F7FC', bgSurface: '#F1EFF8', bgCard: '#FFFFFF', bgElevated: '#E9E5F3',
      border: '#D8D1E6', borderLit: '#9688B0', text: '#292332', textSecondary: '#5D536B',
      textDim: '#665C73', primary: '#6D4BA3', primaryHover: '#56377F', onPrimary: '#FFFFFF',
      shadowSm: '0 1px 2px rgba(67, 50, 91, 0.06)',
      shadowMd: '0 5px 16px rgba(67, 50, 91, 0.09)',
      shadowLg: '0 16px 36px rgba(67, 50, 91, 0.13)',
    },
  },
  {
    id: 'sky',
    name: '晴空',
    description: '清爽理性的浅蓝工作区',
    mode: 'light',
    colors: {
      bgVoid: '#F3F8FC', bgSurface: '#EAF2F9', bgCard: '#FFFFFF', bgElevated: '#DEEAF4',
      border: '#C4D6E6', borderLit: '#7B9DBB', text: '#1D2E40', textSecondary: '#4D6378',
      textDim: '#536A7F', primary: '#2563A6', primaryHover: '#1D4F86', onPrimary: '#FFFFFF',
      shadowSm: '0 1px 2px rgba(29, 62, 94, 0.06)',
      shadowMd: '0 5px 16px rgba(29, 62, 94, 0.09)',
      shadowLg: '0 16px 36px rgba(29, 62, 94, 0.13)',
    },
  },
  {
    id: 'oat',
    name: '燕麦',
    description: '温暖舒适的奶油纸感工作区',
    mode: 'light',
    colors: {
      bgVoid: '#F6F1E8', bgSurface: '#EFE8DC', bgCard: '#FFFCF7', bgElevated: '#E7DECF',
      border: '#D5C7B4', borderLit: '#A38B70', text: '#32291F', textSecondary: '#665747',
      textDim: '#70604E', primary: '#805A3B', primaryHover: '#66462E', onPrimary: '#FFFFFF',
      shadowSm: '0 1px 2px rgba(75, 53, 31, 0.06)',
      shadowMd: '0 5px 16px rgba(75, 53, 31, 0.09)',
      shadowLg: '0 16px 36px rgba(75, 53, 31, 0.13)',
    },
  },
  {
    id: 'rose',
    name: '胭脂',
    description: '柔和细腻的豆沙粉工作区',
    mode: 'light',
    colors: {
      bgVoid: '#FCF5F6', bgSurface: '#F7EBEF', bgCard: '#FFFCFD', bgElevated: '#F0DFE5',
      border: '#E2C7D1', borderLit: '#B78095', text: '#39252D', textSecondary: '#70515F',
      textDim: '#795B68', primary: '#A34261', primaryHover: '#85354F', onPrimary: '#FFFFFF',
      shadowSm: '0 1px 2px rgba(91, 39, 58, 0.06)',
      shadowMd: '0 5px 16px rgba(91, 39, 58, 0.09)',
      shadowLg: '0 16px 36px rgba(91, 39, 58, 0.13)',
    },
  },
  {
    id: 'terracotta',
    name: '赤陶',
    description: '温暖鲜活的杏白砖橙工作区',
    mode: 'light',
    colors: {
      bgVoid: '#FBF4EE', bgSurface: '#F5E9DE', bgCard: '#FFFCF9', bgElevated: '#EDDDCF',
      border: '#DFC4B1', borderLit: '#B18468', text: '#3A2920', textSecondary: '#715342',
      textDim: '#795D4D', primary: '#A2452B', primaryHover: '#873922', onPrimary: '#FFFFFF',
      shadowSm: '0 1px 2px rgba(99, 49, 27, 0.06)',
      shadowMd: '0 5px 16px rgba(99, 49, 27, 0.09)',
      shadowLg: '0 16px 36px rgba(99, 49, 27, 0.13)',
    },
  },
  {
    id: 'pine',
    name: '松夜',
    description: '安静自然的墨绿工作区',
    mode: 'dark',
    colors: {
      bgVoid: '#101C18', bgSurface: '#16251F', bgCard: '#1D2E26', bgElevated: '#273D32',
      border: '#365245', borderLit: '#648674', text: '#EDF7F0', textSecondary: '#B3CCBD',
      textDim: '#A0BBAA', primary: '#79C9A3', primaryHover: '#A0DEBE', onPrimary: '#10291D',
      shadowSm: '0 1px 2px rgba(3, 12, 7, 0.32)',
      shadowMd: '0 5px 16px rgba(3, 12, 7, 0.42)',
      shadowLg: '0 16px 36px rgba(3, 12, 7, 0.52)',
    },
  },
  {
    id: 'mocha',
    name: '摩卡',
    description: '温润复古的深咖工作区',
    mode: 'dark',
    colors: {
      bgVoid: '#211A17', bgSurface: '#2A211C', bgCard: '#342820', bgElevated: '#44352A',
      border: '#5D4838', borderLit: '#92735A', text: '#FAF1E7', textSecondary: '#D4BEA8',
      textDim: '#C4AB93', primary: '#D7AB7A', primaryHover: '#E9C59E', onPrimary: '#302014',
      shadowSm: '0 1px 2px rgba(15, 8, 4, 0.32)',
      shadowMd: '0 5px 16px rgba(15, 8, 4, 0.42)',
      shadowLg: '0 16px 36px rgba(15, 8, 4, 0.52)',
    },
  },
] as const;

export const THEME_PRESET_MAP = Object.fromEntries(
  THEME_PRESETS.map((preset) => [preset.id, preset]),
) as Record<ThemeId, ThemePreset>;

export const SELECTABLE_THEME_PRESETS = THEME_PRESETS;

export const isThemeId = (value: unknown): value is ThemeId => (
  typeof value === 'string' && value in THEME_PRESET_MAP
);

export const isSelectableThemeId = (value: unknown): value is ThemeId => (
  isThemeId(value) && SELECTABLE_THEME_PRESETS.some((preset) => preset.id === value)
);

export const getThemePreset = (theme: ThemeId): ThemePreset => THEME_PRESET_MAP[theme];
