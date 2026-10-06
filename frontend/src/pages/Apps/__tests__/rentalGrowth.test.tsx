// @vitest-environment jsdom
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { ConfigProvider } from 'antd';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { api } from '@/services/api';
import { dayInZone, localTime, utcTime, type CopyBody, type RentalRecord } from '@/services/rentalGrowth';
import { RentalGrowthWorkspace } from '../RentalGrowthPage';

vi.mock('@/services/api', () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn() } }));
let root: Root; let container: HTMLDivElement;
const base = '/rental';
const property: RentalRecord = { id: 'p1', title: '梧桐公寓', revision: 0, status: 'available', archived: false, data: { city: '上海', district: '徐汇', rent: 2800, rental_type: 'whole', layout: '一室一厅', photos: [{ label: '客厅', note: '实拍' }] }, created_at: '2026-10-05', updated_at: '2026-10-05' };
const lead: RentalRecord = { ...property, id: 'l1', title: '小林', status: 'new', data: { consulted_on: '2026-10-05', contact: 'wx', budget_max: 3000 } };
const body: CopyBody = { titles: ['真实房源'], cover: '一室一厅', body: '月租2800元，临街有噪声。', pages: [{ photo_ref: 'p1:1', caption: '客厅', layout: '有留白时放标题' }], tags: ['租房'], checks: ['中介费待确认'], script: '', shots: [] };
const content: RentalRecord = { ...property, id: 'c1', title: '真实房源', status: 'draft', data: { platform: 'xiaohongshu', content_type: 'property', property_ids: ['p1'] }, latest_version: { id: 'v1', content_id: 'c1', number: 1, body, snapshot: {}, created_at: '2026-10-05' } };
const rows: Record<string, RentalRecord[]> = {};
const counts = { leads: 0, viewed: 0, won: 0, viewing_rate: null, deal_rate: null };
const settle = async () => act(async () => { await new Promise(resolve => setTimeout(resolve, 20)); });
const button = (text: string) => [...document.querySelectorAll<HTMLButtonElement>('button')].find(b => b.textContent?.replace(/\s/g, '') === text.replace(/\s/g, ''))!;
const click = async (text: string) => { expect(button(text)).toBeDefined(); await act(async () => button(text).click()); await settle(); };
async function input(id: string, value: string) {
  const field = document.getElementById(id) as HTMLInputElement;
  expect(field).not.toBeNull();
  await act(async () => { Object.getOwnPropertyDescriptor(field.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype, 'value')!.set!.call(field, value); field.dispatchEvent(new Event('input', { bubbles: true })); });
}
async function render() {
  await act(async () => root.render(createElement(MemoryRouter, {}, createElement(ConfigProvider, { theme: { token: { motion: false } } }, createElement(RentalGrowthWorkspace, { base })))));
  await settle();
}
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} })));
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
  Object.defineProperty(HTMLElement.prototype, 'scrollTo', { configurable: true, value: vi.fn() });
  const computed = window.getComputedStyle.bind(window); vi.spyOn(window, 'getComputedStyle').mockImplementation(el => computed(el));
  Object.keys(rows).forEach(k => delete rows[k]);
  Object.assign(rows, { properties: [property], leads: [lead], contents: [content] });
  vi.mocked(api.get).mockImplementation(async (url: string) => {
    if (url.endsWith('/settings')) return { timezone: 'Asia/Shanghai', platform: 'xiaohongshu', voice: '自然' };
    if (url.includes('/overview/reports')) return { summary: counts, unknown: counts, groups: {}, publications: [], note: '按客户去重' };
    if (url.includes('/overview/')) return { today: '2026-10-05', events: [], attention: [], property_count: 1 };
    if (url.endsWith('/versions')) return [content.latest_version];
    if (url.endsWith('/matches')) return { matched: [{ property, reasons: ['预算符合'], unknown: [], conflicts: [] }], unknown: [], conflicts: [] };
    if (url.endsWith('/ai/tasks')) return { results: [], next: null, count: 0 };
    const result = rows[url.split('/').pop()!] || [];
    return { results: result, next: null, count: result.length };
  });
  vi.mocked(api.post).mockResolvedValue(property); vi.mocked(api.patch).mockResolvedValue(property);
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: vi.fn().mockResolvedValue(undefined) } });
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); vi.restoreAllMocks(); vi.resetAllMocks(); vi.unstubAllGlobals(); });

it('opens all six modules and preserves the bounded scrolling root', async () => {
  await render();
  expect(container.querySelector('.rental-page.app-scroll-page')).not.toBeNull();
  for (const tab of ['房源', '创作', '客户', '日历', '复盘', '今日']) await click(tab);
  expect(container.textContent).toContain('今天联系谁');
});

it('retains a failed property form and serializes the photo checklist without uploading', async () => {
  await render(); await click('新增房源'); await input('rental-title', '新公寓'); await input('rental-photos', '卧室 | 靠窗\n卧室 | 衣柜');
  vi.mocked(api.post).mockRejectedValueOnce(new Error('网络失败'));
  await click('保存'); expect(document.querySelector('#rental-title')).not.toBeNull(); expect((document.getElementById('rental-title') as HTMLInputElement).value).toBe('新公寓');
  await click('保存');
  expect(api.post).toHaveBeenLastCalledWith(`${base}/properties`, expect.objectContaining({ title: '新公寓', data: expect.objectContaining({ photos: [{ label: '卧室', note: '靠窗' }, { label: '卧室', note: '衣柜' }] }) }));
});

it.each(['native', 'missing', 'throws', 'no crypto'])('submits copy tasks and preserves retry keys when randomUUID is %s', async mode => {
  if (mode !== 'native') {
    vi.stubGlobal('crypto', mode === 'no crypto' ? undefined : {
      randomUUID: mode === 'missing' ? undefined : () => { throw new Error('Secure context required'); },
    });
  }
  await render(); await click('房源'); await click('用这套房创作');
  vi.mocked(api.post).mockRejectedValueOnce(new Error('response lost'));
  await click('生成发布文案');
  expect(api.post).toHaveBeenCalledTimes(1);
  const first = vi.mocked(api.post).mock.calls[vi.mocked(api.post).mock.calls.length - 1]?.[1] as Record<string, unknown>;
  expect(first).toMatchObject({ kind: 'copy', platform: 'xiaohongshu', property_ids: ['p1'] });
  expect(first.request_key).toEqual(expect.any(String));
  expect((first.request_key as string).length).toBeGreaterThan(0);
  expect((first.request_key as string).length).toBeLessThanOrEqual(160);
  vi.mocked(api.post).mockResolvedValueOnce({ id: 'task1', kind: 'copy', status: 'failed', result: {}, request: first, created_at: '2026-10-05' });
  await click('生成发布文案');
  expect(api.post).toHaveBeenCalledTimes(2);
  expect((vi.mocked(api.post).mock.calls[vi.mocked(api.post).mock.calls.length - 1]?.[1] as Record<string, unknown>).request_key).toBe(first.request_key);
  expect(container.textContent).toContain('任务已提交');
  vi.mocked(api.post).mockResolvedValueOnce({ id: 'task2', kind: 'copy', status: 'failed', result: {}, request: {}, created_at: '2026-10-05' });
  await click('生成发布文案');
  expect(api.post).toHaveBeenCalledTimes(3);
  expect((vi.mocked(api.post).mock.calls[2][1] as Record<string, unknown>).request_key).not.toBe(first.request_key);
});

it('initializes built-in personas before listing and uses a selected persona in copy creation', async () => {
  const persona = { ...property, id: 'persona-pet', title: '需要养宠的租客', status: 'active', data: { needs: '带宠物一起入住', concerns: '宠物种类、押金和清洁要求', must_have: ['可养宠'] } };
  let finishInitialization!: (value: unknown) => void;
  vi.mocked(api.put).mockImplementationOnce(() => new Promise(resolve => { finishInitialization = resolve; }));
  await render();
  expect(api.put).toHaveBeenCalledWith(`${base}/personas/built-ins`, {});
  expect(vi.mocked(api.get).mock.calls.some(([url]) => url === `${base}/personas`)).toBe(false);
  rows.personas = [persona];
  await act(async () => finishInitialization({ created: 8 })); await settle();
  await click('房源'); await click('目标租客画像'); await click('用这个画像创作');
  expect(container.querySelector('.rental-composer')?.textContent).toContain(persona.data.concerns);
  expect(document.activeElement).toBe(button('生成发布文案'));
  expect(api.post).not.toHaveBeenCalled();
  vi.mocked(api.post).mockResolvedValueOnce({ id: 'persona-copy', kind: 'copy', status: 'failed', result: {}, request: {}, created_at: '2026-10-05' });
  await click('生成发布文案');
  expect(api.post).toHaveBeenCalledWith(`${base}/ai/tasks`, expect.objectContaining({ kind: 'copy', persona_id: persona.id, property_ids: [] }));
});

it('copies only public text and requires saved versions before scheduling', async () => {
  await render(); await click('创作'); await click('编辑文案');
  await click('复制文案'); expect(navigator.clipboard.writeText).toHaveBeenCalledWith('真实房源\n\n月租2800元，临街有噪声。\n\n租房');
  expect(api.post).not.toHaveBeenCalled();
  await input('rental-copy-body', '编辑后的正文');
  expect(button('安排发布').disabled).toBe(true); expect(button('导出 Markdown').disabled).toBe(true);
  vi.mocked(api.post).mockResolvedValueOnce({ ...content.latest_version, id: 'v2', number: 2, body: { ...body, body: '编辑后的正文' } });
  await click('保存新版本'); await click('安排发布');
  expect(document.querySelector('#rental-version')).not.toBeNull();
  expect(api.post).toHaveBeenCalledTimes(1);
});

it('shows matched evidence and sends extraction as a draft without changing customer data', async () => {
  await render(); await click('客户'); await click('咨询与匹配');
  expect(container.textContent).toContain('预算符合');
  await input('reply-text', '需要养猫，预算3000');
  vi.mocked(api.post).mockResolvedValueOnce({ id: 'extract1', kind: 'extract', status: 'succeeded', result: { requirements: { budget_max: 3000 } }, request: { lead_id: 'l1' }, created_at: '2026-10-05' });
  await click('提取需求草稿');
  expect(api.post).toHaveBeenCalledWith(`${base}/ai/tasks`, expect.objectContaining({ kind: 'extract', lead_id: 'l1', instruction: '需要养猫，预算3000' }));
  expect(api.patch).not.toHaveBeenCalled();
});

it('converts calendar input in configured timezone independent of machine timezone', () => {
  expect(dayInZone('Asia/Shanghai', new Date('2026-10-05T17:00:00Z'))).toBe('2026-10-06');
  expect(localTime('2026-10-05T17:30:00Z', 'Asia/Shanghai')).toBe('2026-10-06T01:30');
  expect(utcTime('2026-10-06T01:30', 'Asia/Shanghai')).toBe('2026-10-05T17:30:00.000Z');
});
