import { useNavigate, useSearchParams } from 'react-router-dom';

import { NewMediaWorkbenchApp } from '@newmedia-workbench/main';
import { resolveApplicationPresentation } from '@/lib/applicationPresentation';

export default function NewMediaWorkbenchPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { showApplicationHeader } = resolveApplicationPresentation(searchParams);

  return (
    <NewMediaWorkbenchApp
      showHeader={showApplicationHeader}
      onBack={showApplicationHeader ? () => navigate('/apps') : undefined}
    />
  );
}
