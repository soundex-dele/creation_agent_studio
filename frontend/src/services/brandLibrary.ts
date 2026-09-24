import { api } from './api';

export const brandSections = {
  positioning: { platform: '平台', introduction: '账号介绍', audience: '目标受众', topics: '内容领域', value: '价值主张', goals: '创作目标' },
  voice: { keywords: '风格关键词', principles: '表达原则', preferred: '推荐用语', forbidden: '禁用表达', positive: '正例', negative: '反例' },
  visual: { primary_color: '主色及用途', secondary_color: '辅色及用途', heading_font: '标题字体', body_font: '正文字体', style: '画面风格', layout: '排版要求', logo: 'Logo 使用说明' },
};
export const brandModules = { positioning: '账号定位', products: '产品事实', voice: '品牌语气', examples: '优秀范文', visual: '视觉规范' };
export type BrandModule = keyof typeof brandModules;
export type BrandSection = keyof typeof brandSections;
export interface BrandProfile {
  id: string;
  application_id: number;
  name: string;
  positioning: Record<string, string>;
  voice: Record<string, string>;
  visual: Record<string, string>;
  updated_at: string;
}
export interface BrandItem {
  id: string;
  name: string;
  description?: string;
  facts?: string[];
  source?: string;
  restrictions?: string;
  prohibited_claims?: string;
  platform?: string;
  body?: string;
  source_url?: string;
  highlights?: string;
}
export interface BrandReference {
  profile_id: string;
  modules: BrandModule[];
  product_ids: string[];
  example_ids: string[];
}
export interface BrandConfig { enabled?: boolean; default_modules: BrandModule[]; fields: Record<string, string> }
export interface BrandSelection { profile: BrandProfile; reference: BrandReference }
export interface BrandPage<T> { count: number; results: T[]; next: string | null }

export async function allBrandPages<T>(url: string, signal: AbortSignal): Promise<T[]> {
  const items: T[] = [];
  let page = 1;
  while (!signal.aborted) {
    const result = await api.get<BrandPage<T>>(url, { page }, { signal });
    items.push(...result.results);
    if (!result.next) break;
    page += 1;
  }
  return items;
}

export function inheritedBrandFields(config: BrandConfig | undefined, selection: BrandSelection | null, explicit: string[]): string[] {
  if (!config || !selection) return [];
  return Object.entries(config.fields).flatMap(([field, path]) => {
    const [module, key] = path.split('.') as [BrandSection, string | undefined];
    const data = selection.profile[module];
    const available = data && (key ? data[key] : Object.values(data).some(Boolean));
    return selection.reference.modules.includes(module) && available && !explicit.includes(field) ? [field] : [];
  });
}
