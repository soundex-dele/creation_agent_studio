// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AccountAnalysisExport } from '../douyin/AccountAnalysisExport';
import { douyinApi, type DouyinTask } from '@/services/douyinBenchmark';
import { api } from '@/services/api';
import { saveResearchBlob } from '@/services/researchAssistant';

vi.mock('@/services/api', () => ({ api: { get: vi.fn() } }));
vi.mock('@/services/researchAssistant', () => ({ saveResearchBlob: vi.fn() }));
const account = { id: 'a1', name: '知识/账号:*', source_url: '', group: '', notes: '', profile: {}, updated_at: '' };
const task: DouyinTask = { id: '12345678-task', kind: 'account', status: 'succeeded', stage: 'completed',
  work_id: null, run_id: 'r1', error: '', created_at: '2026-10-08T01:00:00Z', progress: {}, sources: [],
  output: { claims: [{ type: 'observation', text: '事实', refs: ['w1'] }] } };
let container: HTMLDivElement; let root: Root;
beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
async function render(value = task) {
  await act(async () => root.render(<AccountAnalysisExport key={value.id} client={douyinApi('/dy')} account={account} task={value} />));
}
async function click() { await act(async () => container.querySelector('button')!.click()); }

describe('account analysis export', () => {
  it.each(['queued', 'running', 'failed', 'cancelled'])('does not download %s tasks', async status => {
    await render({ ...task, status }); await click();
    expect(container.querySelector('button')!.disabled).toBe(true);
    expect(api.get).not.toHaveBeenCalled();
  });
  it('does not download empty results or other task kinds', async () => {
    await render({ ...task, output: {} }); await click();
    await render({ ...task, kind: 'breakdown' }); await click();
    expect(api.get).not.toHaveBeenCalled();
  });
  it('downloads the selected report once and sanitizes its filename', async () => {
    let resolve!: (blob: Blob) => void;
    vi.mocked(api.get).mockReturnValue(new Promise<Blob>(done => { resolve = done; }));
    await render();
    await act(async () => { container.querySelector('button')!.click(); container.querySelector('button')!.click(); });
    expect(api.get).toHaveBeenCalledTimes(1);
    expect(api.get).toHaveBeenCalledWith('/dy/accounts/a1/tasks/12345678-task/download', undefined, { responseType: 'blob' });
    expect(container.querySelector('button')!.disabled).toBe(true);
    const blob = new Blob(['# 报告']);
    await act(async () => resolve(blob));
    expect(saveResearchBlob).toHaveBeenCalledWith(blob, '知识_账号__-账号分析-2026-10-08-12345678.md');
    expect(container.querySelector('button')!.disabled).toBe(false);
  });
  it('shows blob API errors and allows retry', async () => {
    const error = new Blob(['{"detail":"分析已不可用"}'], { type: 'application/json' });
    Object.defineProperty(error, 'text', { value: async () => '{"detail":"分析已不可用"}' });
    vi.mocked(api.get).mockRejectedValueOnce({ response: { data: error } }).mockResolvedValueOnce(new Blob(['ok']));
    await render(); await click();
    expect(container.textContent).toContain('分析已不可用');
    expect(saveResearchBlob).not.toHaveBeenCalled();
    await click();
    expect(api.get).toHaveBeenCalledTimes(2);
    expect(saveResearchBlob).toHaveBeenCalledTimes(1);
    expect(container.textContent).not.toContain('分析已不可用');
  });
  it('shows useful errors for network and non-JSON failures', async () => {
    vi.mocked(api.get).mockRejectedValueOnce(new Error('网络中断')).mockRejectedValueOnce({ response: { data: new Blob(['<html>error</html>']) } });
    await render(); await click(); expect(container.textContent).toContain('网络中断');
    await click(); expect(container.textContent).toContain('导出失败，请稍后重试');
  });
});
