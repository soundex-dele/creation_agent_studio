import { lazy } from 'react';
import type { ApplicationFrontendModule } from '@platform/applications';

export default {
  rendererKey: 'case-library',
  routes: [
    { path: '/templates', component: lazy(() => import('./pages/LegacyTemplateRedirect')), shell: 'none' },
    { path: '/templates/:id', component: lazy(() => import('./pages/LegacyTemplateRedirect')), shell: 'none' },
    { path: '/apps/case-library', component: lazy(() => import('./pages/TemplatesPage')) },
    { path: '/apps/case-library/:id', component: lazy(() => import('./pages/TemplateDetailPage')) },
  ],
  launch: (_app, entry) => `/apps/case-library?entry=${entry}`,
} satisfies ApplicationFrontendModule;
