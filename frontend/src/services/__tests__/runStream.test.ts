import { afterEach, describe, expect, it, vi } from 'vitest';

import type { RunEventEnvelope } from '@/entities/run';
import {
  parseRunSSEFrame,
  RunEventSequencer,
  SSEFrameBuffer,
  streamRunEvents,
} from '../runStream';
import type { RunEventSnapshotEnvelope } from '@/entities/run';
import * as authSession from '../authSession';

function event(sequence: number, text = String(sequence)): RunEventEnvelope {
  return {
    schema_version: 1,
    run_id: 'run-1',
    attempt_id: null,
    sequence,
    type: 'output.delta',
    payload: { text },
    created_at: '2026-09-11T10:00:00Z',
  };
}

describe('V2 Run stream transport', () => {
  afterEach(() => vi.restoreAllMocks());
  it('parses multiline and chunked SSE frames', () => {
    const parser = new SSEFrameBuffer();
    const json = JSON.stringify(event(1));
    expect(parser.push(`id: 1\nevent: output.delta\ndata: ${json.slice(0, 20)}`)).toEqual([]);
    expect(parser.push(`${json.slice(20)}\n\n`)).toEqual([event(1)]);
    expect(parseRunSSEFrame(': keep-alive')).toBeNull();
  });

  it('fills a sequence gap before delivering the buffered event', async () => {
    const delivered: number[] = [];
    const fetchMissing = vi.fn(async () => ({
      results: [event(1)],
      next_after: 1,
      high_water: 2,
      has_more: false,
    }));
    const sequencer = new RunEventSequencer(
      'run-1',
      0,
      fetchMissing,
      (item) => {
        delivered.push(item.sequence);
      },
    );

    await sequencer.accept(event(2));

    expect(fetchMissing).toHaveBeenCalledWith(0);
    expect(delivered).toEqual([1, 2]);
    expect(sequencer.cursor).toBe(2);
  });

  it('ignores events at or behind the durable cursor', async () => {
    const deliver = vi.fn();
    const sequencer = new RunEventSequencer(
      'run-1',
      2,
      vi.fn(),
      deliver,
    );

    await sequencer.accept(event(2));

    expect(deliver).not.toHaveBeenCalled();
    expect(sequencer.cursor).toBe(2);
  });

  it('fails closed when the events API cannot fill a gap', async () => {
    const sequencer = new RunEventSequencer(
      'run-1',
      0,
      async () => ({ results: [], next_after: 0, high_water: 2, has_more: false }),
      vi.fn(),
    );

    await expect(sequencer.accept(event(2))).rejects.toThrow(/gap is unresolved/);
  });

  it('loads a durable snapshot and resumes when history was compacted', async () => {
    const durableSnapshot: RunEventSnapshotEnvelope = {
      schema_version: 1,
      run_id: 'run-1',
      through_sequence: 10,
      projection: {
        runId: 'run-1',
        nextSequence: 11,
        status: 'running',
        output: 'snapshot output',
        progress: null,
        tools: {},
        pendingInput: null,
        artifactIds: [],
      },
      created_at: '2026-09-11T10:00:00Z',
      updated_at: '2026-09-11T10:00:00Z',
    };
    const fetchImpl = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        code: 'event_history_compacted',
        snapshot_url: 'http://example.test/snapshot',
        snapshot_through_sequence: 10,
        resume_after: 10,
      }), { status: 410, headers: { 'Content-Type': 'application/problem+json' } }))
      .mockResolvedValueOnce(new Response(JSON.stringify(durableSnapshot), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }));
    const snapshots: RunEventSnapshotEnvelope[] = [];
    const holder: { current?: ReturnType<typeof streamRunEvents> } = {};
    const handle = streamRunEvents({
      organizationId: 'organization-1',
      runId: 'run-1',
      baseUrl: '/api',
      fetchImpl,
      onEvent: vi.fn(),
      onSnapshot: (snapshot) => {
        snapshots.push(snapshot);
        holder.current?.abort();
      },
    });
    holder.current = handle;

    await handle.done;

    expect(fetchImpl).toHaveBeenCalledTimes(2);
    expect(snapshots).toEqual([durableSnapshot]);
    expect(handle.cursor).toBe(10);
  });

  it('refreshes an expired access token once and resumes the same cursor', async () => {
    let token = 'expired';
    vi.spyOn(authSession, 'getAccessToken').mockImplementation(() => token);
    vi.spyOn(authSession, 'refreshAccessToken').mockImplementation(async () => {
      token = 'fresh';
    });
    const terminal = { ...event(1), type: 'run.succeeded', payload: {} };
    const fetchImpl = vi.fn()
      .mockResolvedValueOnce(new Response('', { status: 401 }))
      .mockResolvedValueOnce(new Response(
        `data: ${JSON.stringify(terminal)}\n\n`,
        { status: 200, headers: { 'Content-Type': 'text/event-stream' } },
      ));
    const delivered: RunEventEnvelope[] = [];

    const handle = streamRunEvents({
      organizationId: 'organization-1',
      runId: 'run-1',
      baseUrl: '/api',
      fetchImpl,
      onEvent: (item) => { delivered.push(item); },
    });
    await handle.done;

    expect(authSession.refreshAccessToken).toHaveBeenCalledTimes(1);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    expect(new Headers(fetchImpl.mock.calls[0][1]?.headers).get('Authorization'))
      .toBe('Bearer expired');
    expect(new Headers(fetchImpl.mock.calls[1][1]?.headers).get('Authorization'))
      .toBe('Bearer fresh');
    expect(delivered).toEqual([terminal]);
  });
});
