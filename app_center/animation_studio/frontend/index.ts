import { lazy } from 'react';
import type { ApplicationFrontendModule } from '@platform/applications';

export default {
  rendererKey: 'animation-studio',
  routes: [
    { path: '/applications/:applicationId/animation-studio', component: lazy(() => import('./pages/AnimationStudioPage')), fullBleed: true },
  ],
  launch: (app, entry) => `/applications/${app.applicationId}/animation-studio?entry=${entry}`,
} satisfies ApplicationFrontendModule;
