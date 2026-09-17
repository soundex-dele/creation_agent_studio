import { createContext, useContext, useMemo, type PropsWithChildren } from 'react';

import {
  createApplicationRuntimeClient,
  type ApplicationRuntimeClient,
} from '@/services/applicationRuntime';


const RuntimeContext = createContext<ApplicationRuntimeClient | null>(null);

interface ProviderProps extends PropsWithChildren {
  organizationId: string;
  applicationId: string;
}

export function ApplicationRuntimeProvider({
  organizationId,
  applicationId,
  children,
}: ProviderProps) {
  const value = useMemo(
    () => createApplicationRuntimeClient({ organizationId, applicationId }),
    [applicationId, organizationId],
  );
  return <RuntimeContext.Provider value={value}>{children}</RuntimeContext.Provider>;
}

export function useApplicationRuntime(): ApplicationRuntimeClient {
  const value = useContext(RuntimeContext);
  if (value === null) {
    throw new Error('useApplicationRuntime must be used inside ApplicationRuntimeProvider');
  }
  return value;
}
