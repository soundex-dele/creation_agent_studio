import { lazy } from 'react';
import type { ApplicationFrontendModule } from '@platform/applications';

export default {
  rendererKey: 'sokoban',
  routes: [
    { path: '/applications/:applicationId/sokoban', component: lazy(() => import('./pages/SokobanPage')), fullBleed: true },
  ],
  launch: (app, entry) => `/applications/${app.applicationId}/sokoban?entry=${entry}`,
} satisfies ApplicationFrontendModule;
