export interface Preferences { best: number; sound: boolean }
export const storageKey = (organization: string, user: string, application: string) =>
  `pocket-salvager:v1:${encodeURIComponent(organization)}:${encodeURIComponent(user)}:${encodeURIComponent(application)}`;
export function readPreferences(key: string): Preferences {
  try {
    const value = JSON.parse(localStorage.getItem(key) || '{}');
    return { best: Number.isFinite(value?.best) && value.best >= 0 ? value.best : 0, sound: value?.sound !== false };
  } catch { return { best: 0, sound: true }; }
}
export function savePreferences(key: string, value: Preferences) {
  try { localStorage.setItem(key, JSON.stringify(value)); return true; } catch { return false; }
}
