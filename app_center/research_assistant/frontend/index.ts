import { lazy } from 'react';
import type { ApplicationFrontendModule } from '@platform/applications';

export default {
  rendererKey: 'research-assistant',
  routes: [
    { path: '/applications/:applicationId/research-assistant', component: lazy(() => import('./pages/ResearchAssistantPage')), fullBleed: true },
  ],
  launch: (app, entry) => `/applications/${app.applicationId}/research-assistant?entry=${entry}`,
} satisfies ApplicationFrontendModule;
