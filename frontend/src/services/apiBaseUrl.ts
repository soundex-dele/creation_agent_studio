/**
 * Same-origin deployments and the Vite dev server both expose Django below
 * /api. An explicit environment value is only needed for cross-origin setups.
 */
export function resolveApiBaseUrl(configuredBaseUrl?: string): string {
  return (configuredBaseUrl?.trim() || '/api').replace(/\/+$/, '');
}

export const API_BASE_URL = resolveApiBaseUrl(import.meta.env.VITE_API_BASE_URL);
