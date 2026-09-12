import { create } from 'zustand';
import { persist } from 'zustand/middleware';

import type { AgentQuestion, AgentToolCall, RunEventEnvelope } from '@/entities/run';
import { api } from '@/services/api';
import type { RunResource } from '@/services/applicationRuntime';
import { streamRunEvents, type RunStreamHandle } from '@/services/runStream';

interface Message {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  created_at: string;
  metadata?: Record<string, any>;
}

export interface Conversation {
  id: string;
  title: string;
  agent?: any;
  project?: number | null;
  process_id?: string;
  created_at: string;
  updated_at: string;
  last_message?: { role: string; content: string; created_at: string };
  message_count?: number;
}

export interface ConversationDetail extends Conversation {
  messages: Message[];
}

export interface ChatRunOptions {
  permissionMode?: 'default' | 'allow_all';
  skills?: string[];
  agentId?: number | null;
}

const normalizeConversations = (raw: any): Conversation[] => {
  if (!raw) return [];
  const list = Array.isArray(raw) ? raw : Array.isArray(raw.results) ? raw.results : [];
  return list.filter((item: any) => item?.id != null) as Conversation[];
};

const asQuestion = (payload: Record<string, unknown>): AgentQuestion => {
  const source = payload.question && typeof payload.question === 'object'
    ? payload.question as Record<string, unknown>
    : payload;
  const options = Array.isArray(source.options) ? source.options : [];
  return {
    header: String(source.header ?? 'Agent 提问'),
    question: String(source.question ?? source.prompt ?? '请提供继续执行所需的信息'),
    kind: String(payload.kind ?? source.kind) === 'permission' ? 'permission' : 'question',
    options: options.map((option: any) => ({
      label: String(option?.label ?? option?.value ?? ''),
      value: String(option?.value ?? option?.label ?? ''),
      description: option?.description ? String(option.description) : undefined,
    })),
  };
};

const toolValue = (value: unknown): string | undefined => {
  if (value === undefined || value === null || value === '') return undefined;
  return typeof value === 'string' ? value : JSON.stringify(value);
};

const asToolCall = (event: RunEventEnvelope): AgentToolCall => ({
  id: String(event.payload.tool_call_id ?? event.payload.call_id ?? event.sequence),
  name: String(event.payload.name ?? event.payload.tool ?? 'tool'),
  input: toolValue(event.payload.input),
  result: toolValue(event.payload.result ?? event.payload.output),
  status: event.type === 'tool.started'
    ? 'running'
    : event.type === 'tool.failed' ? 'failed' : 'completed',
  error_message: event.payload.error_message
    ? String(event.payload.error_message)
    : undefined,
});

let latestConversationDetailRequest = 0;

interface ConversationState {
  conversations: Conversation[];
  currentConversation: ConversationDetail | null;
  activeRun: RunResource | null;
  isLoading: boolean;
  error: string | null;
  streamingMessageId: string | null;
  pendingQuestion: AgentQuestion | null;
  agentActivity: string | null;
  fetchConversations: () => Promise<void>;
  fetchProjectConversations: (projectId: number | string) => Promise<Conversation[]>;
  fetchConversationDetail: (id: string) => Promise<void>;
  createConversation: (
    title?: string,
    agentId?: number,
    projectId?: number,
    processId?: string,
    context?: {
      applicationId?: number;
      agentId?: number;
      skillIds?: string[];
      workingDirectory?: string;
    },
  ) => Promise<Conversation>;
  sendMessage: (conversationId: string, content: string) => Promise<RunResource>;
  sendMessageStream: (
    conversationId: string,
    content: string,
    options?: ChatRunOptions,
  ) => AbortController;
  appendStreamContent: (content: string) => void;
  replaceStreamContent: (content: string) => void;
  recordStreamToolCall: (toolCall: AgentToolCall) => void;
  answerQuestion: (
    conversationId: string,
    answer: { text?: string; selections?: string[] },
  ) => Promise<void>;
  cancelTurn: (conversationId: string) => Promise<void>;
  clearConversation: (conversationId: string) => Promise<void>;
  deleteConversation: (conversationId: string) => Promise<void>;
  setCurrentConversation: (conversation: ConversationDetail | null) => void;
  clearError: () => void;
}

export const useConversationStore = create<ConversationState>()(
  persist(
    (set, get) => {
      const finishRun = (conversationId: string) => {
        set({ streamingMessageId: null, pendingQuestion: null, agentActivity: null });
        void get().fetchConversationDetail(conversationId).catch(() => undefined);
        void get().fetchConversations().catch(() => undefined);
      };

      const consumeEvent = (conversationId: string, event: RunEventEnvelope) => {
        switch (event.type) {
          case 'run.queued':
            set({ agentActivity: 'Run 已排队…' });
            break;
          case 'run.started':
            set({ agentActivity: 'Agent 正在运行…' });
            break;
          case 'output.delta':
            get().appendStreamContent(String(event.payload.text ?? ''));
            set({ agentActivity: '正在生成…' });
            break;
          case 'output.snapshot': {
            const output = event.payload.text ?? event.payload.output ?? event.payload.result;
            if (output !== undefined) get().replaceStreamContent(String(output));
            break;
          }
          case 'tool.started':
          case 'tool.completed':
          case 'tool.failed': {
            const toolCall = asToolCall(event);
            get().recordStreamToolCall(toolCall);
            set({
              agentActivity: event.type === 'tool.started'
                ? `正在调用工具：${toolCall.name}`
                : `工具已结束：${toolCall.name}`,
            });
            break;
          }
          case 'input.required':
            set({ pendingQuestion: asQuestion(event.payload), agentActivity: '等待你的回答' });
            break;
          case 'input.accepted':
            set({ pendingQuestion: null, agentActivity: 'Run 已继续执行…' });
            break;
          case 'run.succeeded':
            finishRun(conversationId);
            break;
          case 'run.failed':
            set({
              error: String(event.payload.message ?? event.payload.error_message ?? 'Agent 执行失败'),
              streamingMessageId: null,
              pendingQuestion: null,
              agentActivity: null,
            });
            break;
          case 'run.cancelled':
            finishRun(conversationId);
            break;
        }
      };

      return {
        conversations: [],
        currentConversation: null,
        activeRun: null,
        isLoading: false,
        error: null,
        streamingMessageId: null,
        pendingQuestion: null,
        agentActivity: null,

        fetchConversations: async () => {
          set({ isLoading: true, error: null });
          try {
            const response = await api.get<Conversation[] | { results?: Conversation[] }>('/conversations/');
            set({ conversations: normalizeConversations(response), isLoading: false });
          } catch (error: any) {
            set({ error: error.response?.data?.detail || '获取对话列表失败', isLoading: false });
            throw error;
          }
        },

        fetchConversationDetail: async (id) => {
          const requestId = ++latestConversationDetailRequest;
          set({ isLoading: true, error: null });
          try {
            const response = await api.get<ConversationDetail>(`/conversations/${id}/`);
            if (requestId === latestConversationDetailRequest) {
              set({
                currentConversation: { ...response, id: String(response.id) },
                isLoading: false,
              });
            }
          } catch (error: any) {
            if (requestId === latestConversationDetailRequest) {
              set({ error: error.response?.data?.detail || '获取对话详情失败', isLoading: false });
            }
            throw error;
          }
        },

        fetchProjectConversations: async (projectId) => {
          try {
            const response = await api.get<Conversation[] | { results?: Conversation[] }>(
              '/conversations/',
              { project_id: projectId },
            );
            return normalizeConversations(response);
          } catch {
            return [];
          }
        },

        createConversation: async (title, agentId, projectId, processId, context = {}) => {
          set({ isLoading: true, error: null });
          try {
            const payload: Record<string, unknown> = { title };
            const effectiveAgentId = agentId ?? context.agentId;
            if (effectiveAgentId !== undefined) payload.agent_id = effectiveAgentId;
            if (projectId !== undefined) payload.project_id = projectId;
            if (processId !== undefined) payload.process_id = processId;
            if (context.applicationId) payload.application_id = context.applicationId;
            if (context.skillIds?.length) payload.skill_ids = context.skillIds;
            if (context.workingDirectory) payload.working_directory = context.workingDirectory;
            const response = await api.post<Conversation>('/conversations/', payload);
            if (!projectId) set({ conversations: [response, ...get().conversations] });
            set({ isLoading: false });
            return response;
          } catch (error: any) {
            set({ error: error.response?.data?.detail || '创建对话失败', isLoading: false });
            throw error;
          }
        },

        sendMessage: async (conversationId, content) => api.post<RunResource>(
          `/conversations/${conversationId}/send_message/`,
          { content },
          { headers: { 'Idempotency-Key': crypto.randomUUID() } },
        ),

        sendMessageStream: (conversationId, content, options = {}) => {
          const controller = new AbortController();
          let stream: RunStreamHandle | null = null;
          const current = get().currentConversation;
          const stamp = Date.now();
          const assistantMessageId = `run-pending-${stamp}`;
          const userMessage: Message = {
            id: `user-pending-${stamp}`,
            role: 'user',
            content,
            created_at: new Date().toISOString(),
            metadata: {
              composer: {
                skills: options.skills ?? [],
                agent_id: options.agentId ?? null,
                permission_mode: options.permissionMode ?? 'default',
              },
            },
          };
          const assistantMessage: Message = {
            id: assistantMessageId,
            role: 'assistant',
            content: '',
            created_at: new Date().toISOString(),
          };
          set({
            error: null,
            activeRun: null,
            streamingMessageId: assistantMessageId,
            pendingQuestion: null,
            agentActivity: '正在创建 Run…',
            currentConversation: current
              ? { ...current, messages: [...current.messages, userMessage, assistantMessage] }
              : null,
          });

          void get().sendMessage(conversationId, content).then((run) => {
            if (controller.signal.aborted) return;
            set({ activeRun: run, isLoading: false });
            stream = streamRunEvents({
              organizationId: run.organization_id,
              runId: run.id,
              onEvent: (event) => consumeEvent(conversationId, event),
              onSnapshot: () => {
                void get().fetchConversationDetail(conversationId);
              },
              onError: (error) => {
                if (!controller.signal.aborted && get().streamingMessageId) {
                  set({ error: `Run 事件流错误: ${error.message}` });
                }
              },
            });
          }).catch((error: any) => {
            if (!controller.signal.aborted) {
              set({
                error: error.response?.data?.detail || '创建 Run 失败',
                streamingMessageId: null,
                agentActivity: null,
              });
            }
          });
          controller.signal.addEventListener('abort', () => stream?.abort(), { once: true });
          return controller;
        },

        appendStreamContent: (content) => {
          const { currentConversation, streamingMessageId } = get();
          if (!currentConversation || !streamingMessageId) return;
          set({
            currentConversation: {
              ...currentConversation,
              messages: currentConversation.messages.map((message) =>
                message.id === streamingMessageId
                  ? { ...message, content: message.content + content }
                  : message),
            },
          });
        },

        replaceStreamContent: (content) => {
          const { currentConversation, streamingMessageId } = get();
          if (!currentConversation || !streamingMessageId) return;
          set({
            currentConversation: {
              ...currentConversation,
              messages: currentConversation.messages.map((message) =>
                message.id === streamingMessageId ? { ...message, content } : message),
            },
          });
        },

        recordStreamToolCall: (toolCall) => {
          const { currentConversation, streamingMessageId } = get();
          if (!currentConversation || !streamingMessageId) return;
          set({
            currentConversation: {
              ...currentConversation,
              messages: currentConversation.messages.map((message) => {
                if (message.id !== streamingMessageId) return message;
                const existing: AgentToolCall[] = message.metadata?.agent?.tool_calls ?? [];
                const index = existing.findIndex((item) => item.id === toolCall.id);
                const toolCalls = [...existing];
                if (index >= 0) toolCalls[index] = { ...toolCalls[index], ...toolCall };
                else toolCalls.push(toolCall);
                return {
                  ...message,
                  metadata: {
                    ...message.metadata,
                    agent: { ...message.metadata?.agent, tool_calls: toolCalls },
                  },
                };
              }),
            },
          });
        },

        answerQuestion: async (_conversationId, answer) => {
          const { activeRun, pendingQuestion } = get();
          if (!activeRun) throw new Error('没有可恢复的 Run');
          const selected = answer.selections?.[0];
          const type = pendingQuestion?.kind === 'permission'
            ? selected === 'deny' ? 'deny_permission' : 'grant_permission'
            : 'answer';
          set({ pendingQuestion: null, agentActivity: '正在提交回答…', error: null });
          try {
            await api.post(
              `/organizations/${activeRun.organization_id}/runs/${activeRun.id}/commands`,
              {
                type,
                idempotency_key: crypto.randomUUID(),
                input_request_id: activeRun.pending_input_request_id,
                payload: answer,
              },
            );
          } catch (error: any) {
            set({ pendingQuestion, error: error.response?.data?.detail || '提交回答失败' });
            throw error;
          }
        },

        cancelTurn: async (_conversationId) => {
          const run = get().activeRun;
          if (!run) return;
          set({ agentActivity: '正在取消…', error: null });
          await api.post(
            `/organizations/${run.organization_id}/runs/${run.id}/commands`,
            { type: 'cancel', idempotency_key: crypto.randomUUID(), payload: {} },
          );
        },

        clearConversation: async (conversationId) => {
          set({ isLoading: true, error: null });
          try {
            await api.delete(`/conversations/${conversationId}/clear/`);
            const currentConversation = get().currentConversation;
            set({
              currentConversation: currentConversation?.id === conversationId
                ? { ...currentConversation, messages: [] }
                : currentConversation,
              isLoading: false,
            });
          } catch (error: any) {
            set({ error: error.response?.data?.detail || '清空对话失败', isLoading: false });
            throw error;
          }
        },

        deleteConversation: async (conversationId) => {
          set({ isLoading: true, error: null });
          try {
            await api.delete(`/conversations/${conversationId}/delete_conversation/`);
            const { conversations, currentConversation } = get();
            set({
              conversations: conversations.filter((item) => item.id !== conversationId),
              currentConversation: currentConversation?.id === conversationId
                ? null : currentConversation,
              isLoading: false,
            });
          } catch (error: any) {
            set({ error: error.response?.data?.detail || '删除对话失败', isLoading: false });
            throw error;
          }
        },

        setCurrentConversation: (conversation) => set({ currentConversation: conversation }),
        clearError: () => set({ error: null }),
      };
    },
    {
      name: 'conversation-storage',
      merge: (persisted, current) => {
        const value = (persisted as Partial<ConversationState>) ?? {};
        return {
          ...current,
          ...value,
          activeRun: null,
          streamingMessageId: null,
          pendingQuestion: null,
          agentActivity: null,
          conversations: normalizeConversations(value.conversations),
        };
      },
      partialize: (state) => ({
        conversations: state.conversations,
        currentConversation: state.currentConversation,
      }),
    },
  ),
);
