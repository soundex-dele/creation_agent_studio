import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api';
import { createConnectionApi, loadConnectionCollection } from '../chatConnection';
import { streamRunEvents } from '../runStream';
import * as runStream from '../runStream';
import { createConversationStore, useConversationStore } from '@/stores/useConversationStore';
import type { RunEventSnapshotEnvelope, RunEventEnvelope } from '@/entities/run';
import { applicationPath } from '@/lib/applicationCatalog';

afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); });

describe('remote connection isolation and recovery', () => {
  it('sends modes to the selected computer and routes Codex questions and answers back', async () => {
    const store = createConversationStore({ deviceId: 'computer' });
    store.setState({ currentConversation: { id: '1', title: 'chat', created_at: '', updated_at: '', messages: [] } });
    const post = vi.spyOn(api, 'post').mockResolvedValue({ id: 'run-1', organization_id: 'local-org', status: 'queued' });
    let emit: ((event: RunEventEnvelope) => void) | undefined;
    vi.spyOn(runStream, 'streamRunEvents').mockImplementation(options => {
      expect(options.connection).toEqual({ deviceId: 'computer' });
      emit = options.onEvent;
      return { abort: vi.fn(), done: new Promise(() => undefined), cursor: 0 };
    });
    try {
      const controller = store.getState().sendMessageStream('1', 'Plan this', {
        permissionMode: 'allow_all', collaborationMode: 'plan',
      });
      await (controller as AbortController & { submitted: Promise<void> }).submitted;
      expect(post).toHaveBeenCalledWith('/remote/devices/computer/proxy/conversations/1/send_message/', {
        content: 'Plan this', permission_mode: 'allow_all', collaboration_mode: 'plan',
      }, expect.any(Object));
      emit?.({ schema_version: 1, run_id: 'run-1', attempt_id: null, sequence: 1, created_at: '',
        type: 'input.required', payload: { input_request_id: 'input-1', input_kind: 'answer',
          questions: [{ id: 'framework', header: '框架', question: '选择哪个框架？', options: [{ label: 'React', value: 'React' }] }],
        },
      });
      expect(store.getState().pendingQuestion?.question).toBe('选择哪个框架？');
      await store.getState().answerQuestion('1', { answers: { framework: { answers: ['React'] } } });
      expect(post).toHaveBeenLastCalledWith('/remote/devices/computer/proxy/organizations/local-org/runs/run-1/commands',
        expect.objectContaining({ type: 'answer', input_request_id: 'input-1',
          payload: { answers: { framework: { answers: ['React'] } } },
        }), expect.any(Object));
    } finally { store.getState().disconnect(); }
  });
  it('loads catalog pages through the selected computer instead of following local absolute URLs', async () => {
    const get = vi.spyOn(api, 'get')
      .mockResolvedValueOnce({ results: [{ id: 1 }], next: 'http://127.0.0.1:8080/api/v1/apps/?page=2' })
      .mockResolvedValueOnce({ results: [{ id: 2 }], next: null });
    const result = await loadConnectionCollection(createConnectionApi({ deviceId: 'computer' }), '/apps/', { kind: 'chat' });
    expect(result).toEqual([{ id: 1 }, { id: 2 }]);
    expect(get.mock.calls.map(call => [call[0], call[1]])).toEqual([
      ['/remote/devices/computer/proxy/apps/', { kind: 'chat', page: 1 }],
      ['/remote/devices/computer/proxy/apps/', { kind: 'chat', page: 2 }],
    ]);
  });
  it('keeps server and computer stores isolated despite overlapping numeric ids', async () => {
    const first = createConversationStore({ deviceId: 'first' });
    const second = createConversationStore({ deviceId: 'second' });
    useConversationStore.setState({ conversations: [] });
    vi.spyOn(api, 'get').mockImplementation(async path => ({
      id: 1, title: path.includes('first') ? 'First computer' : 'Second computer', messages: [],
    }) as never);
    await Promise.all([
      first.getState().fetchConversationDetail('1'), second.getState().fetchConversationDetail('1'),
    ]);
    expect(first.getState().currentConversation?.title).toBe('First computer');
    expect(second.getState().currentConversation?.title).toBe('Second computer');
    expect(useConversationStore.getState().conversations).toEqual([]);
    expect(api.get).toHaveBeenCalledWith('/remote/devices/first/proxy/conversations/1/', undefined, expect.any(Object));
    first.getState().disconnect(); second.getState().disconnect();
  });

  it('keeps the same idempotency key after a lost response and a manual retry', async () => {
    vi.useFakeTimers();
    const transport = createConnectionApi({ deviceId: 'computer' });
    const post = vi.spyOn(api, 'post').mockRejectedValue(new Error('response lost'));
    const failed = transport.post('/conversations/', { title: 'one' }, { headers: { 'Idempotency-Key': 'original' } });
    const caught = failed.catch(() => undefined);
    await vi.runAllTimersAsync();
    await caught;
    post.mockResolvedValue({ id: 1 });
    await transport.post('/conversations/', { title: 'one' }, { headers: { 'Idempotency-Key': 'newly-generated' } });
    expect(post.mock.calls.map(call => (call[2]?.headers as Record<string, string>)['Idempotency-Key']))
      .toEqual(['original', 'original', 'original', 'original']);
  });

  it('routes compacted snapshots through the same computer, ignoring its loopback host', async () => {
    const snapshot: RunEventSnapshotEnvelope = {
      schema_version: 1, run_id: 'run-1', through_sequence: 10,
      projection: { runId: 'run-1', nextSequence: 11, status: 'running', output: 'restored',
        progress: null, tools: {}, pendingInput: null, artifactIds: [] },
      created_at: '2026-09-22T00:00:00Z', updated_at: '2026-09-22T00:00:00Z',
    };
    const fetchImpl = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        code: 'event_history_compacted', snapshot_url: 'http://127.0.0.1:8080/api/v1/organizations/local-org/runs/run-1/snapshot',
        snapshot_through_sequence: 10, resume_after: 10,
      }), { status: 410 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(snapshot)));
    const handle = streamRunEvents({
      connection: { deviceId: 'computer' }, organizationId: 'local-org', runId: 'run-1',
      fetchImpl, authToken: 'server-token', baseUrl: '/api/v1', onEvent: vi.fn(),
      onSnapshot: () => { handle.abort(); },
    });
    await handle.done;
    expect(fetchImpl.mock.calls.map(call => call[0])).toEqual([
      '/api/v1/remote/devices/computer/proxy/organizations/local-org/runs/run-1/stream?after=0',
      '/api/v1/remote/devices/computer/proxy/organizations/local-org/runs/run-1/snapshot',
    ]);
  });

  it('detects a Run started from the other screen while idle', async () => {
    const store = createConversationStore({ deviceId: 'computer' });
    store.setState({ currentConversation: { id: '1', title: 'chat', created_at: '', updated_at: '', messages: [] } });
    const stream = vi.spyOn(runStream, 'streamRunEvents').mockReturnValue({ abort: vi.fn(), done: Promise.resolve(), cursor: 0 });
    const get = vi.spyOn(api, 'get').mockResolvedValue({ id: 1, messages: [],
      active_run: { id: 'other-screen-run', organization_id: 'local-org', status: 'running' } });
    await store.getState().refreshIfIdle('1');
    expect(get).toHaveBeenCalledTimes(1);
    expect(stream).toHaveBeenCalledWith(expect.objectContaining({
      connection: { deviceId: 'computer' }, runId: 'other-screen-run', organizationId: 'local-org',
    }));
    store.setState({ streamingMessageId: 'active' });
    await store.getState().refreshIfIdle('1');
    expect(get).toHaveBeenCalledTimes(1);
    store.getState().disconnect();
  });

  it('registers the dedicated mobile computer entry', () => {
    expect(applicationPath({ id: 'my-computer', applicationId: 1, rendererKey: 'my-computer', kind: 'custom' }))
      .toBe('/apps/my-computer?entry=apps');
  });
});
