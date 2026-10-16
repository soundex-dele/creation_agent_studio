import { lazy } from 'react';
import type { ApplicationFrontendModule } from '@/platform/applications';

const component = lazy(() => import('./pages/CommunityChatPage'));
export default {
  rendererKey: 'community-chat',
  routes: [
    { path: '/applications/:applicationId/community-chat', component, fullBleed: true },
    { path: '/community-chat', component, fullBleed: true },
  ],
  launch: (app, entry) => `/applications/${app.applicationId}/community-chat?entry=${entry}`,
} satisfies ApplicationFrontendModule;
