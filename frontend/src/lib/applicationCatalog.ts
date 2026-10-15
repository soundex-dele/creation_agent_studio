import applicationModules from 'virtual:application-packages';
import type { AppItem } from '@/types';

type ApplicationLink = Pick<AppItem, 'id' | 'rendererKey' | 'applicationId' | 'kind'>;
type EntryPoint = 'home' | 'apps';
type RouteBuilder = (app: ApplicationLink, entry: EntryPoint) => string;

const withEntry = (path: string, entry: EntryPoint, params?: URLSearchParams) => {
  const query = params ?? new URLSearchParams();
  query.set('entry', entry);
  return `${path}?${query.toString()}`;
};

/** Trusted package launchers plus the platform's shared chat/task renderers. */
export const applicationRendererRegistry: Readonly<Record<string, RouteBuilder>> = {
  ...Object.fromEntries(applicationModules.map(module => [module.rendererKey, module.launch])),
  chat: (app, entry) => withEntry(
    `/applications/${app.applicationId}/chat`,
    entry,
    new URLSearchParams({ slug: app.id }),
  ),
  'generic-task': (app, entry) => withEntry(`/applications/${app.applicationId}/run`, entry),
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
