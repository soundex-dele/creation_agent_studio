import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Button, Empty, Input, Select, Spin } from 'antd';
import {
  ArrowRightOutlined,
  PlusOutlined,
  ReloadOutlined,
  SearchOutlined,
} from '@ant-design/icons';
import { useAgentStore } from '@/stores/useAgentStore';
import AgentDetailModal from '@/components/Agents/AgentDetailModal';
import AgentEditorModal from '@/components/Agents/AgentEditorModal';
import { useAuthStore } from '@/stores/useAuthStore';
import { useOrganizationStore } from '@/stores/useOrganizationStore';
import './AgentsPage.css';

const { Search } = Input;
type AgentSort = 'recommended' | 'newest' | 'name';

const AGENT_ICONS = ['🎬', '✍️', '🎙️', '✂️', '🎨', '🎵', '💡', '🔧'];
const visibilityLabels = {
  private: '仅自己',
  restricted: '指定成员',
  organization: '组织可用',
};

const AgentsPage: React.FC = () => {
  const user = useAuthStore((state) => state.user);
  const { organizations, currentOrganizationId } = useOrganizationStore();
  const currentRole = organizations.find((item) => item.id === currentOrganizationId)?.role;
  const canCreateAgent = user?.role === 'admin'
    || ['owner', 'admin', 'developer'].includes(currentRole ?? '');
  const [selectedAgentId, setSelectedAgentId] = useState<number | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [editorOpen, setEditorOpen] = useState(false);
  const [sort, setSort] = useState<AgentSort>('recommended');
  const {
    agents,
    categories,
    isLoading,
    error,
    selectedCategory,
    searchQuery,
    loadAgents,
    loadCategories,
    selectCategory,
    setSearchQuery,
  } = useAgentStore();

  const isFirstRun = useRef(true);

  useEffect(() => { void loadCategories(); }, [loadCategories]);

  useEffect(() => {
    if (isFirstRun.current) {
      isFirstRun.current = false;
      void loadAgents(selectedCategory || undefined);
      return;
    }
    const timer = window.setTimeout(() => {
      void loadAgents(selectedCategory || undefined);
    }, 300);
    return () => window.clearTimeout(timer);
  }, [selectedCategory, searchQuery, loadAgents]);

  const visibleAgents = useMemo(() => [...agents].sort((left, right) => {
    if (sort === 'name') return left.name.localeCompare(right.name, 'zh-CN');
    if (sort === 'newest') {
      return Date.parse(right.created_at || '') - Date.parse(left.created_at || '');
    }
    return 0;
  }), [agents, sort]);

  const openDetail = (agentId: number) => {
    setSelectedAgentId(agentId);
    setModalOpen(true);
  };

  const resetFilters = () => {
    selectCategory(null);
    setSearchQuery('');
  };

  return (
    <div className="agents-page animate-fade-in">
      <div className="agents-heading">
        <div className="page-header">
          <h1 className="page-title">智能体</h1>
          <p className="page-subtitle">选择智能体开始协作，或创建适合团队场景的专属智能体</p>
        </div>
      </div>

      <div className="agents-category-strip" aria-label="智能体分类">
        <button type="button" className={!selectedCategory ? 'active' : ''} onClick={() => selectCategory(null)}>
          全部
        </button>
        {categories.map((category) => (
          <button
            type="button"
            key={category.slug}
            className={selectedCategory === category.slug ? 'active' : ''}
            onClick={() => selectCategory(category.slug)}
          >
            {category.name}
          </button>
        ))}
      </div>

      <div className="page-toolbar agents-toolbar">
        {canCreateAgent && (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setEditorOpen(true)}>
            新建智能体
          </Button>
        )}
        <Search
          placeholder="搜索名称或描述"
          prefix={<SearchOutlined className="text-text-dim" />}
          value={searchQuery}
          onChange={(event) => setSearchQuery(event.target.value)}
          allowClear
          className="agents-search"
        />
        <Select<AgentSort>
          value={sort}
          onChange={setSort}
          className="agents-sort"
          aria-label="智能体排序"
          options={[
            { value: 'recommended', label: '推荐排序' },
            { value: 'newest', label: '最近创建' },
            { value: 'name', label: '名称排序' },
          ]}
        />
        <Button
          icon={<ReloadOutlined />}
          loading={isLoading}
          onClick={() => void Promise.all([
            loadAgents(selectedCategory || undefined),
            loadCategories(),
          ])}
        >刷新</Button>
      </div>

      {isLoading && agents.length === 0 ? (
        <div className="agents-state"><Spin size="large" /></div>
      ) : error ? (
        <div className="agents-state">
          <Empty description={<span className="text-text-sec">{error}</span>}>
            <Button type="primary" onClick={() => void loadAgents(selectedCategory || undefined)}>重新加载</Button>
          </Empty>
        </div>
      ) : visibleAgents.length === 0 ? (
        <div className="agents-state">
          <Empty description={<span className="text-text-sec">暂无匹配智能体</span>}>
            {(selectedCategory || searchQuery) && <Button onClick={resetFilters}>清除筛选</Button>}
          </Empty>
        </div>
      ) : (
        <div className="agent-grid">
          {visibleAgents.map((agent, index) => (
            <article
              key={agent.id}
              className="agent-card"
              style={{ animationDelay: `${Math.min(index, 8) * 45}ms` }}
              onClick={() => openDetail(agent.id)}
              onKeyDown={(event) => {
                if (event.currentTarget === event.target && (event.key === 'Enter' || event.key === ' ')) {
                  event.preventDefault();
                  openDetail(agent.id);
                }
              }}
              role="button"
              tabIndex={0}
            >
              <div className="agent-card-heading">
                <span className={`agent-card-icon icon-gradient-${(index % 6) + 1}`}>
                  {agent.icon || AGENT_ICONS[index % AGENT_ICONS.length]}
                </span>
                <span className="agent-card-category">{agent.category_name}</span>
              </div>
              <div className="agent-card-content">
                <h2 className="agent-card-name">{agent.name}</h2>
                <p className="agent-card-desc">{agent.description}</p>
              </div>
              <div className="agent-card-footer">
                <span className="agent-card-visibility">{visibilityLabels[agent.visibility] || '可使用'}</span>
                <span className="agent-card-open">查看详情 <ArrowRightOutlined /></span>
              </div>
            </article>
          ))}
        </div>
      )}

      <AgentDetailModal
        agentId={selectedAgentId}
        open={modalOpen}
        onClose={() => { setModalOpen(false); setSelectedAgentId(null); }}
      />
      <AgentEditorModal
        agentId={null}
        open={editorOpen}
        onClose={() => setEditorOpen(false)}
        onSaved={() => {
          void loadAgents(selectedCategory || undefined);
          void loadCategories();
        }}
      />
    </div>
  );
};

export default AgentsPage;
