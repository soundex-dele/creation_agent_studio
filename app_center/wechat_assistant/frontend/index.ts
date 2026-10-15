import { lazy } from 'react';
import type { ApplicationFrontendModule } from '@platform/applications';

export default {
  rendererKey: 'wechat-assistant',
  routes: [
    { path: '/applications/:applicationId/wechat-assistant', component: lazy(() => import('./pages/WechatAssistantPage')), fullBleed: true },
  ],
  launch: (app, entry) => `/applications/${app.applicationId}/wechat-assistant?entry=${entry}`,
} satisfies ApplicationFrontendModule;
