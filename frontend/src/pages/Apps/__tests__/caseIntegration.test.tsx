// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '@/services/api';
import { douyinApi } from '@/services/douyinBenchmark';
import { SaveCaseButton, CasePicker } from '../douyin/CaseIntegration';
import CaseCreationAction from '@/pages/Templates/CaseCreationAction';

vi.mock('@/services/api', () => ({ api: { get: vi.fn(), post: vi.fn() } }));
let container: HTMLDivElement; let root: Root;
const preview = { case_id: null, task_id: 't1', title: '来源作品', category: null, summary: '摘要', tags: [], source_content: '完整转写', analysis_sections: [{ title: '初步推测', content: '拆解结论' }] };
beforeEach(() => {
  vi.clearAllMocks(); vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn(), addListener: vi.fn(), removeListener: vi.fn() })));
  const style = window.getComputedStyle; vi.spyOn(window, 'getComputedStyle').mockImplementation(el => style(el));
  vi.mocked(api.get).mockImplementation(async url => url.endsWith('/case') ? preview : []);
  vi.mocked(api.post).mockResolvedValue({ case_id: 41, result: 'created' });
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
function Location() { return <output>{useLocation().pathname}{useLocation().search}</output>; }
async function render(node: React.ReactNode, entry = '/?embedded=1&entry=home') {
  await act(async () => root.render(<MemoryRouter initialEntries={[entry]}>{node}<Location /></MemoryRouter>));
}
async function click(label: string) {
  const button = [...document.querySelectorAll<HTMLButtonElement>('button')].find(b => b.textContent?.replace(/\s/g, '') === label.replace(/\s/g, ''));
  expect(button, label).toBeDefined(); await act(async () => button!.click());
}

describe('Saving a case', () => {
  it('previews text, saves the chosen task, and opens the new case preserving presentation', async () => {
    await render(<SaveCaseButton client={douyinApi('/dy')} workId="w1" taskId="t1" />);
    expect(api.get).not.toHaveBeenCalled();
    await click('存入案例库');
    expect(api.get).toHaveBeenCalledWith('/dy/works/w1/case', { task_id: 't1' });
    expect(document.body.textContent).toContain('仅本人可见');
    expect(document.body.textContent).toContain('完整转写');
    await click('保存案例');
    expect(api.post).toHaveBeenCalledWith('/dy/works/w1/case', expect.objectContaining({ action: 'save', task_id: 't1', title: '来源作品' }), expect.anything());
    await click('查看案例');
    expect(container.querySelector('output')?.textContent).toContain('/apps/case-library/41');
    expect(container.querySelector('output')?.textContent).toContain('embedded=1');
  });

  it('offers explicit updating for an existing case and does not send editable metadata', async () => {
    vi.mocked(api.get).mockImplementation(async url => url.endsWith('/case') ? { ...preview, case_id: 41 } : []);
    await render(<SaveCaseButton client={douyinApi('/dy')} workId="w1" />);
    await click('存入案例库');
    expect(document.body.textContent).toContain('保留你填写的标题');
    const buttons = [...document.querySelectorAll<HTMLButtonElement>('.ant-modal button')];
    const update = buttons.find(b => b.textContent?.replace(/\s/g, '') === '更新来源内容')!;
    await act(async () => update.click());
    expect(vi.mocked(api.post).mock.calls[0][1]).toEqual({ action: 'update', task_id: 't1' });
  });

  it.each(['missing', 'throwing', 'absent'])('retries saving in simulated phone HTTP with crypto %s', async mode => {
    vi.stubGlobal('crypto', mode === 'absent' ? undefined : mode === 'missing' ? {} : { randomUUID: () => { throw new Error('Insecure context'); } });
    vi.mocked(api.post).mockRejectedValueOnce(new Error('Network Error')).mockResolvedValue({ case_id: 41 });
    await render(<SaveCaseButton client={douyinApi('/dy')} workId="w1" />);
    await click('存入案例库'); await click('保存案例');
    expect(document.body.textContent).toContain('Network Error');
    await click('保存案例');
    expect(vi.mocked(api.post).mock.calls[0][2]).toEqual(vi.mocked(api.post).mock.calls[1][2]);
  });
});

describe('Choosing a creative destination', () => {
  it('opens the only available assistant without submitting a task', async () => {
    vi.mocked(api.get).mockResolvedValue([{ id: 7, name: '抖音助手' }]);
    await render(<CaseCreationAction caseId={41} />, '/?standalone=1');
    await click('用于创作');
    expect(container.querySelector('output')?.textContent).toContain('/applications/7/douyin-benchmark?');
    expect(container.querySelector('output')?.textContent).toContain('case=41');
    expect(container.querySelector('output')?.textContent).toContain('standalone=1');
    expect(api.post).not.toHaveBeenCalled();
  });
  it.each([{ targets: [] }, { targets: [{ id: 7, name: '助手一' }, { id: 8, name: '助手二' }] }])('handles zero or multiple applications', async ({ targets }) => {
    vi.mocked(api.get).mockResolvedValue(targets);
    await render(<CaseCreationAction caseId={41} />); await click('用于创作');
    expect(document.body.textContent).toContain(targets.length ? '目标应用' : '暂无你可运行');
    expect(container.querySelector('output')?.textContent).not.toContain('/applications/');
  });
});

it('searches cases, limits the selection to three and allows removal', async () => {
  vi.mocked(api.get).mockResolvedValue({ count: 1, results: [{ id: 44, title: '第四个案例', status: 'published' }] });
  const selected = [1, 2, 3].map(id => ({ id, title: `案例${id}` })); const onChange = vi.fn();
  await render(<CasePicker selected={selected} onChange={onChange} />);
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 350)); });
  expect([...container.querySelectorAll<HTMLButtonElement>('button')].find(b => b.textContent === '选择案例')?.disabled).toBe(true);
  await act(async () => (container.querySelector('.ant-tag-close-icon') as HTMLElement).click());
  expect(onChange).toHaveBeenCalledWith(selected.slice(1));
});
