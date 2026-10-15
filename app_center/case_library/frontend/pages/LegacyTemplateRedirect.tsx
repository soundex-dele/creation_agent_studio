import { Navigate, useParams } from 'react-router-dom';

export default function LegacyTemplateRedirect() {
  const { id } = useParams<{ id: string }>();
  return <Navigate to={id ? `/apps/case-library/${id}` : '/apps/case-library'} replace />;
}
