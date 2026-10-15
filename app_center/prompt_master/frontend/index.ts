import { lazy } from 'react';
import type { ApplicationFrontendModule } from '@platform/applications';

export default {
  rendererKey: 'prompt-master',
  routes: [
    { path: '/applications/:applicationId/prompt-master', component: lazy(() => import('./pages/PromptMasterPage')), fullBleed: true },
  ],
  launch: (app, entry) => `/applications/${app.applicationId}/prompt-master?entry=${entry}`,
} satisfies ApplicationFrontendModule;
