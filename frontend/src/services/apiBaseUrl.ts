/**
 * Same-origin deployments and the Vite dev server both expose Django below
 * /api/v1. An explicit environment value is only needed for cross-origin setups.
 */
export function resolveApiBaseUrl(configuredBaseUrl?: string): string {
  return (configuredBaseUrl?.trim() || '/api/v1').replace(/\/+$/, '');
}

export const API_BASE_URL = resolveApiBaseUrl(import.meta.env.VITE_API_BASE_URL);
