import { useCallback } from 'react';
import { useNavigate, useSearchParams, type NavigateOptions } from 'react-router-dom';
import { applicationNavigationPath } from '@/lib/applicationPresentation';

/** Navigate within an application without losing its window presentation. */
export default function useApplicationNavigate() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  return useCallback((path: string, options?: NavigateOptions) => (
    navigate(applicationNavigationPath(path, searchParams), options)
  ), [navigate, searchParams]);
}
