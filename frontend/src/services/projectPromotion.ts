import { api } from './api';
import { createIdempotencyKey } from '@/lib/idempotencyKey';

export type Data = Record<string, unknown>;
export type Resource = 'cases' | 'topics';
export interface SourceSnapshot { origin?: { path?: string; commit?: string }; digest?: string; coverage?: { files_read?: number; files_cited?: number; files_total: number; note: string }; evidence?: Record<string, { path: string; start: number; end: number; quote: string; sha256: string }> }
export interface PromotionRecord { id: string; title: string; status: string; archived: boolean; revision: number; data: Data; case_id?: string; case_ids?: string[]; topic_id?: string; channel_id?: string | null; platform?: string; source_snapshot?: SourceSnapshot }
export interface ActivityItem { id: string; title: string; detail: string; status: 'running' | 'completed' | 'failed' | 'stopped'; created_at: string; updated_at: string }
export interface Task { id: string; kind: string; status: string; applied: boolean; error: string; request: Data; result: Data; stage?: string; activity?: { items: ActivityItem[]; dropped: number }; created_at: string }
export interface Handoff { id: string; topic_id: string | null; source_type?: 'version' | 'topic' | 'materials'; platform: string; version_id: string | null; target_application_id: number; kind: string; url: string; status: string; target_id: string }
export interface ExplorationInput { case_ids: string[]; platform?: string; content_type?: string; goal?: string; direction?: string; audience?: string; requirements?: string }
export interface Destination { id: number; name: string; slug: string }
export const resources: Resource[] = ['cases', 'topics'];
export const platforms: Record<string, string> = { wechat: '公众号', xiaohongshu: '小红书', douyin: '抖音', moments: '朋友圈' };
export const channelApplications: Record<string, { slug: string; name: string }> = {
  wechat: { slug: 'wechat-viral-article', name: '公众号爆款写作' },
  xiaohongshu: { slug: 'write-image-text-copy', name: '图文文案' },
  douyin: { slug: 'write-short-video-copy', name: '短视频文案' },
  moments: { slug: 'write-image-text-copy', name: '图文文案' },
};
export const materialTypes: Record<string, string> = {
  "overview": "项目概览",
  "application_overview": "应用概览",
  "positioning": "项目定位",
  "audience": "适用人群",
  "scenario": "应用场景",
  "feature": "功能资料",
  "workflow": "工作流程",
  "case": "使用案例",
  "artifact": "成果样本",
  "quickstart": "快速上手",
  "integration": "集成对接",
  "customization": "定制扩展",
  "architecture": "技术实现",
  "deployment": "部署运维",
  "security": "安全隐私",
  "performance": "性能容量",
  "boundaries": "使用边界",
  "cost": "成本资源",
  "release": "版本变更",
  "development": "开发记录",
  "roadmap": "未来规划"
};
export const broadExplorationFocuses: Record<string, string> = {
  "all": "综合介绍",
  "user": "用户功能与流程",
  "technical": "技术实现与设计",
  "business": "业务定位与交付条件"
};
export const explorationFocusDescriptions: Record<string, string> = {
  "all": "全面梳理项目，根据实际资料选择有价值的素材类型",
  "user": "侧重用户角色、功能、使用场景和完整流程",
  "technical": "侧重架构、集成、扩展、运行条件及技术边界",
  "business": "侧重定位、适用对象、交付方式和资源条件",
  "overview": "整个项目的定位、应用或模块构成、协作关系与整体能力；不能用单个应用的介绍代替",
  "application_overview": "项目内一个具体应用的用途、适用用户、主要功能及输入输出；标题明确应用名称，不代表整个项目",
  "positioning": "解决的核心问题、价值主张与定位；不编造竞品优劣",
  "audience": "适合的用户、角色及使用前提，不虚构已有客户",
  "scenario": "适用的业务情境与任务；设想场景要标注，不冒充真实案例",
  "feature": "单项功能做什么、输入输出及能力范围",
  "workflow": "多个步骤或功能怎样协作完成任务",
  "case": "具体问题、解决过程和结果；演示与真实客户案例分开",
  "artifact": "项目实际产出的内容或文件样本，不编造产物或效果",
  "quickstart": "首次使用的准备条件与最短操作路径，只整理操作事实",
  "integration": "与外部工具、接口和数据的连接方式及条件",
  "customization": "现有配置、插件和二次开发能力；未实现扩展另列",
  "architecture": "模块职责、关键设计与技术协作方式",
  "deployment": "运行环境、部署方式、维护和故障处理条件",
  "security": "权限、数据处理与隐私机制；不把机制等同安全认证或合规结论",
  "performance": "已有性能与容量资料；区分设计目标和实测，缺少数据时不编造指标",
  "boundaries": "已知限制、不支持的情况及适用前提",
  "cost": "所需软硬件、外部服务与资源消耗；未知费用留空，不臆测价格",
  "release": "有变更记录的新增、调整与修复",
  "development": "已有开发过程、决策和经验记录，不臆测作者动机",
  "roadmap": "已有计划、TODO 或规划声明，明确尚未实现，不承诺交付日期"
};
export const explorationFocuses = { ...broadExplorationFocuses, ...materialTypes };
export function explorationCategoriesLabel(request: Data) {
  if (Array.isArray(request.material_types)) return request.material_types.map(key => materialTypes[String(key)] || String(key)).join('、');
  return explorationFocuses[string(request.exploration_focus) || 'all'] || '综合介绍';
}
export const materialType = (row: PromotionRecord) => string(row.data.material_type) || 'case';
export const sourceIds = (row: PromotionRecord) => row.case_ids?.length ? row.case_ids : row.case_id ? [row.case_id] : [];
export const directions: Record<string, string> = { overview: '项目介绍', application_overview: '应用介绍', audience: '适用人群', demo: '功能演示', solution: '问题解决', workflow: '完整流程', showcase: '成果展示', comparison: '对比取舍', tutorial: '上手技巧', architecture: '技术解读', boundaries: '使用边界', development: '开发演进', experience: '实践复盘' };
export const statuses: Record<string, string> = { draft: '待审核草稿', confirmed: '已确认' };
export const string = (value: unknown) => value == null ? '' : String(value);
export const activeTask = (task: Task) => ['queued', 'running', 'waiting_input', 'waiting_children', 'cancelling'].includes(task.status);
export function promotionError(error: unknown): string {
  const data = (error as { response?: { data?: unknown } })?.response?.data;
  return data ? typeof data === 'string' ? data : JSON.stringify(data) : error instanceof Error ? error.message : '操作失败，请重试。';
}
export function promotionApi(base: string) {
  let pending: { signature: string; key: string } | null = null;
  async function all<T>(resource: string): Promise<T[]> {
    const rows: T[] = []; let page: number | null = 1;
    while (page) {
      const result: { results: T[]; next: number | null } = await api.get(`${base}/${resource}`, { page });
      rows.push(...result.results); page = result.next;
    }
    return rows;
  }
  return {
    all,
    create: (kind: Resource, data: Data) => api.post<PromotionRecord>(`${base}/${kind}`, data),
    update: (kind: Resource, row: PromotionRecord, data: Data) => api.patch<PromotionRecord>(`${base}/${kind}/${row.id}`, { ...data, revision: row.revision }),
    start: async (value: Data) => {
      const signature = JSON.stringify(value);
      if (pending?.signature !== signature) pending = { signature, key: createIdempotencyKey('promotion') };
      const result = await api.post<Task>(`${base}/ai/tasks`, { ...value, request_key: pending.key });
      pending = null;
      return result;
    },
    apply: (id: string) => api.post<Task>(`${base}/ai/tasks/${id}/apply`),
    cancel: (id: string) => api.post<Task>(`${base}/ai/tasks/${id}/cancel`),
    destinations: () => api.get<Destination[]>(`${base}/integrations`),
    handoffs: () => api.get<Handoff[]>(`${base}/handoffs`),
    prepare: (topic: PromotionRecord, platform: string) => api.post<Handoff>(`${base}/handoffs`, { topic_id: topic.id, platform }),
    explore: (input: ExplorationInput) => api.post<Handoff>(`${base}/handoffs`, input),
  };
}
export type PromotionApi = ReturnType<typeof promotionApi>;
