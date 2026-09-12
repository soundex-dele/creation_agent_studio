import React, { useEffect, useMemo, useState } from 'react';
import { Menu, Empty, Popconfirm } from 'antd';
import { DeleteOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { useAppStore } from '@/stores/useAppStore';
import { useProjectStore } from '@/stores/useProjectStore';
import { api } from '@/services/api';
import type { RunResource } from '@/services/applicationRuntime';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import { tenantApiRoot } from '@/services/tenantContext';

interface AppHistoryItem {
  key: string;
  kind: 'application' | 'workflow';
  title: string;
  subtitle: string;
  icon: string;
  updatedAt: string;
  projectId?: number;
  applicationId?: number;
  conversationId?: number;
  workflowRunId?: string;
}

/**
 * App-center sidebar: category filter plus standalone app workspaces and the
 * application steps actually opened inside workflow runs.
 */
const AppHistorySidebar: React.FC = () => {
  const navigate = useNavigate();
  const { categories, selectedCategory, loadCategories, selectCategory } = useAppStore();
  const { projects, loadProjects, deleteProject } = useProjectStore();
  const organizationId = useOrganizationStore((state) => state.currentOrganizationId);
  const [workflowRuns, setWorkflowRuns] = useState<RunResource[]>([]);

  const historyItems = useMemo<AppHistoryItem[]>(() => {
    const standaloneItems: AppHistoryItem[] = projects
      .filter((project) => project.source === 'application' || !project.source)
      .filter((project) => project.application_kind !== 'chat'
        || Boolean(project.conversation_id))
      .map((project) => ({
        key: `application:${project.id}`,
        kind: 'application',
        title: project.title,
        subtitle: '独立应用',
        icon: '📂',
        updatedAt: project.updated_at,
        projectId: project.id,
        applicationId: project.application_id || undefined,
        conversationId: project.conversation_id || undefined,
      }));
    const workflowItems: AppHistoryItem[] = workflowRuns.map((run) => ({
      key: `workflow:${run.id}`,
      kind: 'workflow',
      title: String(run.definition_snapshot.workflow_name || '工作流 Run'),
      subtitle: `工作流 · ${run.status}`,
      icon: '🔀',
      updatedAt: run.created_at || '',
      workflowRunId: run.id,
    }));
    return [...standaloneItems, ...workflowItems].sort(
      (left, right) => Date.parse(right.updatedAt) - Date.parse(left.updatedAt));
  }, [projects, workflowRuns]);

  useEffect(() => {
    loadCategories();
    loadProjects();
    if (organizationId) {
      api.get<RunResource[]>(`${tenantApiRoot(organizationId)}/runs`, {
        source_type: 'workflow',
      }).then(setWorkflowRuns).catch(() => setWorkflowRuns([]));
    } else {
      setWorkflowRuns([]);
    }
  }, [loadCategories, loadProjects, organizationId]);

  const openHistory = async (item: AppHistoryItem) => {
    try {
      if (item.kind === 'application' && item.projectId) {
        if (item.applicationId) {
          navigate(`/applications/${item.applicationId}/run`);
        } else {
          // Legacy records without an application association retain the old
          // project workspace fallback.
          navigate(`/workspace/${item.projectId}`);
        }
        return;
      }
      if (item.workflowRunId) navigate(`/runs/${item.workflowRunId}`);
    } catch { /* navigation has no recoverable side effect */ }
  };

  const menuItems = [
    { key: 'all', label: '全部应用' },
    ...categories.map((cat) => ({
      key: cat.slug,
      label: `${cat.icon ? cat.icon + ' ' : ''}${cat.name} (${cat.app_count ?? 0})`,
    })),
  ];

  return (
    <div className="tpl-sidebar">
      {/* Category filter */}
      <div className="tpl-sidebar-section">
        <div className="sidebar-title">应用分类</div>
        <Menu
          mode="inline"
          selectedKeys={[selectedCategory || 'all']}
          items={menuItems}
          onClick={({ key }) => selectCategory(key === 'all' ? null : key)}
        />
      </div>

      {/* History: recent workspaces */}
      <div className="tpl-sidebar-section">
        <div className="sidebar-title">历史记录</div>
        {historyItems.length === 0 ? (
          <div className="tpl-sidebar-empty">
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={<span className="text-text-dim">还没有工作空间</span>}
            />
          </div>
        ) : (
          <div className="tpl-history-list">
            {historyItems.map((item) => (
              <div
                key={item.key}
                className="sidebar-item tpl-history-item"
                onClick={() => void openHistory(item)}
              >
                <span className="sidebar-item-icon">{item.icon}</span>
                <div className="tpl-history-body">
                  <div className="tpl-history-title">{item.title}</div>
                  <div className="tpl-history-sub">
                    {item.subtitle} · {new Date(item.updatedAt).toLocaleDateString('zh-CN')}
                  </div>
                </div>
                {item.kind === 'application' && item.projectId && (
                  <Popconfirm
                    title="删除该工作空间？"
                    description="其中的对话与文件将一并删除。"
                    okText="删除"
                    cancelText="取消"
                    okButtonProps={{ danger: true }}
                    onConfirm={(e) => {
                      e?.stopPropagation();
                      deleteProject(item.projectId as number);
                    }}
                    onCancel={(e) => e?.stopPropagation()}
                  >
                    <DeleteOutlined
                      className="tpl-history-delete"
                      onClick={(e) => e.stopPropagation()}
                    />
                  </Popconfirm>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

export default AppHistorySidebar;
