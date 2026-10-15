import type { ComponentType, LazyExoticComponent } from 'react';
import type { AppItem } from '@/types';

export interface ApplicationFrontendModule {
  rendererKey: string;
  routes: { path: string; component: LazyExoticComponent<ComponentType>; fullBleed?: boolean }[];
  launch: (application: Pick<AppItem, 'applicationId'>, entry: 'home' | 'apps') => string;
}
