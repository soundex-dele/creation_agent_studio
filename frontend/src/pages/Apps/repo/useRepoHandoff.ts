import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '@/services/api';
import { repoError, type RepoHandoff } from '@/services/repoExplainer';

/** A server-backed form draft: no content or filesystem path in the navigation URL. */
export function useRepoHandoff(url: string, enabled: boolean, answers: Record<string, unknown>, onLoad: (draft: Record<string, string>) => void) {
  const [ready, setReady] = useState(!url);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const loaded = useRef<RepoHandoff>();
  const latest = useRef(answers); latest.current = answers;
  const stopped = useRef(false); const conversation = useRef<string>();
  const conflict = useRef(false);
  const flight = useRef<Promise<void>>();
  useEffect(() => {
    if (!url || !enabled) return;
    let active = true;
    setReady(false); setError(''); loaded.current = undefined;
    void api.get<RepoHandoff>(url).then(value => {
      if (!active) return;
      loaded.current = value; onLoad(value.draft); setReady(true);
    }).catch(e => { if (active) setError(repoError(e)); });
    return () => { active = false; };
  }, [url, enabled, onLoad]);
  const flush = useCallback(async () => {
    if (!url) return;
    if (!loaded.current) throw new Error('制作草稿尚未载入。');
    if (stopped.current) throw new Error('制作草稿保存失败，请先重试或重新载入。');
    if (flight.current) return flight.current;
    const work = async () => {
      setSaving(true);
      try {
        while (loaded.current) {
          const snapshot = loaded.current;
          const draft = Object.fromEntries(Object.keys(snapshot.draft).map(key => [key, String(latest.current[key] ?? snapshot.draft[key])]));
          const attach = conversation.current;
          if (JSON.stringify(draft) === JSON.stringify(snapshot.draft) && !attach) break;
          const next = await api.patch<RepoHandoff>(url, { revision: snapshot.revision, draft, ...(attach ? { conversation_id: attach } : {}) });
          loaded.current = next;
          if (conversation.current === attach) conversation.current = undefined;
        }
        setError('');
      } catch (e) {
        stopped.current = true;
        conflict.current = (e as { response?: { status?: number } }).response?.status === 409;
        setError(repoError(e)); throw e;
      }
      finally { setSaving(false); }
    };
    // Set the flight before work starts, even when no update is needed.
    flight.current = Promise.resolve().then(work).finally(() => { flight.current = undefined; });
    return flight.current;
  }, [url]);
  const signature = JSON.stringify(answers);
  useEffect(() => {
    if (!url || !ready || stopped.current) return;
    const timer = setTimeout(() => { void flush().catch(() => undefined); }, 800);
    return () => clearTimeout(timer);
  }, [url, ready, signature, flush]);
  const attach = async (id: string) => { conversation.current = id; await flush(); };
  const retry = async () => {
    if (!loaded.current) {
      const value = await api.get<RepoHandoff>(url);
      loaded.current = value; onLoad(value.draft); setReady(true); setError('');
      return;
    }
    stopped.current = false; await flush();
  };
  const resolveConflict = async (keepLocal: boolean) => {
    const value = await api.get<RepoHandoff>(url);
    loaded.current = value; stopped.current = false; conflict.current = false; setError('');
    if (keepLocal) await flush();
    else { latest.current = value.draft; onLoad(value.draft); }
  };
  return { ready, error, saving, flush, attach, retry, hasConflict: conflict.current, resolveConflict };
}
