import { lazy } from 'react';
import type { ApplicationFrontendModule } from '@platform/applications';

export default {
  rendererKey: 'ideas-todos',
  routes: [
    { path: '/applications/:applicationId/ideas-todos', component: lazy(() => import('./pages/IdeasTodosPage')), fullBleed: true },
  ],
  launch: (app, entry) => `/applications/${app.applicationId}/ideas-todos?entry=${entry}`,
} satisfies ApplicationFrontendModule;
