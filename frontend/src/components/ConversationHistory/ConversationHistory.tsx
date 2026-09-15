import React, { useEffect, useMemo } from 'react';
import { Typography, Button, Spin, Dropdown, Modal, message } from 'antd';
import {
  PlusOutlined,
  DeleteOutlined,
  ClearOutlined,
  EllipsisOutlined,
} from '@ant-design/icons';
import { useConversationStore } from '@/stores/useConversationStore';
import type { Conversation } from '@/stores/useConversationStore';
import './ConversationHistory.css';

const { Text } = Typography;

/**
 * Conversation history — designed as a "creative archive": conversations are the
 * work sessions in an AI agent studio, so the list is grouped by recency
 * (today / yesterday / this week / earlier) and each row shows the last message
 * preview so recognition relies on content, not just titles.
 */

/** Curated avatar tints. Applied as a soft tinted chip (≈15% bg + full-color
 *  glyph) so they read as sophisticated pastel marks that survive both themes,
 *  and lead with the brand amber. */
const AVATAR_TINTS = [
  '#D97706', // brand amber
  '#059669', // emerald
  '#4F46E5', // indigo
  '#DB2777', // pink
  '#0891B2', // cyan
  '#7C3AED', // violet
];

/** Stable hash → tint + monogram, so a conversation's avatar never reshuffles
 *  between renders. Coerces to string and falls back to the brand tint so a
 *  stray entry missing its id (e.g. stale persisted state) can never crash. */
const getTint = (id?: string) => {
  const key = id == null ? '' : String(id);
  if (!key) return AVATAR_TINTS[0];
  let hash = 0;
  for (let i = 0; i < key.length; i++) hash = (hash * 31 + key.charCodeAt(i)) >>> 0;
  return AVATAR_TINTS[hash % AVATAR_TINTS.length];
};

const getMonogram = (title?: string) => {
  const ch = (title || '').trim()[0];
  return ch || '对';
};

const isUser = (role?: string) =>
  !!role && (role === 'user' || role === 'human' || role === 'me');

const TIME_GROUPS = [
  { key: 'today', label: '今天' },
  { key: 'yesterday', label: '昨天' },
  { key: 'week', label: '本周' },
  { key: 'earlier', label: '更早' },
] as const;

type GroupKey = (typeof TIME_GROUPS)[number]['key'];

const bucketOf = (dateStr?: string): GroupKey => {
  if (!dateStr) return 'earlier';
  const d = new Date(dateStr);
  if (Number.isNaN(d.getTime())) return 'earlier';
  const now = new Date();
  const startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const ts = d.getTime();
  const day = 86_400_000;
  if (ts >= startToday) return 'today';
  if (ts >= startToday - day) return 'yesterday';
  if (ts >= startToday - 6 * day) return 'week';
  return 'earlier';
};

const formatTime = (dateStr?: string) => {
  if (!dateStr) return '';
  const d = new Date(dateStr);
  if (Number.isNaN(d.getTime())) return '';
  const now = new Date();
  if (d.toDateString() === now.toDateString())
    return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
  const yest = new Date(now);
  yest.setDate(now.getDate() - 1);
  if (d.toDateString() === yest.toDateString()) return '昨天';
  const days = Math.floor((now.getTime() - d.getTime()) / 86_400_000);
  if (days < 7) return `${days} 天前`;
  return d.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' });
};

interface ConversationHistoryProps {
  onConversationSelect: (conversationId: string) => void;
  activeConversationId?: string | null;
}

const ConversationHistory: React.FC<ConversationHistoryProps> = ({
  onConversationSelect,
  activeConversationId,
}) => {
  const {
    conversations,
    isLoading,
    error,
    fetchConversations,
    deleteConversation,
    clearConversation,
    setCurrentConversation,
    clearError,
  } = useConversationStore();

  useEffect(() => {
    fetchConversations();
  }, [fetchConversations]);

  const handleCreateConversation = () => {
    clearError();
    setCurrentConversation(null);
    onConversationSelect('');
  };

  const handleDeleteConversation = async (conversationId: string) => {
    try {
      await deleteConversation(conversationId);
      if (activeConversationId === conversationId) onConversationSelect('');
      message.success('对话已删除');
    } catch {
      message.error('删除对话失败');
    }
  };

  const handleClearConversation = async (conversationId: string) => {
    try {
      await clearConversation(conversationId);
      message.success('对话已清空');
    } catch {
      message.error('清空对话失败');
    }
  };

  const handleMenuClick = (conversationId: string, key: string) => {
    if (key === 'clear') {
      Modal.confirm({
        title: '清空对话',
        content: '确定要清空该对话的所有消息吗?',
        okText: '确定',
        cancelText: '取消',
        onOk: () => handleClearConversation(conversationId),
      });
    } else if (key === 'delete') {
      Modal.confirm({
        title: '删除对话',
        content: '确定要删除该对话吗?',
        okText: '确定',
        okButtonProps: { danger: true },
        cancelText: '取消',
        onOk: () => handleDeleteConversation(conversationId),
      });
    }
  };

  // Bucket conversations by recency, newest first within each bucket, and drop
  // empty buckets. useMemo so the ordering work doesn't run every render.
  const groups = useMemo(() => {
    const sorted = [...conversations].sort((a, b) => {
      const ta = new Date(a.updated_at).getTime() || 0;
      const tb = new Date(b.updated_at).getTime() || 0;
      return tb - ta;
    });
    return TIME_GROUPS.map((g) => ({
      ...g,
      items: sorted.filter((c) => bucketOf(c.updated_at || c.last_message?.created_at) === g.key),
    })).filter((g) => g.items.length > 0);
  }, [conversations]);

  if (isLoading && conversations.length === 0) {
    return (
      <div className="conversation-history-loading">
        <Spin size="small" />
        <Text type="secondary">加载中...</Text>
      </div>
    );
  }

  if (error && conversations.length === 0) {
    return (
      <div className="conversation-history-error">
        <Text type="danger">{error}</Text>
        <Button size="small" onClick={() => fetchConversations()}>
          重试
        </Button>
      </div>
    );
  }

  if (conversations.length === 0) {
    return (
      <div className="conversation-history-empty">
        <div className="ch-empty-mark">✶</div>
        <Text className="ch-empty-title">开启你的第一次对话</Text>
        <Text className="ch-empty-sub">和 AI 一起，从一句话开始处理任务。</Text>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={handleCreateConversation}
          size="small"
        >
          新建对话
        </Button>
      </div>
    );
  }

  const previewOf = (c: Conversation) => {
    const lm = c.last_message;
    if (!lm?.content) return '暂无消息';
    const prefix = isUser(lm.role) ? '你：' : '';
    return prefix + lm.content.replace(/\s+/g, ' ').trim();
  };

  return (
    <div className="conversation-history">
      <div className="conversation-history-header">
        <div className="ch-header-label">
          <span>对话</span>
          <span className="ch-header-count">{conversations.length}</span>
        </div>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={handleCreateConversation}
          size="small"
        >
          新建
        </Button>
      </div>

      <div className="conversation-list">
        {groups.map((group) => (
          <section className="conversation-group" key={group.key}>
            <div className="conversation-group-label">{group.label}</div>
            {group.items.map((c) => {
              const tint = getTint(c.id);
              const isActive = activeConversationId === c.id;
              return (
                <div
                  key={c.id}
                  className={`conversation-item ${isActive ? 'active' : ''}`}
                  onClick={() => onConversationSelect(c.id)}
                >
                  <div
                    className="conversation-avatar"
                    style={{
                      background: `color-mix(in srgb, ${tint} 16%, transparent)`,
                      color: tint,
                    }}
                  >
                    {getMonogram(c.title)}
                  </div>

                  <div className="conversation-main">
                    <div className="conversation-head">
                      <Text
                        className="conversation-title"
                        ellipsis={{ tooltip: c.title || '未命名对话' }}
                      >
                        {c.title || '未命名对话'}
                      </Text>
                      <Dropdown
                        trigger={['click']}
                        placement="bottomRight"
                        menu={{
                          items: [
                            { key: 'clear', icon: <ClearOutlined />, label: '清空对话' },
                            { type: 'divider' as const },
                            {
                              key: 'delete',
                              icon: <DeleteOutlined />,
                              label: '删除对话',
                              danger: true,
                            },
                          ],
                          onClick: ({ key, domEvent }) => {
                            domEvent.stopPropagation();
                            handleMenuClick(c.id, key);
                          },
                        }}
                      >
                        <Button
                          type="text"
                          icon={<EllipsisOutlined />}
                          size="small"
                          className="conversation-more-btn"
                          onClick={(e: React.MouseEvent) => e.stopPropagation()}
                        />
                      </Dropdown>
                    </div>
                    <div className="conversation-sub">
                      <span className="conversation-preview">{previewOf(c)}</span>
                      <span className="conversation-time">
                        {formatTime(c.last_message?.created_at || c.updated_at)}
                      </span>
                    </div>
                  </div>
                </div>
              );
            })}
          </section>
        ))}
      </div>
    </div>
  );
};

export default ConversationHistory;
