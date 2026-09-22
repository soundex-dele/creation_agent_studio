import React, { type ReactNode } from 'react';
import { Avatar, Button, Image, message as toast, Tooltip, Typography } from 'antd';
import {
  CopyOutlined,
  RobotOutlined,
  ThunderboltOutlined,
  UserOutlined,
} from '@ant-design/icons';
import ReactMarkdown from 'react-markdown';
import rehypeKatex from 'rehype-katex';
import remarkMath from 'remark-math';
import type { AgentToolCall } from '@/entities/run';
import { normalizeMarkdownMath } from '@/lib/markdownMath';
import type { MessageAttachment } from '@/stores/useConversationStore';
import 'katex/dist/katex.min.css';
import './MessageList.css';
import { useChatConnection } from './ChatConnectionContext';

const { Text } = Typography;

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  created_at: string;
  metadata?: {
    composer?: {
      skill_names?: string[];
      skills?: string[];
    };
    graphflow?: {
      tool_calls?: AgentToolCall[];
      loaded_skills?: string[];
    };
    agent?: {
      tool_calls?: AgentToolCall[];
      loaded_skills?: string[];
    };
  };
  attachments?: MessageAttachment[];
}

export interface AssistantMessageRenderContext {
  message: ChatMessage;
  content: string;
  isStreaming: boolean;
}

interface MessageListProps {
  messages: ChatMessage[];
  isLoading?: boolean;
  isStreaming?: boolean;
  streamingMessageId?: string | null;
  renderAssistantContent?: (
    context: AssistantMessageRenderContext,
  ) => ReactNode | undefined;
}

const MessageList: React.FC<MessageListProps> = ({
  messages,
  isLoading = false,
  isStreaming = false,
  streamingMessageId = null,
  renderAssistantContent,
}) => {
  const { remote } = useChatConnection();
  const copyMessageContent = async (content: string) => {
    try {
      await navigator.clipboard.writeText(content);
      toast.success('消息已复制');
    } catch {
      toast.error('复制失败，请稍后重试');
    }
  };

  const formatToolValue = (value: string) => {
    if (!value) return '';
    try {
      return JSON.stringify(JSON.parse(value), null, 2);
    } catch {
      return value;
    }
  };

  const renderToolCall = (toolCall: AgentToolCall, index: number) => {
    const statusText: Record<string, string> = {
      running: '调用中',
      inProgress: '调用中',
      completed: '已完成',
      succeeded: '已完成',
      failed: '失败',
      cancelled: '已取消',
    };
    const hasDetails = Boolean(
      toolCall.input || toolCall.result || toolCall.error_message
    );
    return (
      <details
        key={toolCall.id || `${toolCall.name}-${index}`}
        className={`tool-call-row tool-call-row--${toolCall.status || 'running'}`}
      >
        <summary className="tool-call-summary">
          <span className="tool-call-dot" aria-hidden="true" />
          <span className="tool-call-name">{toolCall.name || '未知工具'}</span>
          <span className="tool-call-status">
            {statusText[toolCall.status] || toolCall.status || '调用中'}
          </span>
          {hasDetails && <span className="tool-call-expand" aria-hidden="true" />}
        </summary>
        {hasDetails && (
          <div className="tool-call-details">
            {toolCall.input && (
              <div>
                <span>输入</span>
                <pre>{formatToolValue(toolCall.input)}</pre>
              </div>
            )}
            {toolCall.result && (
              <div>
                <span>结果</span>
                <pre>{formatToolValue(toolCall.result)}</pre>
              </div>
            )}
            {toolCall.error_message && (
              <div className="tool-call-error">{toolCall.error_message}</div>
            )}
          </div>
        )}
      </details>
    );
  };

  const renderMessage = (message: ChatMessage) => {
    const isUser = message.role === 'user';
    const isSystem = message.role === 'system';
    const toolCalls = message.metadata?.agent?.tool_calls
      || message.metadata?.graphflow?.tool_calls
      || [];
    const loadedSkills = message.metadata?.agent?.loaded_skills
      || message.metadata?.graphflow?.loaded_skills
      || [];
    const selectedSkills = message.metadata?.composer?.skill_names
      ?? message.metadata?.composer?.skills
      ?? [];
    const isStreamingMessage = message.id === streamingMessageId;
    const customAssistantContent = !isUser && !isSystem && message.content
      ? renderAssistantContent?.({
        message,
        content: message.content,
        isStreaming: isStreamingMessage,
      })
      : undefined;

    return (
      <div
        key={message.id}
        className={`message-row message-row--${isUser ? 'user' : isSystem ? 'system' : 'assistant'} animate-fade-in mb-4 flex gap-3 ${
          isUser ? 'flex-row-reverse' : 'flex-row'
        }`}
      >
        <Avatar
          icon={isUser ? <UserOutlined /> : <RobotOutlined />}
          size={36}
          className="message-avatar flex-shrink-0"
          aria-hidden="true"
          style={{
            backgroundColor: isUser
              ? 'var(--color-primary)'
              : 'var(--color-bg-elevated)',
            color: isUser ? 'var(--color-on-primary)' : 'var(--color-primary)',
          }}
        />

        <div className="message-bubble-column max-w-[75%]">
          <div
            className={`rounded-2xl px-4 py-3 ${
              isUser
                ? 'border border-primary/30 text-text'
                : 'border border-border bg-card text-text'
            }`}
            style={isUser ? {
              background: 'color-mix(in srgb, var(--color-primary) 12%, var(--color-bg-card))',
            } : undefined}
          >
            <div
              className={`mb-1 flex items-center gap-2 text-xs ${
                isUser ? 'justify-end text-text-sec' : 'text-text-dim'
              }`}
            >
              <span className="font-medium">
                {isUser ? '你' : isSystem ? '系统' : '助手'}
              </span>
              <span>
                {new Date(message.created_at).toLocaleString('zh-CN', {
                  hour: '2-digit',
                  minute: '2-digit',
                })}
              </span>
            </div>

            <div className={`text-sm leading-relaxed ${isUser ? '' : 'message-markdown'}`}>
              {isUser && selectedSkills.length > 0 && (
                <div className="message-selected-skills" aria-label="本轮使用的技能">
                  {selectedSkills.map((skill) => (
                    <span className="message-skill-chip" key={skill}>
                      <ThunderboltOutlined />
                      {skill}
                    </span>
                  ))}
                </div>
              )}
              {remote && message.attachments?.map(attachment => (
                <p key={attachment.id}>{attachment.original_name} · 远程访问暂不支持附件预览</p>
              ))}
              {!remote && message.attachments && message.attachments.length > 0 && (
                <div className="message-image-grid" aria-label="消息图片">
                  <Image.PreviewGroup>
                    {message.attachments.map((attachment) => (
                      <Image
                        key={attachment.id}
                        src={attachment.url}
                        alt={attachment.original_name}
                        className="message-image"
                        fallback="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' height='120'%3E%3Crect width='100%25' height='100%25' fill='%23eeeeee'/%3E%3Ctext x='50%25' y='50%25' text-anchor='middle' dominant-baseline='middle' fill='%23888888'%3E图片加载失败%3C/text%3E%3C/svg%3E"
                      />
                    ))}
                  </Image.PreviewGroup>
                </div>
              )}
              {!isUser && toolCalls.length > 0 && (
                <div className="tool-call-list">
                  {toolCalls.map(renderToolCall)}
                </div>
              )}
              {!isUser && loadedSkills.length > 0 && (
                <div className="message-loaded-skills">
                  <ThunderboltOutlined /> 已加载技能：{loadedSkills.join('、')}
                </div>
              )}
              {customAssistantContent !== undefined
                ? customAssistantContent
                : message.content && (
                  isUser || isSystem || isStreamingMessage ? (
                    <span className={isStreamingMessage ? 'message-streaming-content' : undefined}>
                      {message.content}
                    </span>
                  ) : (
                    <ReactMarkdown
                      components={remote ? {
                        img: ({ alt }) => <span>{alt || '附件'} · 远程访问暂不支持预览</span>,
                        a: ({ children }) => <span>{children}（远程访问暂不支持打开文件或链接）</span>,
                      } : undefined}
                      remarkPlugins={[remarkMath]}
                      rehypePlugins={[rehypeKatex]}
                    >
                      {normalizeMarkdownMath(message.content)}
                    </ReactMarkdown>
                  )
                )}
            </div>
          </div>

          {message.content.trim() && (
            <div className={`message-actions ${isUser ? 'message-actions--user' : ''}`}>
              <Tooltip title="复制正文">
                <Button
                  type="text"
                  size="small"
                  className="message-copy-button"
                  icon={<CopyOutlined />}
                  aria-label="复制消息正文"
                  onClick={() => void copyMessageContent(message.content)}
                />
              </Tooltip>
            </div>
          )}
        </div>
      </div>
    );
  };

  return (
    <div className="flex flex-col px-4 py-6">
      {messages.length === 0 && !isLoading && (
        <div className="flex flex-1 items-center justify-center">
          <Text className="text-text-dim">开始新的对话吧...</Text>
        </div>
      )}
      {messages.map(renderMessage)}

      {(isLoading || isStreaming) && (
        <div className="animate-fade-in mb-4 flex gap-3">
          <Avatar
            icon={<RobotOutlined />}
            size={36}
            className="flex-shrink-0"
            style={{
              backgroundColor: 'var(--color-bg-elevated)',
              color: 'var(--color-primary)',
            }}
          />
          <div className="flex items-center gap-1 rounded-2xl border border-border bg-card px-4 py-3">
            <span className="animate-typing-dot inline-block h-2 w-2 rounded-full bg-primary" style={{ animationDelay: '0s' }} />
            <span className="animate-typing-dot inline-block h-2 w-2 rounded-full bg-primary" style={{ animationDelay: '0.2s' }} />
            <span className="animate-typing-dot inline-block h-2 w-2 rounded-full bg-primary" style={{ animationDelay: '0.4s' }} />
          </div>
        </div>
      )}
    </div>
  );
};

export default MessageList;
