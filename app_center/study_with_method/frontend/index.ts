import { lazy } from 'react';
import type { ApplicationFrontendModule } from '@platform/applications';

export default {
  rendererKey: 'study-with-method',
  routes: [
    { path: '/applications/:applicationId/study-with-method', component: lazy(() => import('./pages/StudyWithMethodPage')), fullBleed: true },
  ],
  launch: (app, entry) => `/applications/${app.applicationId}/study-with-method?entry=${entry}`,
} satisfies ApplicationFrontendModule;
