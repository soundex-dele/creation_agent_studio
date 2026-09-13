import { beforeEach, describe, expect, it, vi } from 'vitest';

import { api } from '@/services/api';
import * as runStream from '@/services/runStream';
import type { RunEventEnvelope } from '@/entities/run';
import { useConversationStore } from '../useConversationStore';

describe('useConversationStore durable Run integration', () => {
  beforeEach(() => {
    useConversationStore.setState({
      currentConversation: null,
      activeRun: null,
      error: null,
      streamingMessageId: null,
      pendingQuestion: null,
      agentActivity: null,
    });
    vi.restoreAllMocks();
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
    emit?.(event(5, 'input.required', {
      input_request_id: 'question-1',
      input_kind: 'permission',
      question: 'Allow access?',
      options: [{ label: 'Deny', value: 'deny' }],
    }));

    const assistant = useConversationStore.getState().currentConversation?.messages[1];
    expect(assistant?.content).toBe('Hello world');
    expect(assistant?.metadata?.agent?.tool_calls[0]).toMatchObject({
      id: 'tool-1', name: 'read', status: 'running',
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
  });
});
