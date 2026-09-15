import { useCallback } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';

import { CreationMasterApp } from '@creation-master/main';
import { api } from '@/services/api';
import { useOrganizationStore } from '@/stores/useOrganizationStore';


export default function CreationMasterPage() {
  const { applicationId } = useParams<{ applicationId: string }>();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const embedded = searchParams.get('embedded') === '1';
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

  return (
    <CreationMasterApp
      organizationId={organizationId ?? ''}
      applicationId={applicationId ?? ''}
      requester={requester}
      onBack={embedded ? undefined : () => navigate('/apps')}
    />
  );
}
