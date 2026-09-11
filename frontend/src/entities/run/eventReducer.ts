import type {
  RunEventEnvelope,
  RunEventGap,
  RunEventIngestResult,
  RunEventState,
  RunEventSnapshotEnvelope,
  RunStatus,
} from './types';

const STATUS_BY_EVENT: Record<string, RunStatus> = {
  'run.queued': 'queued',
  'run.started': 'running',
  'run.waiting_input': 'waiting_input',
  'run.cancelling': 'cancelling',
  'run.retry_scheduled': 'queued',
  'run.succeeded': 'succeeded',
  'run.failed': 'failed',
  'run.cancelled': 'cancelled',
};

export function createRunEventState(
  runId: string | null = null,
  after = 0,
): RunEventState {
  if (!Number.isSafeInteger(after) || after < 0) {
    throw new Error('after must be a non-negative safe integer');
  }
  return {
    runId,
    nextSequence: after + 1,
    status: null,
    output: '',
    progress: null,
    tools: {},
    pendingInput: null,
    artifactIds: [],
    buffered: {},
  };
}

export function restoreRunEventSnapshot(
  snapshot: RunEventSnapshotEnvelope,
): RunEventState {
  if (snapshot.schema_version !== 1) {
    throw new Error(`Unsupported RunEvent snapshot schema_version ${snapshot.schema_version}`);
  }
  if (!Number.isSafeInteger(snapshot.through_sequence) || snapshot.through_sequence < 1) {
    throw new Error('RunEvent snapshot sequence must be a positive safe integer');
  }
  if (
    snapshot.projection.runId !== snapshot.run_id
    || snapshot.projection.nextSequence !== snapshot.through_sequence + 1
  ) {
    throw new Error('RunEvent snapshot projection cursor is inconsistent');
  }
  return {
    ...snapshot.projection,
    tools: { ...snapshot.projection.tools },
    artifactIds: [...snapshot.projection.artifactIds],
    buffered: {},
  };
}

function toolId(event: RunEventEnvelope): string {
  return String(
    event.payload.tool_call_id ?? event.payload.call_id ?? `sequence-${event.sequence}`,
  );
}

function applyEvent(state: RunEventState, event: RunEventEnvelope): RunEventState {
  const next: RunEventState = {
    ...state,
    runId: state.runId ?? event.run_id,
    nextSequence: event.sequence + 1,
  };
  const lifecycleStatus = STATUS_BY_EVENT[event.type];
  if (lifecycleStatus) next.status = lifecycleStatus;

  switch (event.type) {
    case 'output.delta':
      next.output += String(event.payload.text ?? '');
      break;
    case 'output.snapshot':
      next.output = String(event.payload.text ?? event.payload.output ?? '');
      break;
    case 'progress.updated':
      next.progress = { ...event.payload };
      break;
    case 'input.required':
      next.status = 'waiting_input';
      next.pendingInput = { ...event.payload };
      break;
    case 'input.accepted':
      next.status = 'queued';
      next.pendingInput = null;
      break;
    case 'input.expired':
      next.status = 'cancelled';
      next.pendingInput = null;
      break;
    case 'artifact.created': {
      const artifactId = String(event.payload.artifact_id ?? '');
      if (artifactId && !next.artifactIds.includes(artifactId)) {
        next.artifactIds = [...next.artifactIds, artifactId];
      }
      break;
    }
    case 'tool.started':
    case 'tool.completed':
    case 'tool.failed': {
      const id = toolId(event);
      next.tools = {
        ...next.tools,
        [id]: { ...next.tools[id], ...event.payload, event_type: event.type },
      };
      break;
    }
  }
  return next;
}

function currentGap(state: RunEventState): RunEventGap | null {
  const sequences = Object.keys(state.buffered).map(Number).sort((a, b) => a - b);
  if (!sequences.length || sequences[0] <= state.nextSequence) return null;
  return {
    missingFrom: state.nextSequence,
    missingThrough: sequences[0] - 1,
    after: state.nextSequence - 1,
  };
}

export function ingestRunEvent(
  state: RunEventState,
  event: RunEventEnvelope,
): RunEventIngestResult {
  if (event.schema_version !== 1) {
    throw new Error(`Unsupported RunEvent schema_version ${event.schema_version}`);
  }
  if (!Number.isSafeInteger(event.sequence) || event.sequence < 1) {
    throw new Error('RunEvent sequence must be a positive safe integer');
  }
  if (state.runId !== null && state.runId !== event.run_id) {
    throw new Error(`RunEvent belongs to ${event.run_id}, expected ${state.runId}`);
  }
  if (event.sequence < state.nextSequence) {
    return { state, applied: 0, duplicate: true, gap: currentGap(state) };
  }

  const buffered = { ...state.buffered, [event.sequence]: event };
  let next: RunEventState = {
    ...state,
    runId: state.runId ?? event.run_id,
    buffered,
  };
  let applied = 0;
  while (next.buffered[next.nextSequence]) {
    const contiguous = next.buffered[next.nextSequence];
    const remaining = { ...next.buffered };
    delete remaining[next.nextSequence];
    next = applyEvent({ ...next, buffered: remaining }, contiguous);
    applied += 1;
  }

  return {
    state: next,
    applied,
    duplicate: false,
    gap: currentGap(next),
  };
}
