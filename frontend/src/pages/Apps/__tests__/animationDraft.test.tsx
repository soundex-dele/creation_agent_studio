// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useStudioDraft } from '../animation/useStudioDraft';
import { newDocument, newScene, type ProjectClient, type StudioProject } from '@/services/animationProjects';

let root: Root; let host: HTMLDivElement; let hook: ReturnType<typeof useStudioDraft>;
const save = vi.fn(); const get = vi.fn(); const client = { save, get } as unknown as ProjectClient;
function Harness() { hook = useStudioDraft(client, 'org:app:user'); return <span>{hook.status}</span>; }
function project(id = 'one'): StudioProject { return { id, title: 'Test', archived: false, revision: 1, updated_at: '', draft: { ...newDocument(), scenes: [newScene()] } }; }
beforeEach(async () => {
  vi.clearAllMocks(); localStorage.clear();
  Object.defineProperty(globalThis, 'IS_REACT_ACT_ENVIRONMENT', { value: true, configurable: true });
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
  await act(async () => root.render(<Harness />));
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.useRealTimers(); });

describe('animation autosave and recovery', () => {
  it('saves after the debounce with the current revision and clears the local recovery copy', async () => {
    vi.useFakeTimers(); const p = project();
    await act(async () => hook.adopt(p));
    const document = { ...p.draft, prompt: 'changed' };
    save.mockResolvedValue({ ...p, revision: 2, draft: document });
    await act(async () => hook.change(document));
    expect(save).not.toHaveBeenCalled();
    expect(localStorage.getItem('animation-draft:org:app:user:one')).toContain('changed');
    await act(async () => vi.advanceTimersByTimeAsync(1000));
    expect(save).toHaveBeenCalledWith('one', 1, document);
    expect(localStorage.getItem('animation-draft:org:app:user:one')).toBeNull();
    expect(hook.project?.revision).toBe(2);
  });
  it('preserves local content on conflict and blocks navigation until resolution', async () => {
    const p = project(); await act(async () => hook.adopt(p));
    const document = { ...p.draft, prompt: 'local' }; await act(async () => hook.change(document));
    save.mockRejectedValue({ response: { status: 409, data: { detail: 'conflict' } } });
    let ok = true; await act(async () => { ok = await hook.flush(); });
    expect(ok).toBe(false); expect(hook.conflict).toBe(true); expect(hook.doc?.prompt).toBe('local');
    get.mockResolvedValue({ ...p, revision: 4, draft: { ...p.draft, prompt: 'server' } });
    await act(async () => hook.resolve(true));
    expect(hook.project?.revision).toBe(4); expect(hook.doc?.prompt).toBe('local');
  });
  it('does not replace edits when a background task refreshes the project', async () => {
    const p = project(); await act(async () => hook.adopt(p));
    await act(async () => hook.change({ ...p.draft, prompt: 'typing' }));
    await act(async () => hook.refresh({ ...p, revision: 2, draft: { ...p.draft, prompt: 'AI result' }, tasks: [] }));
    expect(hook.doc?.prompt).toBe('typing'); expect(hook.project?.revision).toBe(1);
  });
  it('waits for edits made during an in-flight save before allowing a project switch', async () => {
    const p = project(); await act(async () => hook.adopt(p));
    const first = { ...p.draft, prompt: 'first' }; const second = { ...p.draft, prompt: 'second' };
    await act(async () => hook.change(first));
    let finish!: (p: StudioProject) => void;
    save.mockImplementationOnce(() => new Promise<StudioProject>(resolve => { finish = resolve; })).mockResolvedValueOnce({ ...p, revision: 3, draft: second });
    let result!: Promise<boolean>; await act(async () => { result = hook.flush(); });
    await act(async () => hook.change(second));
    await act(async () => { finish({ ...p, revision: 2, draft: first }); await result; });
    expect(save).toHaveBeenLastCalledWith('one', 2, second);
    expect(hook.project?.revision).toBe(3);
  });
});
