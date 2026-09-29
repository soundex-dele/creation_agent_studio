import { useCallback, useEffect, useRef, useState } from 'react';
import type { ProjectClient, StudioDocument, StudioProject } from '@/services/animationProjects';
import { animationError } from '@/services/animationStudio';

export function useStudioDraft(client: ProjectClient, scope: string) {
  const [project, setProject] = useState<StudioProject>(); const [doc, setDoc] = useState<StudioDocument>();
  const [status, setStatus] = useState(''); const [conflict, setConflict] = useState(false);
  const current = useRef<{ project: StudioProject; doc: StudioDocument; dirty: boolean }>(); const flight = useRef<Promise<boolean>>(); const live = useRef(true); const blocked = useRef(false);
  const key = useCallback((id: string) => `animation-draft:${scope}:${id}`, [scope]);
  useEffect(() => { live.current = true; return () => { live.current = false; }; }, []);
  const cache = useCallback(() => {
    const c = current.current; if (!c || !c.dirty) return;
    try { localStorage.setItem(key(c.project.id), JSON.stringify({ revision: c.project.revision, document: c.doc })); } catch { if (live.current) setStatus('本地空间不足，请保持页面打开并重试保存。'); }
  }, [key]);
  const adopt = useCallback((p: StudioProject) => {
    let restored = p.draft; let dirty = false; let collision = false;
    try { const value = JSON.parse(localStorage.getItem(key(p.id)) || 'null'); if (value?.document?.schema_version === 2) { restored = value.document; dirty = true; collision = value.revision !== p.revision; } } catch { /* invalid local cache does not replace the server */ }
    current.current = { project: p, doc: restored, dirty }; blocked.current = collision;
    setProject(p); setDoc(restored); setConflict(collision); setStatus(collision ? '发现本地恢复副本与服务器冲突，请选择保留哪份。' : dirty ? '已恢复未保存草稿' : '已保存');
  }, [key]);
  const change = useCallback((document: StudioDocument) => {
    const c = current.current; if (!c) return;
    current.current = { ...c, doc: document, dirty: true }; setDoc(document); setStatus('尚未保存'); cache();
  }, [cache]);
  const flush = useCallback(async function flushDraft(): Promise<boolean> {
    if (flight.current) { const ok = await flight.current; if (!ok) return false; }
    if (blocked.current) return false;
    const c = current.current; if (!c || !c.dirty || c.doc.schema_version !== 2) return true;
    setStatus('正在保存…');
    const saving = client.save(c.project.id, c.project.revision, c.doc).then(p => {
      if (!live.current || current.current?.project.id !== c.project.id) return true;
      const dirty = current.current.doc !== c.doc;
      current.current = { project: { ...current.current.project, ...p }, doc: current.current.doc, dirty };
      setProject(current.current.project); setStatus(dirty ? '尚未保存' : '已保存');
      if (!dirty) localStorage.removeItem(key(p.id)); else cache();
      return true;
    }).catch(e => {
      if (live.current) { if ((e as { response?: { status?: number } }).response?.status === 409) { blocked.current = true; setConflict(true); } setStatus(animationError(e)); cache(); }
      return false;
    });
    flight.current = saving;
    let ok = false;
    try { ok = await saving; } finally { if (flight.current === saving) flight.current = undefined; }
    return ok && current.current?.dirty ? flushDraft() : ok;
  }, [cache, client, key]);
  useEffect(() => {
    if (!doc || blocked.current) return;
    const timer = setTimeout(() => { void flush(); }, 1000); return () => clearTimeout(timer);
  }, [doc, project?.revision, flush]);
  useEffect(() => {
    const leave = (e: BeforeUnloadEvent) => { if (current.current?.dirty) { cache(); e.preventDefault(); e.returnValue = ''; } };
    window.addEventListener('beforeunload', leave); return () => { cache(); window.removeEventListener('beforeunload', leave); };
  }, [cache]);
  const resolve = useCallback(async (keepLocal: boolean) => {
    const c = current.current; if (!c) return;
    const latest = await client.get(c.project.id); localStorage.removeItem(key(latest.id));
    blocked.current = false; setConflict(false); adopt(latest);
    if (keepLocal) change(c.doc);
  }, [client, key, adopt, change]);
  const refresh = useCallback((p: StudioProject) => {
    const c = current.current; if (!c || c.project.id !== p.id) return;
    if (c.dirty || flight.current) {
      const updated = { ...c.project, versions: p.versions, tasks: p.tasks, title: p.title, archived: p.archived };
      current.current = { ...c, project: updated }; setProject(updated);
    } else adopt(p);
  }, [adopt]);
  return { project, doc, status, conflict, adopt, change, flush, resolve, refresh, current };
}
