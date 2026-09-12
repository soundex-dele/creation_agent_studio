export function isSingleTenantMode(): boolean {
  try {
    const persisted = JSON.parse(localStorage.getItem('organization-storage') || '{}');
    return persisted?.state?.singleTenantMode === true;
  } catch {
    return false;
  }
}

export function tenantApiRoot(organizationId: string): string {
  return isSingleTenantMode() ? '' : `/organizations/${organizationId}`;
}
