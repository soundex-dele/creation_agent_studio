import { useCallback, useEffect, useState } from 'react';
import { useAuthStore } from '@/stores/useAuthStore';
import { CONVERSATION_APP_ID, conversationApplicationId } from '@/lib/conversationApplication';

interface ApplicationPreferences {
  favorites: string[];
  recent: Record<string, number>;
}

const EMPTY: ApplicationPreferences = { favorites: [], recent: {} };
const CHANGE_EVENT = 'application-preferences-changed';

function readPreferences(key: string): ApplicationPreferences {
  try {
    const saved = localStorage.getItem(key);
    const parsed = saved ? JSON.parse(saved) : null;
    const recent: Record<string, number> = Object.fromEntries(
      Object.entries(parsed?.recent || {}).filter(([, time]) =>
        typeof time === 'number' && Number.isFinite(time) && time > 0),
    ) as Record<string, number>;
    if (recent.cowork !== undefined && recent[CONVERSATION_APP_ID] === undefined) {
      recent[CONVERSATION_APP_ID] = recent.cowork;
    }
    delete recent.cowork;
    const preferences = {
      favorites: Array.isArray(parsed?.favorites)
        ? [...new Set<string>(parsed.favorites.filter((id: unknown) => typeof id === 'string').map(conversationApplicationId))]
        : [],
      recent,
    };
    if (saved && JSON.stringify(preferences) !== saved) {
      try { localStorage.setItem(key, JSON.stringify(preferences)); } catch { /* Storage may be read-only. */ }
    }
    return preferences;
  } catch {
    return EMPTY;
  }
}

/** Shared by the workbench and app catalog, including other open windows. */
export function useApplicationPreferences() {
  const userId = useAuthStore(state => state.user?.id || 'anonymous');
  const key = `application-preferences:${userId}`;
  const [snapshot, setSnapshot] = useState(() => ({ key, value: readPreferences(key) }));

  useEffect(() => {
    const refresh = () => setSnapshot({ key, value: readPreferences(key) });
    const onStorage = (event: StorageEvent) => {
      if (event.key === key || event.key === null) refresh();
    };
    const onChange = (event: Event) => {
      const detail = (event as CustomEvent<typeof snapshot>).detail;
      if (detail.key === key) setSnapshot(detail);
    };
    refresh();
    window.addEventListener('storage', onStorage);
    window.addEventListener('focus', refresh);
    window.addEventListener(CHANGE_EVENT, onChange);
    return () => {
      window.removeEventListener('storage', onStorage);
      window.removeEventListener('focus', refresh);
      window.removeEventListener(CHANGE_EVENT, onChange);
    };
  }, [key]);

  const update = useCallback((change: (current: ApplicationPreferences) => ApplicationPreferences) => {
    // Read at mutation time so opening an app cannot overwrite another window's favorites.
    const value = change(readPreferences(key));
    try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* Opening apps still works without storage. */ }
    const next = { key, value };
    setSnapshot(next);
    window.dispatchEvent(new CustomEvent(CHANGE_EVENT, { detail: next }));
  }, [key]);

  const recordUsage = (id: string) => update(current => ({
    ...current,
    recent: { ...current.recent, [conversationApplicationId(id)]: Date.now() },
  }));
  const toggleFavorite = (id: string) => update(current => ({
    ...current,
    favorites: current.favorites.includes(id)
      ? current.favorites.filter(value => value !== id)
      : [...current.favorites, id],
  }));

  return { preferences: snapshot.key === key ? snapshot.value : EMPTY, recordUsage, toggleFavorite };
}
