import { lazy } from 'react';
import type { ApplicationFrontendModule } from '@platform/applications';

export default {
  rendererKey: 'pocket-salvager',
  routes: [
    { path: '/apps/pocket-salvager', component: lazy(() => import('./pages/PocketSalvagerPage')), fullBleed: true },
    { path: '/applications/:applicationId/pocket-salvager', component: lazy(() => import('./pages/PocketSalvagerPage')), fullBleed: true },
  ],
  launch: (app, entry) => `/applications/${app.applicationId}/pocket-salvager?entry=${entry}`,
} satisfies ApplicationFrontendModule;
