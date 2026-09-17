export const NAVIGATION_ICON_OPTIONS = [
  { id: 'home', label: '首页' },
  { id: 'message', label: '对话' },
  { id: 'robot', label: '智能体' },
  { id: 'compass', label: '指南针' },
  { id: 'bolt', label: '闪电' },
  { id: 'apps', label: '应用网格' },
  { id: 'workflow', label: '流程' },
  { id: 'book', label: '知识库' },
  { id: 'clock', label: '时钟' },
  { id: 'building', label: '组织' },
  { id: 'bulb', label: '灵感' },
  { id: 'star', label: '星标' },
  { id: 'experiment', label: '实验' },
  { id: 'code', label: '代码' },
  { id: 'database', label: '数据库' },
  { id: 'team', label: '团队' },
  { id: 'tool', label: '工具' },
  { id: 'rocket', label: '启动' },
] as const;

export type NavigationIconId = typeof NAVIGATION_ICON_OPTIONS[number]['id'];

export const HEADER_NAV_ITEMS = [
  { id: 'home', path: '/', label: '首页', defaultIcon: 'home', emoji: '🏠' },
  { id: 'chat', path: '/chat', label: '对话', defaultIcon: 'message', emoji: '💬' },
  { id: 'agents', path: '/agents', label: '智能体', defaultIcon: 'robot', emoji: '🤖' },
  { id: 'delegates', path: '/delegates', label: 'AI 分身', defaultIcon: 'compass', emoji: '🧭' },
  { id: 'skills', path: '/skills', label: '技能', defaultIcon: 'bolt', emoji: '⚡' },
  { id: 'apps', path: '/apps', label: '应用', defaultIcon: 'apps', emoji: '🧩' },
  { id: 'workflows', path: '/workflows', label: '工作流', defaultIcon: 'workflow', emoji: '🔀' },
  { id: 'knowledge', path: '/knowledge', label: '知识库', defaultIcon: 'book', emoji: '📚' },
  { id: 'automations', path: '/automations', label: '自动化', defaultIcon: 'clock', emoji: '⏱️' },
  { id: 'enterprise', path: '/enterprise', label: '控制台', defaultIcon: 'building', emoji: '🏢' },
] as const satisfies readonly {
  id: string;
  path: string;
  label: string;
  defaultIcon: NavigationIconId;
  emoji: string;
}[];

export type HeaderNavigationItemId = typeof HEADER_NAV_ITEMS[number]['id'];
export type NavigationIconPreferences = Record<HeaderNavigationItemId, NavigationIconId>;

export const DEFAULT_NAVIGATION_ICONS = Object.fromEntries(
  HEADER_NAV_ITEMS.map((item) => [item.id, item.defaultIcon]),
) as NavigationIconPreferences;
