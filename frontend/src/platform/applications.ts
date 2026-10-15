import type { ComponentType, LazyExoticComponent } from 'react';
import type { AppItem } from '@/types';
import type { ApplicationRuntimeDescriptor, RunResource } from '@/services/applicationRuntime';
import type { useRunStream } from '@/features/run-stream';

export interface ApplicationTaskViewProps {
  descriptor: ApplicationRuntimeDescriptor;
  showApplicationHeader: boolean;
  run: RunResource | null;
  starting: boolean;
  projection: ReturnType<typeof useRunStream>;
  total: number;
  percent: number;
  start: (input?: Record<string, unknown>) => Promise<void>;
  cancel: () => Promise<void>;
}

export interface ApplicationFrontendModule {
  rendererKey: string;
  taskView?: LazyExoticComponent<ComponentType<ApplicationTaskViewProps>>;
  routes: {
    path: string;
    component: LazyExoticComponent<ComponentType>;
    fullBleed?: boolean;
    shell?: 'application' | 'main' | 'none';
    hideSidebar?: boolean;
  }[];
  launch: (application: Pick<AppItem, 'applicationId'>, entry: 'home' | 'apps') => string;
}
