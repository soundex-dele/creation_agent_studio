import { lazy } from 'react';
import type { ApplicationFrontendModule } from '@platform/applications';

export default {
  rendererKey: 'kitchen-assistant',
  routes: [{ path: '/applications/:applicationId/kitchen-assistant', component: lazy(() => import('./pages/KitchenAssistantPage')), fullBleed: true }],
  launch: (app, entry) => `/applications/${app.applicationId}/kitchen-assistant?entry=${entry}`,
} satisfies ApplicationFrontendModule;
