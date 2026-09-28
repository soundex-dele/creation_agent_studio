import { useParams, useSearchParams } from 'react-router-dom';
import { useAuthStore } from '@/stores/useAuthStore';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import { resolveApplicationPresentation } from '@/lib/applicationPresentation';
import Workspace from './pocket-salvager/Workspace';
import { storageKey } from './pocket-salvager/storage';
import './PocketSalvagerPage.css';

export default function PocketSalvagerPage() {
  const { applicationId = 'pocket-salvager' } = useParams<{ applicationId: string }>();
  const [params] = useSearchParams();
  const user = useAuthStore(state => state.user?.id);
  const organization = useOrganizationStore(state => state.currentOrganizationId);
  if (!user || !organization) return <div className="salvager-page"><p className="salvager-empty" role="status">请选择组织并登录后开始航行。</p></div>;
  const key = storageKey(organization, user, applicationId);
  return <Workspace key={key} saveKey={key} showBack={resolveApplicationPresentation(params).showApplicationHeader} />;
}
