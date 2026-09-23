import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '@/services/api';
import type { WorkspaceFileListing, WorkspaceFilePreview } from '@/types/workspaceFiles';

const EMPTY_LISTING: WorkspaceFileListing = {
  working_directory: '',
  entries: [],
  file_count: 0,
  truncated: false,
};

export function useWorkspaceFiles(projectId?: number, conversationId?: string | null) {
  const [listing, setListing] = useState<WorkspaceFileListing>(EMPTY_LISTING);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const projectIdRef = useRef(projectId);
  const conversationIdRef = useRef(conversationId);
  projectIdRef.current = projectId;
  conversationIdRef.current = conversationId;

  const endpoint = projectId
    ? `/projects/${projectId}/workspace-files/`
    : conversationId
      ? `/conversations/${conversationId}/workspace-files/`
      : null;

  const refresh = useCallback(async () => {
    if (!endpoint) {
      setListing(EMPTY_LISTING);
      return;
    }
    setIsRefreshing(true);
    setError(null);
    try {
      const response = await api.get<WorkspaceFileListing>(
        endpoint,
      );
      if (
        projectIdRef.current === projectId
        && conversationIdRef.current === conversationId
      ) setListing(response);
    } catch (error) {
      console.error('Failed to scan workspace files:', error);
      if (projectIdRef.current === projectId && conversationIdRef.current === conversationId) {
        setError('加载工作空间文件失败，请点击刷新重试');
      }
    } finally {
      if (
        projectIdRef.current === projectId
        && conversationIdRef.current === conversationId
      ) setIsRefreshing(false);
    }
  }, [conversationId, endpoint, projectId]);

  const readFile = useCallback(async (path: string) => {
    if (!endpoint) throw new Error('工作目录尚未准备好');
    return api.get<WorkspaceFilePreview>(
      endpoint,
      { path },
    );
  }, [endpoint]);

  useEffect(() => {
    setListing(EMPTY_LISTING);
    setIsRefreshing(false);
    setError(null);
  }, [refresh]);

  return { ...listing, isRefreshing, error, refresh, readFile };
}
