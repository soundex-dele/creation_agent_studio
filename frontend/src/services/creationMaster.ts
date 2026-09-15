import { api } from './api';
import { tenantApiRoot } from './tenantContext';


export interface CreationMasterWebRuntime {
  enabled: boolean;
  url: string;
}

export function getCreationMasterWebRuntime(
  organizationId: string,
  applicationId: string,
) {
  return api.get<CreationMasterWebRuntime>(
    `${tenantApiRoot(organizationId)}/applications/${applicationId}/creation-master`,
  );
}
