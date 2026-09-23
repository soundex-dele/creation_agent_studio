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
  'ideas-todos': (app, entry) => withEntry(`/applications/${app.applicationId}/ideas-todos`, entry),
  'my-computer': (_app, entry) => withEntry('/apps/my-computer', entry),
  'case-library': (_app, entry) => withEntry('/apps/case-library', entry),
  'study-with-method': (app, entry) => withEntry(
    `/applications/${app.applicationId}/study-with-method`, entry,
  ),
  'creation-master': (app, entry) => withEntry(
    `/applications/${app.applicationId}/creation-master`, entry,
  ),
  'wechat-assistant': (app, entry) => withEntry(`/applications/${app.applicationId}/wechat-assistant`, entry),
  'creation-toolbox': (app, entry) => withEntry(
    `/applications/${app.applicationId}/creation-toolbox`, entry,
  ),
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
