import { lazy } from 'react';
import type { ApplicationFrontendModule } from '@platform/applications';

export default {
  rendererKey: 'project-promotion',
  routes: [
    { path: '/applications/:applicationId/project-promotion', component: lazy(() => import('./pages/ProjectPromotionPage')), fullBleed: true },
  ],
  launch: (app, entry) => `/applications/${app.applicationId}/project-promotion?entry=${entry}`,
} satisfies ApplicationFrontendModule;
