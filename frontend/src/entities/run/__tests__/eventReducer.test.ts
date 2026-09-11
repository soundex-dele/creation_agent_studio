import { describe, expect, it } from 'vitest';

import {
  createRunEventState,
  ingestRunEvent,
  restoreRunEventSnapshot,
} from '../eventReducer';
import type { RunEventEnvelope, RunEventSnapshotEnvelope } from '../types';

function event(
  sequence: number,
  type: string,
  payload: Record<string, unknown> = {},
): RunEventEnvelope {
  return {
    schema_version: 1,
    run_id: 'run-1',
    attempt_id: null,
    sequence,
    type,
    payload,
    created_at: '2026-09-11T10:00:00Z',
  };
}

describe('RunEvent reducer', () => {
  it('applies contiguous deltas once', () => {
    const first = ingestRunEvent(
      createRunEventState('run-1'),
      event(1, 'output.delta', { text: 'A' }),
    );
    const duplicate = ingestRunEvent(first.state, event(1, 'output.delta', { text: 'A' }));

    expect(first.state.output).toBe('A');
    expect(first.state.nextSequence).toBe(2);
    expect(duplicate.duplicate).toBe(true);
    expect(duplicate.state.output).toBe('A');
  });

  it('buffers out-of-order events and drains them after the gap arrives', () => {
    const outOfOrder = ingestRunEvent(
      createRunEventState('run-1'),
      event(2, 'output.delta', { text: 'B' }),
    );
    expect(outOfOrder.applied).toBe(0);
    expect(outOfOrder.gap).toEqual({ missingFrom: 1, missingThrough: 1, after: 0 });

    const filled = ingestRunEvent(
      outOfOrder.state,
      event(1, 'output.delta', { text: 'A' }),
    );
    expect(filled.applied).toBe(2);
    expect(filled.gap).toBeNull();
    expect(filled.state.output).toBe('AB');
    expect(filled.state.nextSequence).toBe(3);
  });

  it('uses a snapshot to replace the output projection', () => {
    let state = ingestRunEvent(
      createRunEventState('run-1'),
      event(1, 'output.delta', { text: 'old' }),
    ).state;
    state = ingestRunEvent(
      state,
      event(2, 'output.snapshot', { text: 'canonical', through_sequence: 1 }),
    ).state;

    expect(state.output).toBe('canonical');
  });

  it('projects lifecycle and durable input state', () => {
    let state = ingestRunEvent(
      createRunEventState('run-1'),
      event(1, 'run.started'),
    ).state;
    state = ingestRunEvent(
      state,
      event(2, 'input.required', { input_request_id: 'request-1' }),
    ).state;
    expect(state.status).toBe('waiting_input');
    expect(state.pendingInput?.input_request_id).toBe('request-1');

    state = ingestRunEvent(state, event(3, 'input.accepted')).state;
    expect(state.status).toBe('queued');
    expect(state.pendingInput).toBeNull();
  });

  it('rejects another run and unknown schema versions', () => {
    const state = createRunEventState('run-1');
    expect(() =>
      ingestRunEvent(state, { ...event(1, 'run.started'), run_id: 'run-2' }),
    ).toThrow(/expected run-1/);
    expect(() =>
      ingestRunEvent(state, { ...event(1, 'run.started'), schema_version: 2 }),
    ).toThrow(/schema_version 2/);
  });

  it('restores a compacted projection at its durable cursor', () => {
    const snapshot: RunEventSnapshotEnvelope = {
      schema_version: 1,
      run_id: 'run-1',
      through_sequence: 20,
      projection: {
        runId: 'run-1',
        nextSequence: 21,
        status: 'running',
        output: 'retained output',
        progress: { current: 3, total: 5 },
        tools: {},
        pendingInput: null,
        artifactIds: ['artifact-1'],
      },
      created_at: '2026-09-11T10:00:00Z',
      updated_at: '2026-09-11T10:00:00Z',
    };

    const state = restoreRunEventSnapshot(snapshot);

    expect(state.output).toBe('retained output');
    expect(state.nextSequence).toBe(21);
    expect(state.buffered).toEqual({});
  });
});
