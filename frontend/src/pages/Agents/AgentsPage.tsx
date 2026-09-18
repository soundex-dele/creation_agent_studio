import React, { useEffect, useState, useRef } from 'react';
import { Button, Empty, Input, Popconfirm, Spin, Tag, message } from 'antd';
import { DeleteOutlined, EditOutlined, PlusOutlined, SearchOutlined } from '@ant-design/icons';
import { useAgentStore } from '@/stores/useAgentStore';
import AgentDetailModal from '@/components/Agents/AgentDetailModal';
import AgentEditorModal from '@/components/Agents/AgentEditorModal';
import { api } from '@/services/api';
import { useAuthStore } from '@/stores/useAuthStore';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import './AgentsPage.css';

const { Search } = Input;

const AGENT_ICONS = ['🎬', '✍️', '🎙️', '✂️', '🎨', '🎵', '💡', '🔧'];

const AgentsPage: React.FC = () => {
  const user = useAuthStore((state) => state.user);
  const { organizations, currentOrganizationId } = useOrganizationStore();
  const currentRole = organizations.find((item) => item.id === currentOrganizationId)?.role;
  const canCreateAgent = user?.role === 'admin'
    || ['owner', 'admin', 'developer'].includes(currentRole ?? '');
  const [selectedAgentId, setSelectedAgentId] = useState<number | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingAgentId, setEditingAgentId] = useState<number | null>(null);
  const [deletingAgentId, setDeletingAgentId] = useState<number | null>(null);
  const {
    agents,
    isLoading,
    selectedCategory,
    searchQuery,
    loadAgents,
    setSearchQuery,
  } = useAgentStore();

  const isFirstRun = useRef(true);

  useEffect(() => {
    // First load fires immediately; later category/search changes are debounced.
    // The isFirstRun guard avoids a second fetch on the initial mount.
    if (isFirstRun.current) {
      isFirstRun.current = false;
      loadAgents(selectedCategory || undefined);
      return;
    }
    const timer = setTimeout(() => {
      loadAgents(selectedCategory || undefined);
    }, 300);
    return () => clearTimeout(timer);
  }, [selectedCategory, searchQuery, loadAgents]);

  const openEditor = (agentId: number | null) => {
    setEditingAgentId(agentId);
    setEditorOpen(true);
  };

  const handleDelete = async (agentId: number) => {
    setDeletingAgentId(agentId);
    try {
      await api.delete(`/agents/${agentId}/`);
      message.success('智能体已删除');
      await loadAgents(selectedCategory || undefined);
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '删除智能体失败');
    } finally {
      setDeletingAgentId(null);
    }
  };

  return (
    <div className="agents-page animate-fade-in">
      <div className="page-header">
        <h1 className="page-title">智能体市场</h1>
        <p className="page-subtitle">选择或创建智能体，让 AI 协助你处理不同场景的任务</p>
      </div>

      <div className="page-toolbar">
        {canCreateAgent && (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => openEditor(null)}>
            新建智能体
          </Button>
        )}
        <Search
          placeholder="搜索智能体..."
          prefix={<SearchOutlined className="text-text-dim" />}
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          allowClear
          className="max-w-xs"
        />
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-20">
          <Spin size="large" />
        </div>
      ) : agents.length === 0 ? (
        <div className="flex items-center justify-center py-20">
          <Empty description={<span className="text-text-sec">暂无智能体</span>} />
        </div>
      ) : (
        <div className="agent-grid">
          {agents.map((agent, index) => (
            <div
              key={agent.id}
              className="agent-card"
              style={{ animationDelay: `${index * 60}ms` }}
              onClick={() => { setSelectedAgentId(agent.id); setModalOpen(true); }}
            >
              <div className={`agent-card-icon icon-gradient-${(index % 6) + 1}`}>
                {agent.icon || AGENT_ICONS[index % AGENT_ICONS.length]}
              </div>
              <div className="agent-card-name">{agent.name}</div>
              {(agent.can_edit || agent.can_delete) && (
                <div className="agent-card-actions" onClick={(event) => event.stopPropagation()}>
                  {agent.can_edit && (
                    <Button
                      type="text"
                      size="small"
                      icon={<EditOutlined />}
                      aria-label={`编辑 ${agent.name}`}
                      onClick={() => openEditor(agent.id)}
                    />
                  )}
                  {agent.can_delete && (
                    <Popconfirm
                      title="删除智能体"
                      description={`确定删除“${agent.name}”吗？此操作不可撤销。`}
                      okText="删除"
                      cancelText="取消"
                      okButtonProps={{ danger: true }}
                      onConfirm={() => handleDelete(agent.id)}
                    >
                      <Button
                        type="text"
                        danger
                        size="small"
                        icon={<DeleteOutlined />}
                        loading={deletingAgentId === agent.id}
                        aria-label={`删除 ${agent.name}`}
                      />
                    </Popconfirm>
                  )}
                </div>
              )}
              <div className="agent-card-desc">{agent.description}</div>
              <div className="agent-card-footer">
                <Tag className="agent-tag">{agent.category_name}</Tag>
                <span className="agent-card-meta">⚡ {((agent as any).usage_count || 0).toLocaleString()} 次使用</span>
              </div>
            </div>
          ))}
        </div>
      )}

      <AgentDetailModal
        agentId={selectedAgentId}
        open={modalOpen}
        onClose={() => { setModalOpen(false); setSelectedAgentId(null); }}
      />
      <AgentEditorModal
        agentId={editingAgentId}
        open={editorOpen}
        onClose={() => { setEditorOpen(false); setEditingAgentId(null); }}
        onSaved={() => loadAgents(selectedCategory || undefined)}
      />
    </div>
  );
};

export default AgentsPage;
