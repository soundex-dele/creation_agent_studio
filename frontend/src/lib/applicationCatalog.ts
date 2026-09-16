import type { AppItem } from '@/types';

type ApplicationLink = Pick<AppItem, 'id' | 'rendererKey' | 'applicationId' | 'kind'>;
type EntryPoint = 'home' | 'apps';
type RouteBuilder = (app: ApplicationLink, entry: EntryPoint) => string;

const withEntry = (path: string, entry: EntryPoint, params?: URLSearchParams) => {
  const query = params ?? new URLSearchParams();
  query.set('entry', entry);
  return `${path}?${query.toString()}`;
};

/** Platform-owned renderer keys. Manifests select a key; they cannot inject JS. */
export const applicationRendererRegistry: Readonly<Record<string, RouteBuilder>> = {
  'case-library': (_app, entry) => withEntry('/apps/case-library', entry),
  contacts: (app, entry) => withEntry(`/applications/${app.applicationId}/contacts`, entry),
  'creation-master': (app, entry) => withEntry(
    `/applications/${app.applicationId}/creation-master`, entry,
  ),
  wemd: (app, entry) => withEntry(`/applications/${app.applicationId}/wemd`, entry),
  chat: (app, entry) => withEntry(
    `/applications/${app.applicationId}/chat`,
    entry,
    new URLSearchParams({ slug: app.id }),
  ),
  'generic-task': (app, entry) => withEntry(`/applications/${app.applicationId}/run`, entry),
  'html-to-png': (app, entry) => withEntry(`/applications/${app.applicationId}/run`, entry),
};

export function applicationPath(app: ApplicationLink, entry: EntryPoint = 'apps'): string {
  const renderer = app.rendererKey && applicationRendererRegistry[app.rendererKey];
  if (renderer && app.applicationId) return renderer(app, entry);
  if (app.kind === 'chat' && app.applicationId) {
    return applicationRendererRegistry.chat(app, entry);
  }
  if (app.applicationId) {
    return applicationRendererRegistry['generic-task'](app, entry);
  }
  return withEntry(`/apps/${app.id}`, entry);
}
