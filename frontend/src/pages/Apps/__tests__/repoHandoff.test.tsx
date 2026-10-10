// @vitest-environment jsdom
import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '@/services/api';
import { useRepoHandoff } from '../repo/useRepoHandoff';

vi.mock('@/services/api', () => ({ api: { get: vi.fn(), patch: vi.fn() } }));
let root: Root; let container: HTMLDivElement;
let state: ReturnType<typeof useRepoHandoff>;
let update: (draft: Record<string, string>) => void;
let stored: { id: string; kind: string; revision: number; draft: Record<string, string>; target_id: string };
function Harness() {
  const [answers, setAnswers] = useState<Record<string, string>>({ source: '' });
  update = setAnswers;
  state = useRepoHandoff('/handoff', true, answers, setAnswers);
  return <span>{answers.source}</span>;
}
beforeEach(() => {
  vi.useFakeTimers(); vi.clearAllMocks();
  Object.defineProperty(globalThis, 'IS_REACT_ACT_ENVIRONMENT', { configurable: true, value: true });
  stored = { id: 'h', kind: 'jianying', revision: 1, draft: { source: '固定版本文案' }, target_id: '' };
  vi.mocked(api.get).mockImplementation(async () => structuredClone(stored));
  vi.mocked(api.patch).mockImplementation(async (_url, body) => {
    const data = body as { revision: number; draft: Record<string, string>; conversation_id?: string };
    expect(data.revision).toBe(stored.revision);
    stored = { ...stored, revision: stored.revision + 1, draft: data.draft, target_id: data.conversation_id || stored.target_id };
    return structuredClone(stored);
  });
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); vi.useRealTimers(); vi.restoreAllMocks(); });
describe('persistent Jianying handoff', () => {
  it('restores source, saves edits and restores them after remount', async () => {
    await act(async () => root.render(<Harness />));
    expect(container.textContent).toBe('固定版本文案');
    await act(async () => update({ source: '在制作页修改' }));
    await act(async () => { await vi.advanceTimersByTimeAsync(900); });
    expect(stored.draft.source).toBe('在制作页修改');
    await act(async () => root.unmount()); root = createRoot(container);
    await act(async () => root.render(<Harness />));
    expect(container.textContent).toBe('在制作页修改');
    await act(async () => state.attach('42'));
    expect(stored.target_id).toBe('42');
  });
  it('keeps local text after conflict and does not silently overwrite it', async () => {
    await act(async () => root.render(<Harness />));
    vi.mocked(api.patch).mockRejectedValueOnce({ response: { status: 409, data: { detail: '冲突' } } });
    await act(async () => update({ source: '保留本地文本' }));
    await act(async () => { await vi.advanceTimersByTimeAsync(900); });
    expect(container.textContent).toBe('保留本地文本');
    expect(state.error).toBe('冲突');
    expect(stored.draft.source).toBe('固定版本文案');
    await expect(state.flush()).rejects.toThrow('保存失败');
  });
});
