import { lazy } from 'react';
import type { ApplicationFrontendModule } from '@platform/applications';

export default {
  rendererKey: 'song-curator',
  routes: [{ path: '/applications/:applicationId/song-curator', component: lazy(() => import('./pages/SongCuratorPage')), fullBleed: true }],
  launch: (app, entry) => `/applications/${app.applicationId}/song-curator?entry=${entry}`,
} satisfies ApplicationFrontendModule;
