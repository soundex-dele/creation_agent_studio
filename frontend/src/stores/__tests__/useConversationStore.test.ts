import { beforeEach, describe, expect, it, vi } from 'vitest';

import { api } from '@/services/api';
import * as runStream from '@/services/runStream';
import type { RunEventEnvelope } from '@/entities/run';
import { useConversationStore } from '../useConversationStore';

describe('useConversationStore durable Run integration', () => {
  beforeEach(() => {
    useConversationStore.setState({
      conversations: [],
      currentConversation: null,
      activeRun: null,
      error: null,
      streamingMessageId: null,
      pendingQuestion: null,
      agentActivity: null,
    });
    vi.restoreAllMocks();
  });

  it('normalizes conversation ids so URL selections match history items', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({
      results: [{
        id: 15,
        title: 'Numeric id conversation',
        created_at: '',
        updated_at: '',
      }],
    });

    await useConversationStore.getState().fetchConversations();

    expect(useConversationStore.getState().conversations[0]?.id).toBe('15');
  });

  it('normalizes a newly created conversation id', async () => {
    vi.spyOn(api, 'post').mockResolvedValue({
      id: 16,
      title: 'New conversation',
      created_at: '',
      updated_at: '',
    });

    const conversation = await useConversationStore.getState().createConversation('New conversation');

    expect(conversation.id).toBe('16');
    expect(useConversationStore.getState().conversations[0]?.id).toBe('16');
  });

  it('keeps the latest conversation when detail requests finish out of order', async () => {
    let resolveFirst: ((value: any) => void) | undefined;
    let resolveSecond: ((value: any) => void) | undefined;
    vi.spyOn(api, 'get').mockImplementation((url) => {
      if (url === '/conversations/15/') {
        return new Promise((resolve) => { resolveFirst = resolve; });
      }
      return new Promise((resolve) => { resolveSecond = resolve; });
    });

    const first = useConversationStore.getState().fetchConversationDetail('15');
    const second = useConversationStore.getState().fetchConversationDetail('16');
    resolveSecond?.({ id: 16, title: 'Second', messages: [] });
    await second;
    resolveFirst?.({ id: 15, title: 'First', messages: [] });
    await first;

    expect(useConversationStore.getState().currentConversation?.id).toBe('16');
  });

  it('restores a waiting question after refreshing the conversation', async () => {
    let emit: ((event: RunEventEnvelope) => void) | undefined;
    vi.spyOn(api, 'get').mockResolvedValue({
      id: 'conversation-1',
      organization_id: 'org-1',
      title: 'Waiting',
      created_at: '',
      updated_at: '',
      messages: [{
        id: 'question-message',
        role: 'assistant',
        content: 'Which framework?',
        created_at: '',
      }],
      active_run: {
        id: 'run-waiting',
        organization_id: 'org-1',
        status: 'waiting_input',
        version: 3,
        next_event_sequence: 4,
        pending_input_request_id: 'input-1',
        pending_input_kind: 'answer',
        definition_snapshot: {},
        input: {},
        output_summary: {},
      },
    });
    vi.spyOn(runStream, 'streamRunEvents').mockImplementation((options) => {
      emit = options.onEvent as (event: RunEventEnvelope) => void;
      return { abort: vi.fn(), cursor: 0, done: new Promise(() => undefined) };
    });

    await useConversationStore.getState().fetchConversationDetail('conversation-1');
    emit?.({
      schema_version: 1,
      run_id: 'run-waiting',
      attempt_id: null,
      sequence: 1,
      type: 'input.required',
      payload: {
        input_request_id: 'input-1',
        input_kind: 'answer',
        question: 'Which framework?',
        options: [{ label: 'React', value: 'React' }],
      },
      created_at: '',
    });

    expect(useConversationStore.getState().activeRun?.id).toBe('run-waiting');
    expect(useConversationStore.getState().pendingQuestion).toMatchObject({
      kind: 'question',
      question: 'Which framework?',
    });
    expect(useConversationStore.getState().streamingMessageId).toBeNull();
    expect(useConversationStore.getState().currentConversation?.messages)
      .toHaveLength(1);
  });

  it('renders the canonical RunEvent stream', async () => {
    let emit: ((event: RunEventEnvelope) => void) | undefined;
    vi.spyOn(api, 'post').mockResolvedValue({
      id: 'run-1',
      organization_id: 'org-1',
      status: 'queued',
      version: 1,
      next_event_sequence: 1,
      definition_snapshot: {},
      input: {},
      output_summary: {},
    });
    vi.spyOn(runStream, 'streamRunEvents').mockImplementation((options) => {
      emit = options.onEvent as (event: RunEventEnvelope) => void;
      return { abort: vi.fn(), cursor: 0, done: new Promise(() => undefined) };
    });
    useConversationStore.setState({
      currentConversation: {
        id: 'conversation-1',
        title: 'Test',
        created_at: '',
        updated_at: '',
        messages: [],
      },
    });

    useConversationStore.getState().sendMessageStream('conversation-1', 'Hello');
    await vi.waitFor(() => expect(emit).toBeDefined());
    const event = (sequence: number, type: string, payload: Record<string, unknown>) => ({
      schema_version: 1,
      run_id: 'run-1',
      attempt_id: null,
      sequence,
      type,
      payload,
      created_at: '',
    });
    emit?.(event(1, 'run.started', {}));
    emit?.(event(2, 'output.delta', { text: 'Hello ' }));
    emit?.(event(3, 'output.delta', { text: 'world' }));
    emit?.(event(4, 'tool.started', { tool_call_id: 'tool-1', name: 'read' }));
    emit?.(event(5, 'tool.completed', {
      tool_call_id: 'tool-1', name: 'read', output: { lines: 3 },
    }));
    emit?.(event(6, 'input.required', {
      input_request_id: 'question-1',
      input_kind: 'permission',
      question: 'Allow access?',
      options: [{ label: 'Deny', value: 'deny' }],
    }));

    const assistant = useConversationStore.getState().currentConversation?.messages[1];
    expect(assistant?.content).toBe('Hello world\n\nAllow access?\n可选：Deny');
    expect(assistant?.metadata?.agent?.tool_calls[0]).toMatchObject({
      id: 'tool-1', name: 'read', status: 'completed', result: '{"lines":3}',
    });
    expect(useConversationStore.getState().pendingQuestion).toMatchObject({
      kind: 'permission', question: 'Allow access?',
    });
    expect(useConversationStore.getState().activeRun?.pending_input_request_id)
      .toBe('question-1');

    await useConversationStore.getState().answerQuestion(
      'conversation-1', { selections: ['deny'] },
    );
    expect(api.post).toHaveBeenLastCalledWith(
      '/organizations/org-1/runs/run-1/commands',
      expect.objectContaining({
        type: 'deny_permission',
        input_request_id: 'question-1',
      }),
    );
    emit?.(event(7, 'input.accepted', { input_request_id: 'question-1' }));
    emit?.(event(8, 'run.started', {}));
    emit?.(event(9, 'output.delta', { text: 'Continued separately' }));
    expect(
      useConversationStore.getState().currentConversation?.messages.map((message) => ({
        role: message.role,
        content: message.content,
      })),
    ).toEqual([
      { role: 'user', content: 'Hello' },
      { role: 'assistant', content: 'Hello world\n\nAllow access?\n可选：Deny' },
      { role: 'user', content: '拒绝' },
      { role: 'assistant', content: 'Continued separately' },
    ]);
  });

  it('submits composer Agent and Skill selections when creating a Run', async () => {
    vi.spyOn(api, 'post').mockResolvedValue({
      id: 'run-2',
      organization_id: 'org-1',
      status: 'queued',
    });

    await useConversationStore.getState().sendMessage(
      'conversation-1',
      'Use the selected configuration',
      { agentId: 42, skillNames: ['skill-1', 'skill-2'] },
    );

    expect(api.post).toHaveBeenCalledWith(
      '/conversations/conversation-1/send_message/',
      {
        content: 'Use the selected configuration',
        agent_id: 42,
        skill_names: ['skill-1', 'skill-2'],
      },
      { headers: { 'Idempotency-Key': expect.any(String) } },
    );
  });

  it('preserves multiple Codex questions and submits structured answers', async () => {
    let emit: ((event: RunEventEnvelope) => void) | undefined;
    vi.spyOn(api, 'post').mockResolvedValue({
      id: 'run-question',
      organization_id: 'org-1',
      status: 'queued',
      version: 1,
      next_event_sequence: 1,
      definition_snapshot: {},
      input: {},
      output_summary: {},
    });
    vi.spyOn(runStream, 'streamRunEvents').mockImplementation((options) => {
      emit = options.onEvent as (event: RunEventEnvelope) => void;
      return { abort: vi.fn(), cursor: 0, done: new Promise(() => undefined) };
    });
    useConversationStore.setState({
      currentConversation: {
        id: 'conversation-1',
        title: 'Test',
        created_at: '',
        updated_at: '',
        messages: [],
      },
    });

    useConversationStore.getState().sendMessageStream('conversation-1', 'Build it');
    await vi.waitFor(() => expect(emit).toBeDefined());
    emit?.({
      schema_version: 1,
      run_id: 'run-question',
      attempt_id: null,
      sequence: 1,
      type: 'input.required',
      payload: {
        input_request_id: 'input-1',
        input_kind: 'answer',
        kind: 'question',
        questions: [
          {
            id: 'framework',
            header: 'Framework',
            question: 'Which framework?',
            options: [{ label: 'React', value: 'React' }],
            is_other: true,
          },
          {
            id: 'token',
            header: 'Token',
            question: 'Provide the token',
            options: [],
            is_secret: true,
          },
        ],
      },
      created_at: '',
    });

    expect(useConversationStore.getState().pendingQuestion).toMatchObject({
      id: 'framework',
      question: 'Which framework?',
      questions: [
        { id: 'framework', isOther: true },
        { id: 'token', isSecret: true },
      ],
    });

    await useConversationStore.getState().answerQuestion('conversation-1', {
      answers: {
        framework: { answers: ['React'] },
        token: { answers: ['secret'] },
      },
    });
    expect(api.post).toHaveBeenLastCalledWith(
      '/organizations/org-1/runs/run-question/commands',
      expect.objectContaining({
        type: 'answer',
        input_request_id: 'input-1',
        payload: {
          answers: {
            framework: { answers: ['React'] },
            token: { answers: ['secret'] },
          },
        },
      }),
    );
    const messages = useConversationStore.getState().currentConversation?.messages ?? [];
    expect(messages[messages.length - 2]?.content)
      .toBe('Which framework?：React\nProvide the token：••••••');
    expect(messages[messages.length - 1])
      .toMatchObject({ role: 'assistant', content: '' });
  });
});
