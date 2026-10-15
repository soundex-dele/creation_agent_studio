import { lazy } from 'react';
import type { ApplicationFrontendModule } from '@platform/applications';

export default {
  rendererKey: 'html-to-png',
  routes: [],
  taskView: lazy(() => import('./pages/HtmlToPngView')),
  launch: (app, entry) => `/applications/${app.applicationId}/run?entry=${entry}`,
} satisfies ApplicationFrontendModule;
