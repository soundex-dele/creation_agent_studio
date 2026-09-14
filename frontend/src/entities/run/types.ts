export type RunStatus =
  | 'queued'
  | 'running'
  | 'waiting_input'
  | 'waiting_children'
  | 'cancelling'
  | 'succeeded'
  | 'failed'
  | 'cancelled';

export interface RunEventEnvelope {
  schema_version: number;
  run_id: string;
  attempt_id: string | null;
  sequence: number;
  type: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface RunEventGap {
  missingFrom: number;
  missingThrough: number;
  after: number;
}

export interface RunEventState {
  runId: string | null;
  nextSequence: number;
  status: RunStatus | null;
  output: string;
  progress: Record<string, unknown> | null;
  tools: Record<string, Record<string, unknown>>;
  pendingInput: Record<string, unknown> | null;
  artifactIds: string[];
  buffered: Record<number, RunEventEnvelope>;
}

export interface RunEventIngestResult {
  state: RunEventState;
  applied: number;
  duplicate: boolean;
  gap: RunEventGap | null;
}

export interface RunEventSnapshotEnvelope {
  schema_version: number;
  run_id: string;
  through_sequence: number;
  projection: Omit<RunEventState, 'buffered'>;
  created_at: string;
  updated_at: string;
}

export interface AgentQuestionOption {
  label: string;
  value: string;
  description?: string;
}

export interface AgentQuestion {
  header: string;
  question: string;
  kind: 'question' | 'permission';
  options: AgentQuestionOption[];
}

export interface AgentToolCall {
  id: string;
  name: string;
  input?: string;
  result?: string;
  status: string;
  error_message?: string;
}
