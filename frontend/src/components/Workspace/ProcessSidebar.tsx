import React from 'react';
import { Button } from 'antd';
import { ArrowLeftOutlined, CheckCircleFilled } from '@ant-design/icons';
import type { WorkflowProcess, WorkspaceProject } from '@/types/workflow';

interface ProcessSidebarProps {
  project: WorkspaceProject;
  processes: WorkflowProcess[];
  activeProcessId: string | null;
  /** processId -> conversation exists (chat started) */
  startedMap: Record<string, boolean>;
  onSelect: (processId: string) => void;
  onBack: () => void;
}

const ProcessSidebar: React.FC<ProcessSidebarProps> = ({
  project,
  processes,
  activeProcessId,
  startedMap,
  onSelect,
  onBack,
}) => {
  return (
    <aside className="ws-sidebar">
      <div className="ws-sidebar-head">
        <Button
          type="text"
          size="small"
          icon={<ArrowLeftOutlined />}
          onClick={onBack}
          className="ws-back-btn"
        >
          应用中心
        </Button>
        <div className="ws-workspace-title">{project.title}</div>
      </div>

      <div className="ws-sidebar-section-title">任务流程</div>
      <nav className="ws-process-nav">
        {processes.map((p, i) => {
          const active = p.id === activeProcessId;
          const started = !!startedMap[p.id];
          return (
            <button
              key={p.id}
              className={`ws-process-item ${active ? 'active' : ''}`}
              onClick={() => onSelect(p.id)}
            >
              <div className="ws-process-item-icon">{p.icon || '✨'}</div>
              <div className="ws-process-item-body">
                <div className="ws-process-item-name">
                  <span className="ws-process-item-idx">{i + 1}.</span> {p.name}
                </div>
                <div className="ws-process-item-desc">
                  {p.mode === 'guided' ? '引导式对话' : '自由对话'}
                </div>
              </div>
              {started && (
                <CheckCircleFilled className="ws-process-item-done" />
              )}
            </button>
          );
        })}
      </nav>
    </aside>
  );
};

export default ProcessSidebar;
