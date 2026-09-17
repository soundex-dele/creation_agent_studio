import React, { useEffect, useState } from 'react';
import { Button, Drawer } from 'antd';
import { FolderOpenOutlined } from '@ant-design/icons';
import { useSearchParams } from 'react-router-dom';
import { ChatContainer } from '@/components/Chat';
import WorkspaceFilesPanel from '@/components/Workspace/WorkspaceFilesPanel';
import { useWorkspaceFiles } from '@/hooks/useWorkspaceFiles';
import { useConversationStore } from '@/stores/useConversationStore';
import useMediaQuery from '@/hooks/useMediaQuery';

const ChatPage: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const isMobile = useMediaQuery('(max-width: 767px)');
  const [filesOpen, setFilesOpen] = useState(false);
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

  useEffect(() => setFilesOpen(false), [conversationId]);

  return (
    <div className="chat-application-layout">
      <div className="chat-application-main">
        <ChatContainer
          conversationId={conversationId}
          createOnFirstSend
          onConversationCreated={(id) => setSearchParams({ conversation: id }, { replace: true })}
        />
      </div>
      {workspaceFileCount > 0 && !isMobile && (
        <WorkspaceFilesPanel
          workingDirectory={workingDirectory}
          entries={workspaceEntries}
          truncated={workspaceListingTruncated}
          isRefreshing={isRefreshingWorkspace}
          onRefresh={() => void refreshWorkspaceFiles()}
          onReadFile={readWorkspaceFile}
        />
      )}
      {workspaceFileCount > 0 && isMobile && (
        <>
          <Button
            className="chat-files-mobile-trigger"
            icon={<FolderOpenOutlined />}
            aria-expanded={filesOpen}
            onClick={() => setFilesOpen(true)}
          >
            文件
          </Button>
          <Drawer
            title="会话文件"
            placement="right"
            width="min(92vw, 380px)"
            open={filesOpen}
            onClose={() => setFilesOpen(false)}
            rootClassName="chat-files-drawer"
          >
            <WorkspaceFilesPanel
              workingDirectory={workingDirectory}
              entries={workspaceEntries}
              truncated={workspaceListingTruncated}
              isRefreshing={isRefreshingWorkspace}
              onRefresh={() => void refreshWorkspaceFiles()}
              onReadFile={readWorkspaceFile}
            />
          </Drawer>
        </>
      )}
    </div>
  );
};

export default ChatPage;
