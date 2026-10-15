import { lazy } from 'react';
import type { ApplicationFrontendModule } from '@platform/applications';

export default {
  rendererKey: 'ai-drawing',
  routes: [
    { path: '/applications/:applicationId/ai-drawing', component: lazy(() => import('./pages/AIDrawingPage')), fullBleed: true },
  ],
  launch: (app, entry) => `/applications/${app.applicationId}/ai-drawing?entry=${entry}`,
} satisfies ApplicationFrontendModule;
