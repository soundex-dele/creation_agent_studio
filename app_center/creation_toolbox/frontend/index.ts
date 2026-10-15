import { lazy } from 'react';
import type { ApplicationFrontendModule } from '@platform/applications';

export default {
  rendererKey: 'creation-toolbox',
  routes: [
    { path: '/applications/:applicationId/creation-toolbox', component: lazy(() => import('./pages/CreationToolboxPage')), fullBleed: true },
  ],
  launch: (app, entry) => `/applications/${app.applicationId}/creation-toolbox?entry=${entry}`,
} satisfies ApplicationFrontendModule;
