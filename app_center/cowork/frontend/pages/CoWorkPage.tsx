import { Navigate, useLocation } from 'react-router-dom';

/** Preserve bookmarks and launch presentation for the former CoWork entry. */
export default function CoWorkPage() {
  const { search, hash } = useLocation();
  return <Navigate to={`/chat${search}${hash}`} replace />;
}
