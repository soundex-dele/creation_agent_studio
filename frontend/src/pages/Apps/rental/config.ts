import type { Resource } from '@/services/rentalGrowth';
export const platformLabels: Record<string, string> = { xiaohongshu: '小红书', douyin: '抖音', channels: '视频号', moments: '朋友圈', unknown: '未知来源' };
export const typeLabels: Record<string, string> = { property: '单套房源推荐', comparison: '多套房源对比', guide: '区域／预算攻略', qa: '租房问答与经验' };
export const statusLabels: Record<string, string> = { available: '待出租', rented: '已出租', paused: '暂缓', active: '使用中', new: '新咨询', qualified: '需求已确认', recommended: '已推荐', scheduled: '已约看', viewed: '已带看', won: '已成交', lost: '已流失', pending: '待跟进', done: '已完成', cancelled: '已取消', no_show: '未到场', draft: '草稿', planned: '待发布', published: '已发布' };
export const options = (labels: Record<string, string>) => Object.entries(labels).map(([value, label]) => ({ value, label }));
export const meta: Record<Resource, { label: string; statuses: string[] }> = {
  properties: { label: '房源', statuses: ['available', 'rented', 'paused'] }, personas: { label: '租客画像', statuses: ['active'] },
  leads: { label: '客户', statuses: ['new', 'qualified', 'recommended', 'scheduled', 'viewed', 'won', 'paused', 'lost'] },
  followups: { label: '跟进', statuses: ['pending', 'done', 'cancelled'] }, viewings: { label: '带看', statuses: ['scheduled', 'done', 'cancelled', 'no_show'] },
  contents: { label: '内容', statuses: ['draft'] }, publications: { label: '发布记录', statuses: ['draft', 'planned', 'published', 'cancelled'] },
};
export interface Field { key: string; label: string; type?: 'text' | 'long' | 'number' | 'date' | 'time' | 'tags' | 'select' | 'multi' | 'photos' | 'conditions'; options?: Record<string, string>; resource?: Resource; required?: boolean; help?: string }
const rentalTypes = { '': '待确认', whole: '整租', shared: '合租' };
const yesNo = { unknown: '待确认', yes: '是', no: '否' };
export const requirementFields: Field[] = [
  { key: 'budget_min', label: '最低预算（元／月）', type: 'number' }, { key: 'budget_max', label: '最高预算（元／月）', type: 'number' },
  { key: 'city', label: '城市' }, { key: 'districts', label: '意向片区', type: 'tags' },
  { key: 'rental_type', label: '出租方式', type: 'select', options: rentalTypes }, { key: 'layout', label: '意向户型' },
  { key: 'move_in', label: '希望入住日期', type: 'date' }, { key: 'must_have', label: '必要条件', type: 'tags', help: '电梯、可养宠可直接匹配；其他条件与房源中的自定义条件名称保持一致。' },
  { key: 'needs', label: '生活需求', type: 'long' }, { key: 'concerns', label: '主要关注点', type: 'long' },
];
export const fields: Record<Resource, Field[]> = {
  properties: [
    { key: 'city', label: '城市' }, { key: 'district', label: '片区' }, { key: 'location', label: '小区／位置' },
    { key: 'rent', label: '月租（元）', type: 'number' }, { key: 'rental_type', label: '出租方式', type: 'select', options: rentalTypes },
    { key: 'layout', label: '户型' }, { key: 'area', label: '面积（㎡）', type: 'number' }, { key: 'floor', label: '楼层' },
    { key: 'elevator', label: '有电梯', type: 'select', options: yesNo }, { key: 'pets', label: '允许养宠', type: 'select', options: yesNo },
    { key: 'available_from', label: '可入住日期', type: 'date' }, { key: 'transport', label: '交通情况', type: 'long' },
    { key: 'amenities', label: '家具与配置', type: 'long' }, { key: 'fees', label: '押付／中介费／其他费用', type: 'long' },
    { key: 'strengths', label: '真实卖点', type: 'long' }, { key: 'drawbacks', label: '不足与限制', type: 'long' },
    { key: 'conditions', label: '自定义条件', type: 'conditions', help: '每行：条件名称=是／否／待确认，例如 独立厨房=是。' },
    { key: 'photos', label: '实拍照片清单', type: 'photos', help: '每行一张：照片名称 | 备注。允许多张卧室照片；不会上传或分析图片。' },
  ],
  personas: requirementFields,
  leads: [
    { key: 'contact', label: '联系方式（可选）' }, { key: 'platform', label: '咨询平台', type: 'select', options: platformLabels },
    { key: 'source_id', label: '主要来源作品', type: 'select', resource: 'publications' },
    { key: 'consulted_on', label: '首次咨询日期', type: 'date', required: true }, ...requirementFields,
    { key: 'property_ids', label: '意向房源', type: 'multi', resource: 'properties' }, { key: 'notes', label: '客户备注', type: 'long' },
    { key: 'deal_date', label: '成交日期', type: 'date' }, { key: 'deal_property_id', label: '成交房源', type: 'select', resource: 'properties' },
  ],
  followups: [
    { key: 'due_date', label: '跟进日期', type: 'date', required: true }, { key: 'summary', label: '沟通摘要', type: 'long' },
    { key: 'outcome', label: '沟通结果', type: 'long' }, { key: 'next_step', label: '下一步', type: 'long' }, { key: 'next_due_date', label: '下次跟进日期', type: 'date', help: '本条标记完成时，自动创建下一条待跟进事项。' },
  ],
  viewings: [
    { key: 'scheduled_at', label: '预约时间', type: 'time', required: true }, { key: 'property_ids', label: '带看房源', type: 'multi', resource: 'properties', required: true },
    { key: 'meeting_place', label: '集合地点' }, { key: 'notes', label: '预约备注', type: 'long' },
    { key: 'feedback', label: '带看反馈', type: 'long' }, { key: 'next_step', label: '下一步', type: 'long' },
  ],
  contents: [
    { key: 'platform', label: '发布平台', type: 'select', options: Object.fromEntries(Object.entries(platformLabels).filter(([k]) => k !== 'unknown')) },
    { key: 'content_type', label: '内容类型', type: 'select', options: typeLabels },
    { key: 'property_ids', label: '关联房源', type: 'multi', resource: 'properties' }, { key: 'persona_id', label: '目标画像', type: 'select', resource: 'personas' },
    { key: 'planned_date', label: '计划创作日期', type: 'date' }, { key: 'angle', label: '表达角度／资料', type: 'long' },
  ],
  publications: [
    { key: 'scheduled_date', label: '计划发布日期', type: 'date' }, { key: 'published_at', label: '实际发布时间', type: 'time' },
    { key: 'url', label: '作品链接（可选）' }, { key: 'notes', label: '发布备注', type: 'long' },
  ],
};
