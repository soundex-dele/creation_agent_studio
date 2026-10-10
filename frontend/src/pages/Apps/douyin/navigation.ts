/** Preserve presentation and creator selection, discard the previous screen's context. */
export function douyinLocation(params: URLSearchParams, view: string, context: Record<string, string | undefined> = {}) {
  const next = new URLSearchParams(params);
  for (const key of ['account', 'task', 'idea', 'source', 'topic', 'work', 'referenceAccount', 'mode', 'profile', 'subscription', 'output']) next.delete(key);
  next.set('view', view || 'accounts');
  for (const [key, value] of Object.entries(context)) {
    if (value) next.set(key, value); else next.delete(key);
  }
  return next;
}
export function primarySection(view: string) {
  if (['', 'accounts', 'research', 'radar'].includes(view)) return 'accounts';
  if (['owned', 'profiles', 'review'].includes(view)) return 'owned';
  if (['materials', 'inspirations', 'knowledge'].includes(view)) return 'materials';
  return view;
}
export const taskKinds: Record<string, string> = {
  research: 'radar,compare,joint,comments,needs,breakdown',
  create: 'topics,article,script,rewrite,transcribe,variants',
  review: 'review,refresh', knowledge: 'knowledge_extract',
};
export function taskSection(kind: string) {
  if (kind.startsWith('radar_')) return 'radar';
  return Object.keys(taskKinds).find(section => taskKinds[section].split(',').includes(kind)) || 'tasks';
}
