import { lazy } from 'react';
import type { ApplicationFrontendModule } from '@platform/applications';

export default {
  rendererKey: 'brand-library',
  routes: [
    { path: '/applications/:applicationId/brand-library', component: lazy(() => import('./pages/BrandLibraryPage')), fullBleed: true },
  ],
  launch: (app, entry) => `/applications/${app.applicationId}/brand-library?entry=${entry}`,
} satisfies ApplicationFrontendModule;
