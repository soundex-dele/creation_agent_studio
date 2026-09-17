import React from 'react';
import { Avatar, Button, message as toast, Tooltip, Typography } from 'antd';
import {
  CopyOutlined,
  RobotOutlined,
  ThunderboltOutlined,
  UserOutlined,
} from '@ant-design/icons';
import ReactMarkdown from 'react-markdown';
import type { AgentToolCall } from '@/entities/run';
import './MessageList.css';

const { Text } = Typography;

interface Message {
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
}

interface MessageListProps {
  messages: Message[];
  isLoading?: boolean;
  isStreaming?: boolean;
  streamingMessageId?: string | null;
}

const MessageList: React.FC<MessageListProps> = ({
  messages,
  isLoading = false,
  isStreaming = false,
  streamingMessageId = null,
}) => {
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

  const renderMessage = (message: Message) => {
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

    return (
      <div
        key={message.id}
        className={`animate-fade-in mb-4 flex gap-3 ${
          isUser ? 'flex-row-reverse' : 'flex-row'
        }`}
      >
        <Avatar
          icon={isUser ? <UserOutlined /> : <RobotOutlined />}
          size={36}
          className="flex-shrink-0"
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
              {isUser || isSystem || isStreamingMessage ? (
                <span className={isStreamingMessage ? 'message-streaming-content' : undefined}>
                  {message.content}
                </span>
              ) : (
                <ReactMarkdown>{message.content}</ReactMarkdown>
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
