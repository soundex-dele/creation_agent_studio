import { lazy } from 'react';
import type { ApplicationFrontendModule } from '@platform/applications';

export default {
  rendererKey: 'disk-cleaner',
  routes: [
    { path: '/applications/:applicationId/disk-cleaner', component: lazy(() => import('./pages/DiskCleanerPage')), fullBleed: true },
  ],
  launch: (app, entry) => `/applications/${app.applicationId}/disk-cleaner?entry=${entry}`,
} satisfies ApplicationFrontendModule;
