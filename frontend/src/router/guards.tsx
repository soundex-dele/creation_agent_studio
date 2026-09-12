import { useEffect } from 'react';
import { Button, Result, Spin } from 'antd';
import { Navigate } from 'react-router-dom';
import { useAuthStore } from '@/stores/useAuthStore';
import { useOrganizationStore } from '@/stores/useOrganizationStore';

interface ProtectedRouteProps {
  children: React.ReactNode;
}

export const ProtectedRoute: React.FC<ProtectedRouteProps> = ({ children }) => {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const userId = useAuthStore((state) => state.user?.id ?? null);
  const loadedForUserId = useOrganizationStore((state) => state.loadedForUserId);
  const isLoading = useOrganizationStore((state) => state.isLoading);
  const loadError = useOrganizationStore((state) => state.loadError);
  const loadOrganizations = useOrganizationStore((state) => state.loadOrganizations);

  useEffect(() => {
    if (
      isAuthenticated
      && userId
      && loadedForUserId !== userId
      && !isLoading
      && !loadError
    ) {
      void loadOrganizations(userId).catch(() => undefined);
    }
  }, [
    isAuthenticated,
    userId,
    loadedForUserId,
    isLoading,
    loadError,
    loadOrganizations,
  ]);

  if (!isAuthenticated) {
    return <Navigate to="/auth/login" replace />;
  }

  // Validate the persisted organization before any protected page can issue
  // tenant-scoped requests. This also replaces organization IDs left behind
  // by a restored or migrated database.
  if (userId && loadedForUserId !== userId) {
    if (loadError) {
      return (
        <Result
          status="warning"
          title="无法加载组织工作区"
          subTitle={loadError}
          extra={(
            <Button type="primary" onClick={() => {
              void loadOrganizations(userId).catch(() => undefined);
            }}>
              重试
            </Button>
          )}
        />
      );
    }
    return <Spin fullscreen tip="正在加载组织工作区…" />;
  }

  return <>{children}</>;
};

export const PublicRoute: React.FC<ProtectedRouteProps> = ({ children }) => {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);

  if (isAuthenticated) {
    return <Navigate to="/" replace />;
  }

  return <>{children}</>;
};
