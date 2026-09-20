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
  {
    id: 'workbench', path: '/', label: '工作台', defaultIcon: 'home', emoji: '🏠',
    activePrefixes: ['/'],
  },
  {
    id: 'tasks', path: '/tasks', label: '任务中心', defaultIcon: 'clock', emoji: '✅',
    activePrefixes: ['/tasks', '/runs'],
  },
  {
    id: 'apps', path: '/apps', label: '应用', defaultIcon: 'apps', emoji: '🧩',
    activePrefixes: ['/apps', '/applications', '/chat', '/workspace', '/templates'],
  },
  {
    id: 'build', path: '/build', label: '构建', defaultIcon: 'workflow', emoji: '🏗️',
    activePrefixes: ['/build', '/delegates', '/workflows', '/automations'],
  },
  {
    id: 'resources', path: '/resources', label: '资源库', defaultIcon: 'database', emoji: '🗂️',
    activePrefixes: ['/resources', '/agents', '/skills', '/knowledge'],
  },
] as const satisfies readonly {
  id: string;
  path: string;
  label: string;
  defaultIcon: NavigationIconId;
  emoji: string;
  activePrefixes: readonly string[];
}[];

export const isHeaderNavigationItemActive = (
  item: (typeof HEADER_NAV_ITEMS)[number],
  pathname: string,
  search = '',
) => {
  const launchedFromWorkbench = new URLSearchParams(search).get('entry') === 'home'
    && ['/apps', '/applications', '/chat', '/workspace', '/templates'].some((prefix) => (
      pathname === prefix || pathname.startsWith(`${prefix}/`)
    ));
  if (launchedFromWorkbench) return item.id === 'workbench';
  return item.activePrefixes.some((prefix) => (
    prefix === '/'
      ? pathname === '/'
      : pathname === prefix || pathname.startsWith(`${prefix}/`)
  ));
};

export type HeaderNavigationItemId = typeof HEADER_NAV_ITEMS[number]['id'];
export const SIDE_NAVIGATION_GROUPS: Partial<Record<HeaderNavigationItemId, readonly {
  path: string;
  label: string;
}[]>> = {
  build: [
    { path: '/delegates', label: 'AI 分身' },
    { path: '/workflows', label: '工作流' },
    { path: '/automations', label: '自动化' },
  ],
  resources: [
    { path: '/agents', label: '智能体' },
    { path: '/skills', label: '技能' },
    { path: '/knowledge', label: '知识库' },
  ],
};

export type NavigationIconPreferences = Record<HeaderNavigationItemId, NavigationIconId>;

export const DEFAULT_NAVIGATION_ICONS = Object.fromEntries(
  HEADER_NAV_ITEMS.map((item) => [item.id, item.defaultIcon]),
) as NavigationIconPreferences;
