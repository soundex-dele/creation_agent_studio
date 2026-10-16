import { lazy } from 'react';
import type { ApplicationFrontendModule } from '@platform/applications';

export default {
  rendererKey: 'web-fetch',
  routes: [{ path: '/applications/:applicationId/web-fetch', component: lazy(() => import('./pages/WebFetchPage')), fullBleed: true }],
  launch: (app, entry) => `/applications/${app.applicationId}/web-fetch?entry=${entry}`,
} satisfies ApplicationFrontendModule;
