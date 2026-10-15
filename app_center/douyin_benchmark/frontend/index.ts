import { lazy } from 'react';
import type { ApplicationFrontendModule } from '@platform/applications';

export default {
  rendererKey: 'douyin-benchmark',
  routes: [{ path: '/applications/:applicationId/douyin-benchmark', component: lazy(() => import('./pages/DouyinBenchmarkPage')), fullBleed: true }],
  launch: (app, entry) => `/applications/${app.applicationId}/douyin-benchmark?entry=${entry}`,
} satisfies ApplicationFrontendModule;
