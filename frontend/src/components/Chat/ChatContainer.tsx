import React, { useEffect, useId, useMemo, useRef, useState } from 'react';
import { Alert, message } from 'antd';
import { DownOutlined, MessageOutlined, StopOutlined, UpOutlined } from '@ant-design/icons';
import { useChatConnection } from './ChatConnectionContext';
import type { ConversationDetail } from '@/stores/useConversationStore';
import { useAuthStore } from '@/stores/useAuthStore';
import useMediaQuery from '@/hooks/useMediaQuery';
import MessageList from './MessageList';
import type { AssistantMessageRenderContext } from './MessageList';
import MessageInput from './MessageInput';
import type { ComposerAgent, ComposerContext } from './MessageInput';
import AgentQuestionCard from './AgentQuestionCard';
import ChatWorkspaceSidebar from './ChatWorkspaceSidebar';
import './ChatContainer.css';

interface ChatSuggestion {
  icon?: string;
  label: string;
  text?: string;
  onSelect?: () => void;
}

export interface ChatContainerProps {
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
  composerMode?: 'default' | 'study' | 'document';
  inputAccessory?: React.ReactNode;
  /** Allows a feature page to specialize assistant presentation while keeping
   * the shared conversation, streaming, attachments, and composer behavior. */
  renderAssistantContent?: (
    context: AssistantMessageRenderContext,
  ) => React.ReactNode | undefined;
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
  composerMode = 'default',
  inputAccessory,
  renderAssistantContent,
}) => {
  const { store: useConversationStore, api, remote, online } = useChatConnection();
  const { user } = useAuthStore();
  const isMobile = useMediaQuery('(max-width: 767px)');
  const composerId = useId();
  const {
    currentConversation: storedConversation,
    isLoading,
    error,
    streamingMessageId: storedStreamingMessageId,
    pendingQuestion: storedPendingQuestion,
    agentActivity: storedAgentActivity,
    fetchConversationDetail,
    createConversation,
    sendMessageStream,
    answerQuestion,
    cancelTurn,
    clearError,
    setCurrentConversation,
    disconnect,
    refreshIfIdle,
  } = useConversationStore();

  const messagesContainerRef = useRef<HTMLDivElement>(null);
  const shouldAutoScrollRef = useRef(true);
  const abortControllerRef = useRef<ReturnType<typeof sendMessageStream> | null>(null);
  const creatingConversationRef = useRef(false);
  const skipNextFetchRef = useRef<string | null>(null);
  const appliedDraftRequestIdRef = useRef<number | null>(null);
  const [inputValue, setInputValue] = useState('');
  const [isCreatingConversation, setIsCreatingConversation] = useState(false);
  const [composerExpanded, setComposerExpanded] = useState(false);
  const [isStopping, setIsStopping] = useState(false);
  const stoppingRef = useRef(false);
  const workspaceChangingRef = useRef(false);
  const [workspaceChanging, setWorkspaceChanging] = useState(false);

  const ownsConversation = Boolean(storedConversation && (
    String(storedConversation.id) === conversationId
    || (!conversationId && skipNextFetchRef.current === String(storedConversation.id))
  ));
  const currentConversation = ownsConversation ? storedConversation : null;
  const streamingMessageId = ownsConversation ? storedStreamingMessageId : null;
  const pendingQuestion = ownsConversation ? storedPendingQuestion : null;
  const agentActivity = ownsConversation ? storedAgentActivity : null;
  const workspace = useMemo(() => currentConversation ? {
    projectId: currentConversation.project ?? undefined,
    workingDirectory: currentConversation.working_directory,
  } : undefined, [currentConversation]);

  const handleWorkspaceChange = async (selection: Pick<ComposerContext, 'projectId' | 'workingDirectory'>) => {
    if (!conversationId || !online || workspaceChangingRef.current) throw new Error('工作空间暂不可修改');
    workspaceChangingRef.current = true;
    setWorkspaceChanging(true);
    try {
      const updated = await api.post<ConversationDetail>(`/conversations/${conversationId}/workspace/`, {
        project_id: selection.projectId ?? null,
        working_directory: selection.workingDirectory || '',
      });
      const state = useConversationStore.getState();
      if (String(state.currentConversation?.id) === conversationId) {
        setCurrentConversation({ ...state.currentConversation!, ...updated, id: conversationId });
      }
    } finally {
      workspaceChangingRef.current = false;
      setWorkspaceChanging(false);
    }
  };

  useEffect(() => {
    setComposerExpanded(false);
  }, [conversationId]);

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
      disconnect();
    };
  }, [disconnect]);

  useEffect(() => {
    if (!conversationId || !online) return;
    const timer = setInterval(() => {
      void refreshIfIdle(conversationId).catch(() => undefined);
    }, 5000);
    return () => clearInterval(timer);
  }, [conversationId, online, refreshIfIdle]);

  useEffect(() => {
    if (!draftRequest || appliedDraftRequestIdRef.current === draftRequest.id) return;
    appliedDraftRequestIdRef.current = draftRequest.id;
    setInputValue(draftRequest.text);
    setComposerExpanded(true);
  }, [draftRequest]);

  const handleSendMessage = async (
    content: string,
    composer: ComposerContext,
    images: File[],
  ) => {
    if (creatingConversationRef.current || workspaceChangingRef.current || !online) throw new Error('电脑当前不可用，草稿已保留。');
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
        throw error;
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
        collaborationMode: composer.collaborationMode,
        skillNames: composer.skillNames,
        agentId: composer.agentId ?? (creationContext?.applicationId ? activeConversation?.agent?.id : null),
        images,
      });
      abortControllerRef.current = controller;
      if (!conversationId) {
        skipNextFetchRef.current = targetConversationId;
        onConversationCreated?.(targetConversationId);
      }
      await controller.submitted;
      setComposerExpanded(false);
    } catch (error) {
      console.error('Failed to start stream:', error);
      throw error;
    }
  };

  const handleStop = async () => {
    if (!online || stoppingRef.current) return;
    const targetId = currentConversation?.id;
    if (!targetId || useConversationStore.getState().currentConversation?.id !== targetId) return;
    stoppingRef.current = true;
    setIsStopping(true);
    try {
      // A stop pressed during submission must wait for the server's run id.
      if (!useConversationStore.getState().activeRun) {
        await abortControllerRef.current?.submitted;
      }
      const state = useConversationStore.getState();
      if (state.currentConversation?.id === targetId
        && (state.streamingMessageId || state.pendingQuestion)) {
        await cancelTurn(targetId);
      }
    } catch {
      message.error('结束任务失败，请重试');
    } finally {
      stoppingRef.current = false;
      setIsStopping(false);
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
  const isRunning = isStreaming || Boolean(pendingQuestion);
  const canCollapseComposer = isMobile && !isEmpty;
  const composerVisible = !canCollapseComposer || composerExpanded;
  const agent = currentConversation?.agent;
  const showWorkspaceSidebar = Boolean(conversationId && !remote && composerMode !== 'document');

  useEffect(() => {
    const container = messagesContainerRef.current;
    if (container && shouldAutoScrollRef.current) {
      container.scrollTo({ top: container.scrollHeight, behavior: 'auto' });
    }
  }, [composerVisible]);

  return (
    <div className={`chat-container${showWorkspaceSidebar ? ' chat-container--with-toolbar' : ''}${!composerVisible ? ' chat-container--composer-collapsed' : ''}`}>
      {error && <Alert message={error} type="error" showIcon closable onClose={clearError} />}
      {showWorkspaceSidebar && conversationId && (
        <ChatWorkspaceSidebar key={conversationId} conversationId={conversationId} />
      )}
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
              <MessageList
                messages={messages}
                isLoading={isLoading}
                isStreaming={isStreaming}
                streamingMessageId={streamingMessageId}
                renderAssistantContent={renderAssistantContent}
              />
              {agentActivity && isStreaming && (
                <div className="agent-activity">{agentActivity}</div>
              )}
              {pendingQuestion && conversationId && (
                <fieldset disabled={!online} style={{ border: 0, padding: 0, margin: 0 }}>
                <AgentQuestionCard
                  question={pendingQuestion}
                  onAnswer={(answer) => answerQuestion(conversationId, answer)}
                  onCancel={() => cancelTurn(conversationId)}
                />
                </fieldset>
              )}
            </div>
          </div>
        </>
      )}

      {inputAccessory && composerVisible && (
        <div className="chat-input-accessory">{inputAccessory}</div>
      )}
      <div className="chat-input-area">
        <div className="chat-input-wrapper">
          {canCollapseComposer && (
            <div className="chat-mobile-controls">
              <button
                type="button"
                className="chat-composer-toggle"
                aria-expanded={composerExpanded}
                aria-controls={composerId}
                onClick={() => setComposerExpanded((expanded) => !expanded)}
              >
                <MessageOutlined aria-hidden="true" />
                <span>{composerExpanded ? '收起聊天' : '聊天'}</span>
                {composerExpanded ? <DownOutlined aria-hidden="true" /> : <UpOutlined aria-hidden="true" />}
              </button>
              {!composerVisible && isRunning && (
                <button
                  type="button"
                  className="chat-mobile-stop"
                  disabled={!online || isStopping}
                  onClick={() => void handleStop()}
                  aria-label="结束任务"
                  title="结束任务"
                  aria-busy={isStopping}
                >
                  <StopOutlined aria-hidden="true" />
                </button>
              )}
            </div>
          )}
          <div id={composerId} hidden={!composerVisible}>
            <MessageInput
              key={remote ? conversationId || 'new' : 'local'}
              value={inputValue}
              onValueChange={setInputValue}
              onSendMessage={handleSendMessage}
              isRunning={isRunning}
              onStop={handleStop}
              stopDisabled={!online || isStopping}
              isStopping={isStopping}
              visible={composerVisible}
              currentAgent={currentConversation?.agent || defaultAgent}
              workspace={remote ? workspace : undefined}
              onWorkspaceChange={remote && conversationId ? handleWorkspaceChange : undefined}
              workspaceLocked={Boolean(
                (conversationId && (!remote || !currentConversation || currentConversation.workspace_locked !== false))
                || projectId || creationContext?.applicationId
                || creationContext?.workflowStepRunId
              )}
              mode={composerMode}
              disabled={
                !user || !online || isLoading || isCreatingConversation || isRunning || workspaceChanging
                || (!conversationId && !createOnFirstSend)
              }
              placeholder={user ? (inputPlaceholder || '描述你的需求...') : '请先登录'}
            />
          </div>
        </div>
      </div>
    </div>
  );
};

export default ChatContainer;
