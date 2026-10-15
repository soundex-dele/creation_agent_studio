import { lazy } from 'react';
import type { ApplicationFrontendModule } from '@platform/applications';

export default {
  rendererKey: 'my-computer',
  routes: [
    { path: '/apps/my-computer', component: lazy(() => import('./pages/MyComputerPage')), shell: 'main', hideSidebar: true, fullBleed: true },
    { path: '/apps/my-computer/:deviceId', component: lazy(() => import('./pages/MyComputerPage')), shell: 'main', hideSidebar: true, fullBleed: true },
    { path: '/apps/my-computer/:deviceId/conversations/:conversationId', component: lazy(() => import('./pages/MyComputerPage')), shell: 'main', hideSidebar: true, fullBleed: true },
    { path: '/apps/my-computer/:deviceId/terminals', component: lazy(() => import('./pages/MyComputerPage')), shell: 'main', hideSidebar: true, fullBleed: true },
    { path: '/apps/my-computer/:deviceId/terminals/:sessionId', component: lazy(() => import('./pages/MyComputerPage')), shell: 'main', hideSidebar: true, fullBleed: true },
    { path: '/apps/my-computer/:deviceId/files', component: lazy(() => import('./pages/MyComputerPage')), shell: 'main', hideSidebar: true, fullBleed: true },
  ],
  launch: (_app, entry) => `/apps/my-computer?entry=${entry}`,
} satisfies ApplicationFrontendModule;
