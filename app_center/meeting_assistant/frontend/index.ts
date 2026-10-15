import { lazy } from 'react';
import type { ApplicationFrontendModule } from '@platform/applications';

export default {
  rendererKey: 'meeting-assistant',
  routes: [
    { path: '/applications/:applicationId/meeting-assistant', component: lazy(() => import('./pages/MeetingAssistantPage')), fullBleed: true },
  ],
  launch: (app, entry) => `/applications/${app.applicationId}/meeting-assistant?entry=${entry}`,
} satisfies ApplicationFrontendModule;
