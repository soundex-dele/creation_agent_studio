import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { createStreamUpdates } from '@/lib/streamUpdates';

import {
  createRunEventState,
  ingestRunEvent,
  restoreRunEventSnapshot,
  type AgentQuestion,
  type AgentToolCall,
  type RunEventEnvelope,
  type RunEventState,
} from '@/entities/run';
import { createIdempotencyKey } from '@/lib/idempotencyKey';
import { api as defaultApi } from '@/services/api';
import { createConnectionApi, type RemoteConnection } from '@/services/chatConnection';
import type { RunResource } from '@/services/applicationRuntime';
import { streamRunEvents, type RunStreamHandle } from '@/services/runStream';
import { tenantApiRoot } from '@/services/tenantContext';

function conversationRequestError(data: unknown, fallback: string): string {
  if (!data || typeof data !== 'object') return fallback;
  const fields = data as Record<string, unknown>;
  for (const key of ['detail', 'non_field_errors', 'skill_names', 'skill_ids',
    'agent_id', 'application_id', 'images', 'permission_mode', 'collaboration_mode',
    'content', 'working_directory', 'project_id', 'title']) {
    const value = fields[key];
    const text = Array.isArray(value)
      ? value.filter(item => typeof item === 'string').join(' ')
      : typeof value === 'string' ? value : '';
    if (text.trim()) return text;
  }
  return fallback;
}

export interface MessageAttachment {
  id: string;
  url: string;
  original_name: string;
  content_type: string;
  byte_size: number;
  width?: number | null;
  height?: number | null;
  created_at?: string;
}

interface Message {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  created_at: string;
  metadata?: Record<string, any>;
  attachments?: MessageAttachment[];
}

export interface Conversation {
  scope?: 'default' | 'cowork';
  id: string;
  title: string;
  agent?: any;
  project?: number | null;
  working_directory?: string;
  workspace_locked?: boolean;
  process_id?: string;
  created_at: string;
  updated_at: string;
  last_message?: { role: string; content: string; created_at: string };
  message_count?: number;
}

export interface ConversationDetail extends Conversation {
  messages: Message[];
  organization_id?: string;
  active_run?: RunResource | null;
}

class InvalidConversationDetailError extends Error {
  constructor() {
    super('对话接口返回的数据格式异常，请稍后重试。');
    this.name = 'InvalidConversationDetailError';
  }
}

function isTransientDetailError(error: unknown): boolean {
  const failure = error as { code?: string; response?: { status?: number } };
  if (failure.response) return [502, 503, 504].includes(failure.response.status ?? 0);
  return ['ERR_NETWORK', 'ECONNABORTED', 'ETIMEDOUT'].includes(failure.code ?? '');
}

function conversationDetailError(error: unknown): string {
  if (error instanceof InvalidConversationDetailError) return error.message;
  const failure = error as { code?: string; response?: { status?: number; data?: unknown } };
  const fallback = ['ECONNABORTED', 'ETIMEDOUT'].includes(failure.code ?? '')
    ? '加载对话超时，返回页面或网络恢复后将自动重试。'
    : failure.code === 'ERR_NETWORK'
      ? '网络连接失败，返回页面或网络恢复后将自动重试。'
      : '获取对话详情失败';
  return conversationRequestError(failure.response?.data, fallback);
}

function parseConversationDetail(response: unknown, expectedId: string): ConversationDetail {
  if (!response || typeof response !== 'object' || Array.isArray(response)) {
    throw new InvalidConversationDetailError();
  }
  const detail = response as Record<string, unknown>;
  const validId = (value: unknown) => (typeof value === 'string' && value.length > 0)
    || (typeof value === 'number' && Number.isFinite(value));
  if (!validId(detail.id) || String(detail.id) !== expectedId
    || !Array.isArray(detail.messages)
    || !detail.messages.every((item: unknown) => {
      if (!item || typeof item !== 'object' || Array.isArray(item)) return false;
      const message = item as Record<string, unknown>;
      return validId(message.id) && ['user', 'assistant', 'system'].includes(String(message.role))
        && typeof message.content === 'string';
    })) {
    throw new InvalidConversationDetailError();
  }
  return { ...detail, id: String(detail.id) } as unknown as ConversationDetail;
}

export interface ChatRunOptions {
  permissionMode?: 'default' | 'allow_all';
  collaborationMode?: 'default' | 'plan';
  skillNames?: string[];
  agentId?: number | null;
  images?: File[];
}

const normalizeConversation = (item: any): Conversation => ({
  ...item,
  id: String(item.id),
});

const normalizeConversations = (raw: any): Conversation[] => {
  if (!raw) return [];
  const list = Array.isArray(raw) ? raw : Array.isArray(raw.results) ? raw.results : [];
  return list
    .filter((item: any) => item?.id != null)
    .map(normalizeConversation);
};

const asQuestion = (payload: Record<string, unknown>): AgentQuestion => {
  const source = payload.question && typeof payload.question === 'object'
    ? payload.question as Record<string, unknown>
    : payload;
  const normalizeItem = (item: Record<string, unknown>, index: number) => {
    const options = Array.isArray(item.options) ? item.options : [];
    return {
      id: String(item.id ?? `question-${index + 1}`),
      header: String(item.header ?? 'Agent 提问'),
      question: String(item.question ?? item.prompt ?? '请提供继续执行所需的信息'),
      options: options.map((option: any) => ({
        label: String(option?.label ?? option?.value ?? ''),
        value: String(option?.value ?? option?.label ?? ''),
        description: option?.description ? String(option.description) : undefined,
      })),
      isOther: item.is_other === undefined && item.isOther === undefined
        ? undefined
        : Boolean(item.is_other ?? item.isOther),
      isSecret: Boolean(item.is_secret ?? item.isSecret),
    };
  };
  const rawQuestions = Array.isArray(payload.questions)
    ? payload.questions
    : Array.isArray(source.questions) ? source.questions : [];
  const questions = rawQuestions
    .filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object'))
    .map(normalizeItem);
  const primary = questions[0] ?? normalizeItem(source, 0);
  return {
    ...primary,
    id: payload.elicitation ? String(payload.input_request_id ?? primary.id) : primary.id,
    details: payload.details as Record<string, unknown> | undefined,
    formSchema: payload.form_schema as Record<string, unknown> | undefined,
    elicitation: Boolean(payload.elicitation),
    url: typeof payload.url === 'string' ? payload.url : undefined,
    kind: String(payload.input_kind ?? payload.kind ?? source.kind) === 'permission'
      ? 'permission'
      : 'question',
    questions: questions.length > 0 ? questions : undefined,
  };
};

const questionMessageContent = (question: AgentQuestion): string => {
  const questions = question.questions?.length ? question.questions : [question];
  return questions.map((item, index) => {
    const lines: string[] = [];
    if (item.header && (questions.length > 1 || item.header !== 'Agent 提问')) {
      lines.push(`**${item.header}**`);
    }
    lines.push(item.question);
    if (item.options.length) {
      lines.push(`可选：${item.options.map((option) => option.label).join(' / ')}`);
    }
    return `${questions.length > 1 ? `${index + 1}. ` : ''}${lines.join('\n')}`;
  }).join('\n\n');
};

const answerMessageContent = (
  question: AgentQuestion,
  answer: {
    text?: string;
    selections?: string[];
    answers?: Record<string, { answers: string[] }>;
    action?: 'accept' | 'decline' | 'cancel';
  },
): string => {
  if (question.elicitation) return { accept: '已提交工具请求', decline: '已拒绝工具请求', cancel: '已取消工具请求' }[answer.action ?? 'accept'];
  if (question.kind === 'permission') {
    return ['deny', 'decline', 'cancel'].includes(answer.selections?.[0] ?? '') ? '拒绝' : '允许';
  }
  const questions = question.questions?.length ? question.questions : [question];
  if (answer.answers) {
    return questions.map((item) => {
      const values = answer.answers?.[item.id]?.answers ?? [];
      const value = item.isSecret ? '••••••' : values.join(' / ');
      return questions.length > 1 ? `${item.question}：${value}` : value;
    }).join('\n');
  }
  return answer.text || answer.selections?.join(' / ') || '';
};

const toolValue = (value: unknown): string | undefined => {
  if (value === undefined || value === null || value === '') return undefined;
  return typeof value === 'string' ? value : JSON.stringify(value);
};

const revokeOptimisticImageUrls = (messages: Message[] | undefined) => {
  messages?.forEach((item) => item.attachments?.forEach((attachment) => {
    if (attachment.url.startsWith('blob:')) URL.revokeObjectURL(attachment.url);
  }));
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

interface ConversationState {
  disconnect: () => void;
  reset: () => void;
  refreshIfIdle: (id: string) => Promise<void>;
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
  sendMessage: (
    conversationId: string,
    content: string,
    options?: ChatRunOptions,
  ) => Promise<RunResource>;
  sendMessageStream: (
    conversationId: string,
    content: string,
    options?: ChatRunOptions,
  ) => AbortController & { submitted?: Promise<void> };
  appendStreamContent: (content: string) => void;
  replaceStreamContent: (content: string) => void;
  recordStreamToolCall: (toolCall: AgentToolCall) => void;
  answerQuestion: (
    conversationId: string,
    answer: {
      text?: string;
      selections?: string[];
      answers?: Record<string, { answers: string[] }>;
      action?: 'accept' | 'decline' | 'cancel';
      content?: Record<string, unknown>;
    },
  ) => Promise<void>;
  cancelTurn: (conversationId: string) => Promise<void>;
  steerTurn: (conversationId: string, text: string) => Promise<void>;
  clearConversation: (conversationId: string) => Promise<void>;
  deleteConversation: (conversationId: string) => Promise<void>;
  setCurrentConversation: (conversation: ConversationDetail | null) => void;
  clearError: () => void;
}

export const createConversationStore = (connection?: RemoteConnection, apiOverride?: typeof defaultApi, storageName?: string) => {
  const api = apiOverride ?? (connection ? createConnectionApi(connection) : defaultApi);
  const runTenantRoot = (id: string) => connection ? `/organizations/${id}` : tenantApiRoot(id);
  let latestConversationDetailRequest = 0;
  let sessionVersion = 0;
  let idleRefreshRequest: object | null = null;
  let restoredConversationRunStream: RunStreamHandle | null = null;
  let activeController: AbortController | null = null;
  let detailController: AbortController | null = null;
  let failedDetailId: string | null = null;

  const loadConversationDetail = async (id: string, signal: AbortSignal) => {
    for (let attempt = 0; ; attempt += 1) {
      signal.throwIfAborted();
      try {
        return await api.get<unknown>(`/conversations/${id}/`, undefined, {
          timeout: 30000, signal,
        });
      } catch (error) {
        if (signal.aborted || attempt >= 1 || !isTransientDetailError(error)) throw error;
        await new Promise<void>((resolve) => {
          const finish = () => {
            clearTimeout(timer);
            signal.removeEventListener('abort', finish);
            resolve();
          };
          const timer = setTimeout(finish, 500);
          signal.addEventListener('abort', finish, { once: true });
        });
      }
    }
  };
  return create<ConversationState>()(
  persist(
    (set, get) => {
      const streamUpdates = createStreamUpdates();
      const finishRun = (conversationId: string) => {
        set({ streamingMessageId: null, pendingQuestion: null, agentActivity: null });
        void get().fetchConversationDetail(conversationId).catch(() => undefined);
        void get().fetchConversations().catch(() => undefined);
      };

      const applyRunProjection = (
        conversationId: string,
        projection: RunEventState,
        event?: RunEventEnvelope,
      ) => {
        if (get().currentConversation?.id !== conversationId
          || get().activeRun?.id !== projection.runId) return;
        const pendingQuestion = projection.pendingInput
          ? asQuestion(projection.pendingInput)
          : null;
        set((state) => ({
          error: null,
          pendingQuestion,
          activeRun: state.activeRun ? {
            ...state.activeRun,
            status: projection.status ?? state.activeRun.status,
            pending_input_request_id: projection.pendingInput
              ? String(projection.pendingInput.input_request_id ?? '')
              : null,
            pending_input_kind: projection.pendingInput
              ? String(projection.pendingInput.input_kind ?? '')
              : '',
          } : null,
          currentConversation: state.currentConversation && state.streamingMessageId ? {
            ...state.currentConversation,
            messages: state.currentConversation.messages.map(message => {
              if (message.id !== state.streamingMessageId) return message;
              if (message.content === projection.output
                && message.metadata?.agent?.activity === projection.activity) return message;
              return {
                ...message,
                content: projection.output || '',
                metadata: { ...message.metadata, agent: {
                  ...message.metadata?.agent, activity: projection.activity,
                } },
              };
            }),
          } : state.currentConversation,
          ...(event?.type === 'output.delta' ? { agentActivity: '正在生成…' } : {}),
        }));
        if (event && ['input.accepted', 'input.resolved'].includes(event.type) && !get().streamingMessageId) {
          const id = `run-live-${projection.runId}-${event.sequence}`;
          set((state) => ({ streamingMessageId: id, currentConversation: state.currentConversation ? {
            ...state.currentConversation, messages: [...state.currentConversation.messages,
              { id, role: 'assistant', content: projection.output || '', created_at: new Date().toISOString(),
                metadata: { agent: { activity: projection.activity } } }],
          } : null }));
        }
        if (!event) {
          set({
            agentActivity: pendingQuestion
              ? '等待你的回答'
              : projection.status === 'running' ? 'Agent 正在运行…' : null,
          });
          if (projection.status && ['succeeded', 'failed', 'cancelled'].includes(projection.status)) {
            finishRun(conversationId);
          }
          return;
        }
        switch (event.type) {
          case 'run.queued':
            set({ agentActivity: 'Run 已排队…' });
            break;
          case 'run.started':
            set({ agentActivity: 'Agent 正在运行…' });
            break;
          case 'output.delta':
            break;
          case 'output.snapshot':
            break;
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
            if (pendingQuestion) {
              const questionContent = questionMessageContent(pendingQuestion);
              set((state) => ({
                currentConversation: state.currentConversation && state.streamingMessageId
                  ? {
                    ...state.currentConversation,
                    messages: state.currentConversation.messages.map((message) => {
                      if (message.id !== state.streamingMessageId) return message;
                      const existing = message.content.trim();
                      return {
                        ...message,
                        content: existing
                          ? `${existing}\n\n${questionContent}`
                          : questionContent,
                        metadata: {
                          ...message.metadata,
                          interaction: { type: 'input.required' },
                        },
                      };
                    }),
                  }
                  : state.currentConversation,
                streamingMessageId: null,
                agentActivity: '等待你的回答',
              }));
            } else {
              set({ agentActivity: '等待你的回答' });
            }
            break;
          case 'input.accepted':
          case 'input.resolved':
            set({ agentActivity: 'Run 已继续执行…' });
            break;
          case 'input.steered':
            set((state) => {
              if (!state.currentConversation) return {};
              const messages = [...state.currentConversation.messages];
              const index = messages.findIndex(message => message.id === state.streamingMessageId);
              messages.splice(index < 0 ? messages.length : index, 0, {
                id: `steer-${event.sequence}`, role: 'user', content: String(event.payload.text ?? ''), created_at: event.created_at,
              });
              return { currentConversation: { ...state.currentConversation, messages }, agentActivity: '已提交补充指令' };
            });
            break;
          case 'run.succeeded':
            finishRun(conversationId);
            break;
          case 'run.failed':
            set({
              error: String(event.payload.message ?? event.payload.error_message ?? 'Agent 执行失败'),
              activeRun: null,
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

      const publishRunProjection = (
        conversationId: string, projection: RunEventState, event?: RunEventEnvelope,
      ) => {
        // Reduce every event, but avoid notifying React and serializing storage
        // for every token/tool-output fragment. Lifecycle events stay immediate.
        if (event && (event.type === 'output.delta'
          || ((event.type === 'agent.item' || event.type === 'agent.tool')
            && (typeof event.payload.delta === 'string' || typeof event.payload.summary_delta === 'string')))) {
          streamUpdates.schedule(() => applyRunProjection(conversationId, projection, event));
        } else {
          streamUpdates.flush();
          applyRunProjection(conversationId, projection, event);
        }
      };

      const restoreConversationRun = (
        conversationId: string,
        run: RunResource | null | undefined,
      ) => {
        restoredConversationRunStream?.abort();
        restoredConversationRunStream = null;
        if (!run) {
          set({
            activeRun: null,
            streamingMessageId: null,
            pendingQuestion: null,
            agentActivity: null,
          });
          return;
        }

        const waitingForInput = run.status === 'waiting_input';
        const assistantMessageId = `run-restored-${run.id}-${Date.now()}`;
        set((state) => ({
          activeRun: run,
          pendingQuestion: null,
          streamingMessageId: waitingForInput ? null : assistantMessageId,
          agentActivity: waitingForInput ? '正在恢复待回答问题…' : '正在恢复 Run…',
          currentConversation: !waitingForInput && state.currentConversation
            ? {
              ...state.currentConversation,
              messages: [
                ...state.currentConversation.messages,
                {
                  id: assistantMessageId,
                  role: 'assistant',
                  content: '',
                  created_at: new Date().toISOString(),
                },
              ],
            }
            : state.currentConversation,
        }));

        let projection = createRunEventState(run.id);
        const requestVersion = latestConversationDetailRequest;
        restoredConversationRunStream = streamRunEvents({
          connection,
          organizationId: run.organization_id,
          runId: run.id,
          onEvent: (event) => {
            if (requestVersion !== latestConversationDetailRequest
              || get().currentConversation?.id !== conversationId) return;
            projection = ingestRunEvent(projection, event).state;
            publishRunProjection(conversationId, projection, event);
          },
          onSnapshot: (snapshot) => {
            if (requestVersion !== latestConversationDetailRequest
              || get().currentConversation?.id !== conversationId) return;
            projection = restoreRunEventSnapshot(snapshot);
            publishRunProjection(conversationId, projection);
          },
          onError: (error) => {
            if (requestVersion === latestConversationDetailRequest
              && get().currentConversation?.id === conversationId) {
              streamUpdates.flush();
              set({ error: `Run 恢复失败: ${error.message}` });
            }
          },
        });
      };

      return {
        disconnect: () => {
          streamUpdates.flush();
          latestConversationDetailRequest += 1;
          detailController?.abort();
          detailController = null;
          failedDetailId = null;
          idleRefreshRequest = null;
          restoredConversationRunStream?.abort();
          restoredConversationRunStream = null;
          activeController?.abort();
          activeController = null;
          set({
            activeRun: null, streamingMessageId: null, pendingQuestion: null,
            agentActivity: null, isLoading: false,
          });
        },
        reset: () => {
          sessionVersion += 1;
          get().disconnect();
          revokeOptimisticImageUrls(get().currentConversation?.messages);
          set({ conversations: [], currentConversation: null, error: null });
        },
        refreshIfIdle: async (id) => {
          const current = get();
          if (failedDetailId === id && !current.isLoading
            && !current.streamingMessageId && !current.activeRun) {
            await get().fetchConversationDetail(id);
            return;
          }
          if (current.currentConversation?.id !== id || idleRefreshRequest
            || current.isLoading || current.streamingMessageId || current.activeRun || current.error) return;
          const version = latestConversationDetailRequest;
          const request = {};
          idleRefreshRequest = request;
          try {
            const response = await api.get<unknown>(`/conversations/${id}/`);
            const latest = get();
            if (version !== latestConversationDetailRequest
              || latest.currentConversation !== current.currentConversation
              || latest.isLoading || latest.streamingMessageId || latest.activeRun) return;
            const detail = parseConversationDetail(response, id);
            set({ currentConversation: detail });
            if (detail.active_run) restoreConversationRun(id, detail.active_run);
          } finally {
            if (idleRefreshRequest === request) idleRefreshRequest = null;
          }
        },
        conversations: [],
        currentConversation: null,
        activeRun: null,
        isLoading: false,
        error: null,
        streamingMessageId: null,
        pendingQuestion: null,
        agentActivity: null,

        fetchConversations: async () => {
          const version = sessionVersion;
          set({ isLoading: true, error: null });
          try {
            const response = await api.get<Conversation[] | { results?: Conversation[] }>('/conversations/');
            if (version !== sessionVersion) return;
            set({ conversations: normalizeConversations(response), isLoading: false });
          } catch (error: any) {
            if (version === sessionVersion) {
              set({ error: error.response?.data?.detail || '获取对话列表失败', isLoading: false });
            }
            throw error;
          }
        },

        fetchConversationDetail: async (id) => {
          get().disconnect();
          const requestId = latestConversationDetailRequest;
          const controller = new AbortController();
          detailController = controller;
          if (get().currentConversation?.id !== id) {
            revokeOptimisticImageUrls(get().currentConversation?.messages);
            set({ currentConversation: null });
          }
          set({ isLoading: true, error: null });
          try {
            const response = await loadConversationDetail(id, controller.signal);
            if (requestId === latestConversationDetailRequest) {
              const detail = parseConversationDetail(response, id);
              revokeOptimisticImageUrls(get().currentConversation?.messages);
              set({
                currentConversation: detail,
                isLoading: false,
              });
              restoreConversationRun(detail.id, detail.active_run);
            }
          } catch (error: any) {
            if (requestId !== latestConversationDetailRequest || controller.signal.aborted) return;
            if (requestId === latestConversationDetailRequest) {
              failedDetailId = isTransientDetailError(error) ? id : null;
              set({
                error: conversationDetailError(error),
                isLoading: false,
              });
            }
            throw error;
          } finally {
            if (detailController === controller) detailController = null;
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
          const version = sessionVersion;
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
            const response = await api.post<Conversation>('/conversations/', payload, {
              headers: { 'Idempotency-Key': createIdempotencyKey('conversation') },
            });
            if (version !== sessionVersion) throw new DOMException('登录状态已更改', 'AbortError');
            const conversation = normalizeConversation(response);
            if (!projectId || connection) set({ conversations: [conversation, ...get().conversations] });
            set({ isLoading: false });
            return conversation;
          } catch (error: any) {
            if (version === sessionVersion) {
              set({ error: conversationRequestError(error.response?.data, '创建对话失败'), isLoading: false });
            }
            throw error;
          }
        },

        sendMessage: async (conversationId, content, options = {}) => {
          if (options.images?.length) {
            const payload = new FormData();
            payload.append('content', content);
            payload.append('permission_mode', options.permissionMode ?? 'default');
            payload.append('collaboration_mode', options.collaborationMode ?? 'default');
            options.images.forEach((image) => payload.append('images', image, image.name));
            options.skillNames?.forEach((skillName) => payload.append('skill_names', skillName));
            if (options.agentId === null) payload.append('agent_id', '');
            else if (options.agentId !== undefined) {
              payload.append('agent_id', String(options.agentId));
            }
            return api.post<RunResource>(
              `/conversations/${conversationId}/send_message/`,
              payload,
              {
                headers: {
                  'Content-Type': 'multipart/form-data',
                  'Idempotency-Key': createIdempotencyKey('chat'),
                },
                timeout: 120000,
              },
            );
          }
          const payload: Record<string, unknown> = {
            content,
            permission_mode: options.permissionMode ?? 'default',
            collaboration_mode: options.collaborationMode ?? 'default',
          };
          if (options.agentId !== undefined) {
            payload.agent_id = options.agentId;
          }
          if (options.skillNames?.length) payload.skill_names = options.skillNames;
          return api.post<RunResource>(
            `/conversations/${conversationId}/send_message/`,
            payload,
            { headers: { 'Idempotency-Key': createIdempotencyKey('chat') } },
          );
        },

        sendMessageStream: (conversationId, content, options = {}) => {
          restoredConversationRunStream?.abort();
          restoredConversationRunStream = null;
          const started = performance.now();
          const seenEventTypes = new Set<string>();
          const logTiming = (stage: string, details: Record<string, unknown> = {}) => {
            console.info('[chat_latency]', {
              stage, conversationId, elapsedMs: Math.round(performance.now() - started),
              ...details,
            });
          };
          logTiming('send');
          activeController?.abort();
          const controller = new AbortController() as AbortController & { submitted?: Promise<void> };
          activeController = controller;
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
                skill_names: options.skillNames ?? [],
                agent_id: options.agentId ?? null,
                permission_mode: options.permissionMode ?? 'default',
                collaboration_mode: options.collaborationMode ?? 'default',
              },
            },
            attachments: (options.images ?? []).map((image, index) => ({
              id: `pending-image-${stamp}-${index}`,
              url: URL.createObjectURL(image),
              original_name: image.name,
              content_type: image.type,
              byte_size: image.size,
            })),
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

          controller.submitted = get().sendMessage(conversationId, content, options).then((run) => {
            logTiming('run_response', { runId: run.id });
            if (controller.signal.aborted) return;
            set({ activeRun: run, isLoading: false });
            let projection = createRunEventState(run.id);
            stream = streamRunEvents({
              connection,
              organizationId: run.organization_id,
              runId: run.id,
              onEvent: (event) => {
                if (controller.signal.aborted) return;
                if (!seenEventTypes.has(event.type)) {
                  seenEventTypes.add(event.type);
                  logTiming('first_event', { runId: run.id, type: event.type, sequence: event.sequence });
                  if (
                    (event.type === 'output.delta' || event.type === 'output.snapshot')
                    && typeof globalThis.requestAnimationFrame === 'function'
                  ) {
                    requestAnimationFrame(() => requestAnimationFrame(() => {
                      logTiming('output_paint_opportunity', { runId: run.id });
                    }));
                  }
                }
                projection = ingestRunEvent(projection, event).state;
                publishRunProjection(conversationId, projection, event);
              },
              onSnapshot: (snapshot) => {
                if (controller.signal.aborted) return;
                projection = restoreRunEventSnapshot(snapshot);
                publishRunProjection(conversationId, projection);
              },
              onError: (error) => {
                logTiming('stream_error', { runId: run.id, errorType: error.name });
                if (!controller.signal.aborted && get().streamingMessageId) {
                  streamUpdates.flush();
                  set({ error: `Run 事件流错误: ${error.message}` });
                }
              },
            });
          }).catch((error: any) => {
            if (!controller.signal.aborted) {
              set({
                error: conversationRequestError(error.response?.data, '创建 Run 失败'),
                streamingMessageId: null,
                agentActivity: null,
                currentConversation: current,
                isLoading: false,
              });
            }
            throw error;
          });
          void controller.submitted.catch(() => undefined);
          controller.signal.addEventListener('abort', () => {
            if (activeController === controller) streamUpdates.flush();
            stream?.abort();
          }, { once: true });
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
          const requestVersion = latestConversationDetailRequest;
          const {
            activeRun, pendingQuestion, currentConversation, streamingMessageId,
          } = get();
          if (!activeRun) throw new Error('没有可恢复的 Run');
          if (!pendingQuestion) throw new Error('没有待回答的问题');
          const selected = answer.selections?.[0];
          const type = pendingQuestion.kind === 'permission'
            ? ['deny', 'decline', 'cancel'].includes(selected ?? '') ? 'deny_permission' : 'grant_permission'
            : 'answer';
          const stamp = Date.now();
          const nextAssistantId = `run-resume-${activeRun.id}-${stamp}`;
          const answerMessage: Message = {
            id: `answer-pending-${activeRun.id}-${stamp}`,
            role: 'user',
            content: answerMessageContent(pendingQuestion, answer),
            created_at: new Date().toISOString(),
            metadata: { interaction: { type: 'input.accepted' } },
          };
          const nextAssistant: Message = {
            id: nextAssistantId,
            role: 'assistant',
            content: '',
            created_at: new Date().toISOString(),
          };
          set({
            pendingQuestion: null,
            streamingMessageId: nextAssistantId,
            currentConversation: currentConversation ? {
              ...currentConversation,
              messages: [...currentConversation.messages, answerMessage, nextAssistant],
            } : null,
            agentActivity: '正在提交回答…',
            error: null,
          });
          try {
            await api.post(
              `${runTenantRoot(activeRun.organization_id)}/runs/${activeRun.id}/commands`,
              {
                type,
                idempotency_key: createIdempotencyKey('chat-command'),
                input_request_id: activeRun.pending_input_request_id,
                payload: answer,
              },
            );
          } catch (error: any) {
            if (requestVersion === latestConversationDetailRequest) {
              set({
                pendingQuestion,
                currentConversation,
                streamingMessageId,
                error: error.response?.data?.detail || '提交回答失败',
              });
            }
            throw error;
          }
        },

        steerTurn: async (conversationId, text) => {
          const { activeRun, currentConversation } = get();
          if (!activeRun || currentConversation?.id !== conversationId) throw new Error('没有运行中的会话');
          await api.post(`${runTenantRoot(activeRun.organization_id)}/runs/${activeRun.id}/commands`, {
            type: 'steer', idempotency_key: createIdempotencyKey('chat-steer'), payload: { text },
          });
        },

        cancelTurn: async (conversationId) => {
          if (get().currentConversation?.id !== conversationId) return;
          const run = get().activeRun;
          if (!run) return;
          set({ agentActivity: '正在取消…', error: null });
          await api.post(
            `${runTenantRoot(run.organization_id)}/runs/${run.id}/commands`,
            { type: 'cancel', idempotency_key: createIdempotencyKey('chat-command'), payload: {} },
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

        setCurrentConversation: (conversation) => {
          if (!conversation || conversation.id !== get().currentConversation?.id) {
            get().disconnect();
            revokeOptimisticImageUrls(get().currentConversation?.messages);
          }
          set({ currentConversation: conversation, error: null });
        },
        clearError: () => set({ error: null }),
      };
    },
    {
      name: storageName ?? (connection ? `remote-conversation-${connection.deviceId}` : 'conversation-storage'),
      ...(connection || apiOverride ? { storage: {
        getItem: () => null,
        setItem: () => undefined,
        removeItem: () => undefined,
      } } : {}),
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
      }),
    },
  ),
);
};

export const useConversationStore = createConversationStore();
