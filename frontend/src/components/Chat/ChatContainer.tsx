import React, { useEffect, useRef, useState } from 'react';
import { Alert } from 'antd';
import { useConversationStore } from '@/stores/useConversationStore';
import type { ConversationDetail } from '@/stores/useConversationStore';
import { useAuthStore } from '@/stores/useAuthStore';
import MessageList from './MessageList';
import MessageInput from './MessageInput';
import type { ComposerAgent, ComposerContext } from './MessageInput';
import AgentQuestionCard from './AgentQuestionCard';
import './ChatContainer.css';

interface ChatSuggestion {
  icon?: string;
  label: string;
  text?: string;
  onSelect?: () => void;
}

interface ChatContainerProps {
  conversationId: string | null;
  /** When false, skip auto-fetching the conversation on mount/id change.
   *  The workspace uses this to seed a guided conversation without a fetch
   *  clobbering the streamed placeholder message. Default: true. */
  autoFetch?: boolean;
  /** Allow the home page to remain a local draft until its first message. */
  createOnFirstSend?: boolean;
  onConversationCreated?: (conversationId: string) => void;
  creationContext?: {
    applicationId?: number;
    workflowStepRunId?: string;
    agentId?: number;
    skillIds?: string[];
  };
  suggestions?: ChatSuggestion[];
  emptyTitle?: string;
  emptyDescription?: string;
  inputPlaceholder?: string;
  draftRequest?: { id: number; text: string } | null;
  projectId?: number;
  defaultAgent?: ComposerAgent | null;
}

const defaultSuggestions: ChatSuggestion[] = [
  { icon: '🧭', label: '制定行动计划', text: '帮我把这个目标拆解成清晰的行动计划' },
  { icon: '📝', label: '整理信息要点', text: '帮我整理这段信息的重点和待办事项' },
  { icon: '💡', label: '分析解决方案', text: '分析这个问题，并给出几种可行方案及其取舍' },
];

const ChatContainer: React.FC<ChatContainerProps> = ({
  conversationId,
  autoFetch = true,
  createOnFirstSend = false,
  onConversationCreated,
  creationContext,
  suggestions = defaultSuggestions,
  emptyTitle,
  emptyDescription,
  inputPlaceholder,
  draftRequest,
  projectId,
  defaultAgent = null,
}) => {
  const { user } = useAuthStore();
  const {
    currentConversation,
    isLoading,
    error,
    streamingMessageId,
    pendingQuestion,
    agentActivity,
    fetchConversationDetail,
    createConversation,
    sendMessageStream,
    answerQuestion,
    cancelTurn,
    clearError,
    setCurrentConversation,
  } = useConversationStore();

  const messagesContainerRef = useRef<HTMLDivElement>(null);
  const shouldAutoScrollRef = useRef(true);
  const abortControllerRef = useRef<AbortController | null>(null);
  const creatingConversationRef = useRef(false);
  const skipNextFetchRef = useRef<string | null>(null);
  const appliedDraftRequestIdRef = useRef<number | null>(null);
  const [inputValue, setInputValue] = useState('');
  const [isCreatingConversation, setIsCreatingConversation] = useState(false);

  useEffect(() => {
    shouldAutoScrollRef.current = true;
    if (conversationId) {
      if (skipNextFetchRef.current === conversationId) {
        skipNextFetchRef.current = null;
      } else if (autoFetch) {
        fetchConversationDetail(conversationId);
      }
    } else {
      setCurrentConversation(null);
    }
  }, [conversationId, autoFetch, fetchConversationDetail, setCurrentConversation]);

  useEffect(() => {
    const container = messagesContainerRef.current;
    if (!container || !shouldAutoScrollRef.current) return;
    container.scrollTo({ top: container.scrollHeight, behavior: 'auto' });
  }, [currentConversation?.messages, isLoading, streamingMessageId]);

  useEffect(() => {
    return () => {
      abortControllerRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    if (!draftRequest || appliedDraftRequestIdRef.current === draftRequest.id) return;
    appliedDraftRequestIdRef.current = draftRequest.id;
    setInputValue(draftRequest.text);
  }, [draftRequest]);

  const handleSendMessage = async (content: string, composer: ComposerContext) => {
    if (creatingConversationRef.current) return;
    shouldAutoScrollRef.current = true;

    let targetConversationId = conversationId;
    if (!targetConversationId) {
      if (!createOnFirstSend) return;
      creatingConversationRef.current = true;
      setIsCreatingConversation(true);
      try {
        const conversation = await createConversation(
          content.slice(0, 50),
          composer.agentId ?? undefined,
          composer.projectId ?? projectId,
          undefined,
          {
            ...creationContext,
            workingDirectory: composer.workingDirectory,
          },
        );
        // DRF may serialize numeric primary keys even though the frontend route
        // always exposes them as strings. Keep both forms identical so the URL
        // update does not trigger a detail fetch that overwrites this stream.
        targetConversationId = String(conversation.id);
        setCurrentConversation({
          ...conversation,
          id: targetConversationId,
          messages: [],
        } as ConversationDetail);
      } catch (error) {
        console.error('Failed to create conversation:', error);
        return;
      } finally {
        creatingConversationRef.current = false;
        setIsCreatingConversation(false);
      }
    }

    abortControllerRef.current?.abort();
    try {
      const activeConversation = useConversationStore.getState().currentConversation;
      if (activeConversation && composer.agent) {
        setCurrentConversation({
          ...activeConversation,
          agent: composer.agent,
        });
      }
      const controller = sendMessageStream(targetConversationId, content, {
        permissionMode: composer.permissionMode,
        skillNames: composer.skillNames,
        agentId: composer.agentId,
      });
      abortControllerRef.current = controller;
      if (!conversationId) {
        skipNextFetchRef.current = targetConversationId;
        onConversationCreated?.(targetConversationId);
      }
    } catch (error) {
      console.error('Failed to start stream:', error);
    }
  };

  const handleUseSuggestion = (suggestion: (typeof suggestions)[number]) => {
    if (suggestion.onSelect) suggestion.onSelect();
    else if (suggestion.text) setInputValue(suggestion.text);
  };

  const handleMessagesScroll = () => {
    const container = messagesContainerRef.current;
    if (!container) return;
    const distanceFromBottom = (
      container.scrollHeight - container.scrollTop - container.clientHeight
    );
    shouldAutoScrollRef.current = distanceFromBottom <= 96;
  };

  const isStreaming = streamingMessageId !== null;
  const messages = currentConversation?.messages || [];
  // The first optimistic messages are added just before the URL receives its
  // conversation id. Render them immediately instead of keeping the welcome
  // screen visible during that transition.
  const isEmpty = messages.length === 0;
  const agent = currentConversation?.agent;

  if (error) {
    return (
      <div className="flex h-full items-start justify-center p-6">
        <Alert
          message="Agent 执行失败"
          description={error}
          type="error"
          showIcon
          closable
          onClose={clearError}
        />
      </div>
    );
  }

  return (
    <div className="chat-container">
      {isEmpty && !isLoading ? (
        <div className="chat-empty">
          <div className="chat-empty-icon">{agent?.icon || '✦'}</div>
          <h3>{emptyTitle || (agent ? `我是${agent.name}，请问有什么可以帮您？` : '开始处理你的任务')}</h3>
          <p>
            {emptyDescription || (agent
              ? `向${agent.name}描述你的目标、背景和约束，它会根据自身能力协助你完成任务`
              : '描述你的目标、背景和约束，或选择一个更适合当前场景的智能体')}
          </p>
          <div className="chat-empty-suggestions">
            {suggestions.map((s) => (
              <button
                key={s.label}
                className="chat-suggestion"
                onClick={() => handleUseSuggestion(s)}
              >
                {s.icon || '✦'} {s.label}
              </button>
            ))}
          </div>
        </div>
      ) : (
        <>
          <div
            ref={messagesContainerRef}
            className="chat-messages"
            onScroll={handleMessagesScroll}
          >
            <div className="chat-messages-inner">
              <MessageList messages={messages} isLoading={isLoading} isStreaming={isStreaming} />
              {agentActivity && isStreaming && (
                <div className="agent-activity">{agentActivity}</div>
              )}
              {pendingQuestion && conversationId && (
                <AgentQuestionCard
                  question={pendingQuestion}
                  onAnswer={(answer) => answerQuestion(conversationId, answer)}
                  onCancel={() => cancelTurn(conversationId)}
                />
              )}
            </div>
          </div>
        </>
      )}

      <div className="chat-input-area">
        <div className="chat-input-wrapper">
          <MessageInput
            value={inputValue}
            onValueChange={setInputValue}
            onSendMessage={handleSendMessage}
            currentAgent={currentConversation?.agent || defaultAgent}
            workspaceLocked={Boolean(
              conversationId || projectId || creationContext?.applicationId
              || creationContext?.workflowStepRunId
            )}
            disabled={
              !user || isLoading || isCreatingConversation || isStreaming
              || (!conversationId && !createOnFirstSend)
            }
            placeholder={user ? (inputPlaceholder || '描述你的需求... (Enter 发送，Shift+Enter 换行)') : '请先登录'}
          />
          <div className="chat-input-hint">
            {isStreaming && conversationId ? (
              <button className="agent-cancel-link" onClick={() => void cancelTurn(conversationId)}>
                停止当前任务
              </button>
            ) : 'Enter 发送 · Shift+Enter 换行'}
          </div>
        </div>
      </div>
    </div>
  );
};

export default ChatContainer;
