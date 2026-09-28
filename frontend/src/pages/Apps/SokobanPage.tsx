import { useParams, useSearchParams } from 'react-router-dom';
import { useAuthStore } from '@/stores/useAuthStore';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import { resolveApplicationPresentation } from '@/lib/applicationPresentation';
import SokobanWorkspace from './sokoban/Workspace';
import { storageKey } from './sokoban/storage';
import './SokobanPage.css';

export default function SokobanPage() {
  const { applicationId } = useParams<{ applicationId: string }>();
  const [params] = useSearchParams();
  const userId = useAuthStore(state => state.user?.id);
  const organizationId = useOrganizationStore(state => state.currentOrganizationId);
  if (!userId || !organizationId || !applicationId) return <div className="sokoban-page"><p className="sokoban-empty" role="status">请选择组织并登录后使用推箱子。</p></div>;
  const key = storageKey(organizationId, userId, applicationId);
  return <SokobanWorkspace key={key} saveKey={key} showBack={resolveApplicationPresentation(params).showApplicationHeader} />;
}
