import React, { useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { ChatContainer } from '@/components/Chat';
import WorkspaceFilesPanel from '@/components/Workspace/WorkspaceFilesPanel';
import { useWorkspaceFiles } from '@/hooks/useWorkspaceFiles';
import { useConversationStore } from '@/stores/useConversationStore';

const ChatPage: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const conversationId = searchParams.get('conversation') || null;
  const streamingMessageId = useConversationStore((state) => state.streamingMessageId);
  const {
    working_directory: workingDirectory,
    entries: workspaceEntries,
    file_count: workspaceFileCount,
    truncated: workspaceListingTruncated,
    isRefreshing: isRefreshingWorkspace,
    refresh: refreshWorkspaceFiles,
    readFile: readWorkspaceFile,
  } = useWorkspaceFiles(undefined, conversationId);

  useEffect(() => {
    if (!conversationId) return;
    void refreshWorkspaceFiles();
    if (!streamingMessageId) return;
    const timer = window.setInterval(() => void refreshWorkspaceFiles(), 1200);
    return () => window.clearInterval(timer);
  }, [conversationId, streamingMessageId, refreshWorkspaceFiles]);

  return (
    <div className="chat-application-layout">
      <div className="chat-application-main">
        <ChatContainer
          conversationId={conversationId}
          createOnFirstSend
          onConversationCreated={(id) => setSearchParams({ conversation: id }, { replace: true })}
        />
      </div>
      {workspaceFileCount > 0 && (
        <WorkspaceFilesPanel
          workingDirectory={workingDirectory}
          entries={workspaceEntries}
          truncated={workspaceListingTruncated}
          isRefreshing={isRefreshingWorkspace}
          onRefresh={() => void refreshWorkspaceFiles()}
          onReadFile={readWorkspaceFile}
        />
      )}
    </div>
  );
};

export default ChatPage;
