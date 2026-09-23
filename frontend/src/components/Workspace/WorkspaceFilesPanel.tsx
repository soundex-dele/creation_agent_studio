import { useEffect, useState } from 'react';
import { Empty, Spin, message } from 'antd';
import {
  CopyOutlined,
  FileImageOutlined,
  FileOutlined,
  FileTextOutlined,
  FolderOpenOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import type { WorkspaceFileEntry, WorkspaceFilePreview } from '@/types/workspaceFiles';
import './WorkspaceFilesPanel.css';

interface Props {
  workingDirectory: string;
  entries: WorkspaceFileEntry[];
  truncated?: boolean;
  isRefreshing?: boolean;
  onRefresh: () => void;
  onReadFile: (path: string) => Promise<WorkspaceFilePreview>;
}

const formatSize = (bytes: number) => {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
};

const FileIcon = ({ entry }: { entry: WorkspaceFileEntry }) => {
  if (entry.is_directory) return <FolderOpenOutlined />;
  if (entry.preview_kind === 'image') return <FileImageOutlined />;
  if (entry.preview_kind === 'text') return <FileTextOutlined />;
  return <FileOutlined />;
};

const WorkspaceFilesPanel: React.FC<Props> = ({
  workingDirectory,
  entries,
  truncated,
  isRefreshing,
  onRefresh,
  onReadFile,
}) => {
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [preview, setPreview] = useState<WorkspaceFilePreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  useEffect(() => {
    if (selectedPath && !entries.some((entry) => entry.path === selectedPath)) {
      setSelectedPath(null);
      setPreview(null);
      setPreviewLoading(false);
    }
  }, [entries, selectedPath]);

  useEffect(() => {
    if (!selectedPath) return;
    let active = true;
    setPreview(null);
    setPreviewLoading(true);
    onReadFile(selectedPath)
      .then((result) => {
        if (active) setPreview(result);
      })
      .catch(() => {
        if (active) setPreview(null);
      })
      .finally(() => {
        if (active) setPreviewLoading(false);
      });
    return () => { active = false; };
  }, [onReadFile, selectedPath]);

  const copyDirectory = async () => {
    try {
      await navigator.clipboard.writeText(workingDirectory);
      message.success('工作目录已复制');
    } catch {
      message.error('复制失败');
    }
  };

  return (
    <aside className="workspace-files-panel animate-slide-in-right">
      <div className="workspace-files-header">
        <div>
          <div className="workspace-files-title">工作目录</div>
          <div className="workspace-files-path" title={workingDirectory}>{workingDirectory}</div>
        </div>
        <div className="workspace-files-actions">
          <button type="button" aria-label="复制工作目录" onClick={copyDirectory} disabled={!workingDirectory}>
            <CopyOutlined />
          </button>
          <button type="button" aria-label="刷新文件" onClick={onRefresh} disabled={isRefreshing}>
            <ReloadOutlined spin={isRefreshing} />
          </button>
        </div>
      </div>

      <div className="workspace-files-tree" aria-label="工作目录文件">
        {isRefreshing ? (
          <div className="workspace-file-preview-state"><Spin size="small" /></div>
        ) : entries.length === 0 ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="目录为空" />
        ) : entries.map((entry) => (
          <button
            type="button"
            key={entry.path}
            className={`workspace-file-row${selectedPath === entry.path ? ' active' : ''}`}
            style={{ paddingLeft: `${12 + entry.depth * 16}px` }}
            disabled={entry.is_directory}
            onClick={() => setSelectedPath(entry.path)}
          >
            <FileIcon entry={entry} />
            <span className="workspace-file-name" title={entry.path}>{entry.name}</span>
            {!entry.is_directory && <span className="workspace-file-size">{formatSize(entry.size)}</span>}
          </button>
        ))}
        {truncated && <div className="workspace-files-truncated">仅显示前 500 项</div>}
      </div>

      <div className="workspace-file-preview">
        {previewLoading ? (
          <div className="workspace-file-preview-state"><Spin size="small" /></div>
        ) : !preview ? (
          <div className="workspace-file-preview-state">选择文件查看内容</div>
        ) : (
          <>
            <div className="workspace-file-preview-head">
              <span title={preview.path}>{preview.name}</span>
              <small>{formatSize(preview.size)}</small>
            </div>
            <div className="workspace-file-preview-body">
              {preview.preview_kind === 'text' && <pre>{preview.content}</pre>}
              {preview.preview_kind === 'image' && preview.data_url && (
                <img src={preview.data_url} alt={preview.name} />
              )}
              {preview.preview_kind === 'image' && !preview.data_url && (
                <div className="workspace-file-preview-state">图片较大，暂不支持在线预览</div>
              )}
              {preview.preview_kind === 'binary' && (
                <div className="workspace-file-preview-state">该文件暂不支持在线预览</div>
              )}
            </div>
            {preview.truncated && (
              <div className="workspace-file-preview-truncated">文件较大，仅展示部分内容</div>
            )}
          </>
        )}
      </div>
    </aside>
  );
};

export default WorkspaceFilesPanel;
