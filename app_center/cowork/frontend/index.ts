import { lazy } from 'react';
import type { ApplicationFrontendModule } from '@platform/applications';

export default {
  rendererKey: 'cowork',
  routes: [
    { path: '/apps/cowork', component: lazy(() => import('./pages/CoWorkPage')), shell: 'none' },
  ],
  launch: (_app, entry) => `/chat?entry=${entry}`,
} satisfies ApplicationFrontendModule;
