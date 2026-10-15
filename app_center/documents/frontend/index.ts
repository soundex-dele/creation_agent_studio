import { lazy } from 'react';
import type { ApplicationFrontendModule } from '@platform/applications';

export default {
  rendererKey: 'documents',
  routes: [
    { path: '/applications/:applicationId/documents', component: lazy(() => import('./pages/DocumentsPage')), fullBleed: true },
  ],
  launch: (app, entry) => `/applications/${app.applicationId}/documents?entry=${entry}`,
} satisfies ApplicationFrontendModule;
