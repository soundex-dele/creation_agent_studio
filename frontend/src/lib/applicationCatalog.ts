import type { AppCategory, AppItem } from '@/types';

export const CASE_LIBRARY_APP_ID = 'case-library';

export const CASE_LIBRARY_CATEGORY: AppCategory = {
  slug: 'knowledge',
  name: '知识与案例',
  icon: '📚',
  description: '案例、知识与参考资料',
  app_count: 1,
};

export const CASE_LIBRARY_APP: AppItem = {
  id: CASE_LIBRARY_APP_ID,
  name: '案例库',
  description: '阅读真实案例，理解内容结构、表达方法与可复用规律。',
  category: CASE_LIBRARY_CATEGORY.slug,
  icon: '📚',
  color: '#b45309',
  tags: ['案例', '内容拆解', '灵感'],
  developer: 'Creation Studio',
  kind: 'custom',
  rendererKey: 'case-library',
};

export function applicationPath(
  app: Pick<AppItem, 'id' | 'rendererKey' | 'applicationId' | 'kind'>,
  entry: 'home' | 'apps' = 'apps',
): string {
  const suffix = `entry=${entry}`;
  if (app.rendererKey === 'case-library' || app.id === CASE_LIBRARY_APP_ID) {
    return `/apps/case-library?${suffix}`;
  }
  if (app.applicationId) {
    if (app.rendererKey === 'contacts') {
      return `/applications/${app.applicationId}/contacts?${suffix}`;
    }
    if (app.kind === 'chat') {
      return `/applications/${app.applicationId}/chat?slug=${encodeURIComponent(app.id)}&${suffix}`;
    }
    return `/applications/${app.applicationId}/run?${suffix}`;
  }
  return `/apps/${app.id}?${suffix}`;
}

export function mergeBuiltInApplications(apps: AppItem[]): AppItem[] {
  return apps.some((app) => app.id === CASE_LIBRARY_APP_ID)
    ? apps
    : [CASE_LIBRARY_APP, ...apps];
}

export function mergeBuiltInCategories(categories: AppCategory[]): AppCategory[] {
  return categories.some((category) => category.slug === CASE_LIBRARY_CATEGORY.slug)
    ? categories.map((category) => category.slug === CASE_LIBRARY_CATEGORY.slug
      ? { ...category, app_count: (category.app_count ?? 0) + 1 }
      : category)
    : [CASE_LIBRARY_CATEGORY, ...categories];
}
