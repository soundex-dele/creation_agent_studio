import { lazy } from 'react';
import type { ApplicationFrontendModule } from '@platform/applications';

export default {
  rendererKey: 'repo-explainer',
  routes: [
    { path: '/applications/:applicationId/repo-explainer', component: lazy(() => import('./pages/RepoExplainerPage')), fullBleed: true },
  ],
  launch: (app, entry) => `/applications/${app.applicationId}/repo-explainer?entry=${entry}`,
} satisfies ApplicationFrontendModule;
