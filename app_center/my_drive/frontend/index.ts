import { lazy } from 'react';
import type { ApplicationFrontendModule } from '@platform/applications';

export default {
  rendererKey: 'my-drive',
  routes: [
    { path: '/applications/:applicationId/my-drive', component: lazy(() => import('./pages/MyDrivePage')), fullBleed: true },
  ],
  launch: (app, entry) => `/applications/${app.applicationId}/my-drive?entry=${entry}`,
} satisfies ApplicationFrontendModule;
