import { lazy } from 'react';
import type { ApplicationFrontendModule } from '@platform/applications';

export default {
  rendererKey: 'rental-growth-assistant',
  routes: [
    { path: '/applications/:applicationId/rental-growth-assistant', component: lazy(() => import('./pages/RentalGrowthPage')), fullBleed: true },
  ],
  launch: (app, entry) => `/applications/${app.applicationId}/rental-growth-assistant?entry=${entry}`,
} satisfies ApplicationFrontendModule;
