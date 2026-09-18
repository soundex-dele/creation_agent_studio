import { useCallback } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';

import { CreationToolboxApp } from '@creation-toolbox/main';
import { resolveApplicationPresentation } from '@/lib/applicationPresentation';
import { api } from '@/services/api';
import { tenantApiRoot } from '@/services/tenantContext';
import { useOrganizationStore } from '@/stores/useOrganizationStore';


export default function CreationToolboxPage() {
  const { applicationId } = useParams<{ applicationId: string }>();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { showApplicationHeader } = resolveApplicationPresentation(searchParams);
  const organizationId = useOrganizationStore((state) => state.currentOrganizationId);

  const requester = useCallback(async <T,>(path: string, init: RequestInit = {}) => {
    const method = String(init.method || 'GET').toUpperCase();
    const headers = Object.fromEntries(new Headers(init.headers).entries());
    const data = typeof init.body === 'string' ? JSON.parse(init.body) : init.body;
    if (method === 'POST') return api.post<T>(path, data, { headers });
    if (method === 'PATCH') return api.patch<T>(path, data, { headers });
    if (method === 'PUT') return api.put<T>(path, data, { headers });
    if (method === 'DELETE') return api.delete<T>(path, { headers });
    return api.get<T>(path, undefined, { headers });
  }, []);

  if (!organizationId || !applicationId) return null;

  return (
    <CreationToolboxApp
      apiBasePath={`${tenantApiRoot(organizationId)}/applications/${applicationId}/creation-toolbox`}
      requester={requester}
      showHeader={showApplicationHeader}
      onBack={showApplicationHeader ? () => navigate('/apps') : undefined}
    />
  );
}

