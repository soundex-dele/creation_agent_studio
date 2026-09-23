import { useCallback } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { WechatAssistantApp } from '@wechat-assistant/main';
import { api } from '@/services/api';
import { tenantApiRoot } from '@/services/tenantContext';
import { useOrganizationStore } from '@/stores/useOrganizationStore';

export default function WechatAssistantPage() {
  const { applicationId } = useParams<{ applicationId: string }>();
  const organizationId = useOrganizationStore(state => state.currentOrganizationId);
  const navigate = useNavigate();
  const requester = useCallback(async <T,>(path: string, init: RequestInit = {}) => {
    const data = typeof init.body === 'string' ? JSON.parse(init.body) : init.body;
    if (init.method === 'PUT') return api.put<T>(path, data);
    if (init.method === 'POST') return api.post<T>(path, data);
    return api.get<T>(path);
  }, []);
  if (!organizationId || !applicationId) return null;
  return <WechatAssistantApp key={`${organizationId}:${applicationId}`} apiBasePath={`${tenantApiRoot(organizationId)}/applications/${applicationId}/wechat-assistant/`} requester={requester} openConversation={id => navigate(`/chat?conversation=${id}`)} />;
}
