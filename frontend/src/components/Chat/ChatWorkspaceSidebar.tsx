import { useId, useState } from 'react';
import { Alert, Button, Drawer, Tooltip, message } from 'antd';
import { FileSearchOutlined, FolderOpenOutlined } from '@ant-design/icons';
import { SidebarSimple } from '@phosphor-icons/react';
import { useWorkspaceFiles } from '@/hooks/useWorkspaceFiles';
import WorkspaceFilesPanel from '@/components/Workspace/WorkspaceFilesPanel';
import { useChatConnection } from './ChatConnectionContext';
import './ChatWorkspaceSidebar.css';

export default function ChatWorkspaceSidebar({ conversationId }: { conversationId: string }) {
  const { api, online } = useChatConnection();
  const [open, setOpen] = useState(false);
  const [filesVisible, setFilesVisible] = useState(false);
  const [openingDirectory, setOpeningDirectory] = useState(false);
  const sidebarId = useId();
  const filesId = useId();
  const files = useWorkspaceFiles(undefined, conversationId);

  const close = () => {
    setOpen(false);
    setFilesVisible(false);
  };

  const openDirectory = async () => {
    if (!online || openingDirectory) return;
    setOpeningDirectory(true);
    try {
      await api.post(`/conversations/${conversationId}/open-workspace/`, {});
    } catch {
      message.error('无法打开当前会话目录，请重试');
    } finally {
      setOpeningDirectory(false);
    }
  };

  const toggleFiles = () => {
    setFilesVisible(!filesVisible);
    if (!filesVisible) void files.refresh();
  };

  return (
    <>
      <div className="chat-workspace-toolbar">
        <Tooltip title="打开右侧栏">
          <Button
            type="text"
            icon={<SidebarSimple size={18} weight="bold" mirrored aria-hidden="true" />}
            aria-label="打开右侧栏"
            aria-expanded={open}
            aria-controls={open ? sidebarId : undefined}
            onClick={() => setOpen(true)}
          />
        </Tooltip>
      </div>
      <Drawer
        title="会话工作空间"
        placement="right"
        width="min(92vw, 420px)"
        open={open}
        onClose={close}
        rootClassName="chat-workspace-drawer"
        destroyOnHidden
      >
        <div id={sidebarId} className="chat-workspace-sidebar">
          <div className="chat-workspace-sidebar-actions">
            <Button
              icon={<FolderOpenOutlined />}
              loading={openingDirectory}
              disabled={!online}
              onClick={() => void openDirectory()}
            >打开目录</Button>
            <Button
              icon={<FileSearchOutlined />}
              disabled={!online}
              aria-expanded={filesVisible}
              aria-controls={filesId}
              onClick={toggleFiles}
            >{filesVisible ? '收起工作空间文件' : '查看工作空间文件'}</Button>
          </div>
          <div id={filesId} className="chat-workspace-sidebar-files" hidden={!filesVisible}>
            {filesVisible && (
              <>
                {files.error && <Alert type="error" showIcon message={files.error} />}
                <WorkspaceFilesPanel
                  workingDirectory={files.working_directory}
                  entries={files.entries}
                  truncated={files.truncated}
                  isRefreshing={files.isRefreshing}
                  onRefresh={() => { if (online) void files.refresh(); }}
                  onReadFile={files.readFile}
                />
              </>
            )}
          </div>
        </div>
      </Drawer>
    </>
  );
}
