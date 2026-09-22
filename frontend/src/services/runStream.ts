import type { RunEventEnvelope, RunEventSnapshotEnvelope } from '@/entities/run';
import { getAccessToken, refreshAccessToken } from './authSession';
import { API_BASE_URL } from './apiBaseUrl';
import { tenantApiRoot } from './tenantContext';
import { remotePath, type RemoteConnection } from './chatConnection';

export interface RunEventsPage {
  results: RunEventEnvelope[];
  next_after: number;
  high_water: number;
  has_more: boolean;
}

export interface RunStreamOptions {
  connection?: RemoteConnection;
  organizationId: string;
  runId: string;
  after?: number;
  authToken?: string | null;
  baseUrl?: string;
  onEvent: (event: RunEventEnvelope) => void | Promise<void>;
  onSnapshot?: (snapshot: RunEventSnapshotEnvelope) => void | Promise<void>;
  onError?: (error: Error) => void;
  onConnectionChange?: (connected: boolean) => void;
  fetchImpl?: typeof fetch;
}

export interface EventHistoryCompactedProblem {
  code: 'event_history_compacted';
  snapshot_url: string;
  snapshot_through_sequence: number;
  resume_after: number;
}

export class RunHistoryCompactedError extends Error {
  constructor(readonly problem: EventHistoryCompactedProblem) {
    super('Run event history was compacted');
  }
}

export interface RunStreamHandle {
  abort: () => void;
  readonly cursor: number;
  done: Promise<void>;
}

const TERMINAL_RUN_EVENTS = new Set([
  'run.succeeded',
  'run.failed',
  'run.cancelled',
]);

function assertEnvelope(value: unknown): RunEventEnvelope {
  if (!value || typeof value !== 'object') throw new Error('Invalid RunEvent payload');
  const event = value as Partial<RunEventEnvelope>;
  if (
    event.schema_version !== 1
    || typeof event.run_id !== 'string'
    || !Number.isSafeInteger(event.sequence)
    || Number(event.sequence) < 1
    || typeof event.type !== 'string'
    || !event.payload
    || typeof event.payload !== 'object'
    || typeof event.created_at !== 'string'
  ) {
    throw new Error('Invalid RunEvent envelope');
  }
  return event as RunEventEnvelope;
}

function assertSnapshot(value: unknown): RunEventSnapshotEnvelope {
  if (!value || typeof value !== 'object') throw new Error('Invalid RunEvent snapshot');
  const snapshot = value as Partial<RunEventSnapshotEnvelope>;
  if (
    snapshot.schema_version !== 1
    || typeof snapshot.run_id !== 'string'
    || !Number.isSafeInteger(snapshot.through_sequence)
    || Number(snapshot.through_sequence) < 1
    || !snapshot.projection
    || typeof snapshot.projection !== 'object'
  ) {
    throw new Error('Invalid RunEvent snapshot');
  }
  return snapshot as RunEventSnapshotEnvelope;
}

async function compactedError(response: Response): Promise<RunHistoryCompactedError> {
  const body = await response.json() as Partial<EventHistoryCompactedProblem>;
  if (
    body.code !== 'event_history_compacted'
    || typeof body.snapshot_url !== 'string'
    || !Number.isSafeInteger(body.snapshot_through_sequence)
    || body.resume_after !== body.snapshot_through_sequence
  ) {
    throw new Error('Invalid event_history_compacted response');
  }
  return new RunHistoryCompactedError(body as EventHistoryCompactedProblem);
}

export function parseRunSSEFrame(frame: string): RunEventEnvelope | null {
  if (!frame.trim() || frame.trimStart().startsWith(':')) return null;
  const dataLines: string[] = [];
  for (const line of frame.split(/\r?\n/)) {
    if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart());
  }
  if (!dataLines.length) return null;
  return assertEnvelope(JSON.parse(dataLines.join('\n')));
}

export class SSEFrameBuffer {
  private buffer = '';

  push(text: string, complete = false): RunEventEnvelope[] {
    this.buffer += text;
    const frames = this.buffer.split(/\r?\n\r?\n/);
    this.buffer = frames.pop() ?? '';
    if (complete && this.buffer.trim()) {
      frames.push(this.buffer);
      this.buffer = '';
    }
    return frames
      .map(parseRunSSEFrame)
      .filter((event): event is RunEventEnvelope => event !== null);
  }
}

export class RunEventSequencer {
  private pending = new Map<number, RunEventEnvelope>();

  constructor(
    readonly runId: string,
    private currentCursor: number,
    private readonly fetchMissing: (after: number) => Promise<RunEventsPage>,
    private readonly deliver: (event: RunEventEnvelope) => void | Promise<void>,
  ) {}

  get cursor(): number {
    return this.currentCursor;
  }

  reset(after: number): void {
    if (!Number.isSafeInteger(after) || after < this.currentCursor) {
      throw new Error('RunEvent sequencer cannot reset behind its durable cursor');
    }
    this.pending.clear();
    this.currentCursor = after;
  }

  private add(event: RunEventEnvelope): void {
    if (event.run_id !== this.runId) {
      throw new Error(`RunEvent belongs to ${event.run_id}, expected ${this.runId}`);
    }
    if (event.schema_version !== 1) {
      throw new Error(`Unsupported RunEvent schema_version ${event.schema_version}`);
    }
    if (event.sequence > this.currentCursor) this.pending.set(event.sequence, event);
  }

  private async drain(): Promise<void> {
    let contiguous = this.pending.get(this.currentCursor + 1);
    while (contiguous) {
      this.pending.delete(contiguous.sequence);
      await this.deliver(contiguous);
      this.currentCursor = contiguous.sequence;
      contiguous = this.pending.get(this.currentCursor + 1);
    }
  }

  async accept(event: RunEventEnvelope): Promise<void> {
    if (event.sequence <= this.currentCursor) return;
    this.add(event);
    await this.drain();

    while (this.pending.size > 0) {
      const firstPending = Math.min(...this.pending.keys());
      if (firstPending === this.currentCursor + 1) {
        await this.drain();
        continue;
      }
      const page = await this.fetchMissing(this.currentCursor);
      if (!page.results.length) {
        throw new Error(
          `RunEvent gap is unresolved after sequence ${this.currentCursor}`,
        );
      }
      page.results.forEach((missing) => this.add(missing));
      const previousCursor = this.currentCursor;
      await this.drain();
      if (this.currentCursor === previousCursor) {
        throw new Error(
          `RunEvent gap is unresolved after sequence ${this.currentCursor}`,
        );
      }
    }
  }
}

class RunStreamAuthenticationError extends Error {}

function delay(milliseconds: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const timeout = setTimeout(resolve, milliseconds);
    signal.addEventListener('abort', () => {
      clearTimeout(timeout);
      resolve();
    }, { once: true });
  });
}

export function streamRunEvents(options: RunStreamOptions): RunStreamHandle {
  const controller = new AbortController();
  const fetchImpl = options.fetchImpl ?? fetch;
  const baseUrl = options.baseUrl ?? API_BASE_URL;
  const runPath = `${options.connection ? `/organizations/${options.organizationId}` : tenantApiRoot(options.organizationId)}/runs/${options.runId}`;
  const root = `${baseUrl}${options.connection ? remotePath(options.connection, runPath) : runPath}`;
  const managedAuthentication = options.authToken === undefined;
  const currentToken = (): string | null => (
    managedAuthentication ? getAccessToken() : options.authToken ?? null
  );
  const authenticatedFetch = async (
    url: string,
    init: RequestInit,
  ): Promise<Response> => {
    const send = () => {
      const token = currentToken();
      const headers = new Headers(init.headers);
      if (token) headers.set('Authorization', `Bearer ${token}`);
      else headers.delete('Authorization');
      return fetchImpl(url, { ...init, headers });
    };
    let response = await send();
    if (response.status !== 401 || !managedAuthentication) return response;
    try {
      await refreshAccessToken();
    } catch {
      throw new RunStreamAuthenticationError('Run stream authentication expired');
    }
    response = await send();
    if (response.status === 401) {
      throw new RunStreamAuthenticationError('Run stream authentication expired');
    }
    return response;
  };

  const fetchPage = async (after: number): Promise<RunEventsPage> => {
    const response = await authenticatedFetch(`${root}/events?after=${after}&limit=500`, {
      credentials: 'include',
      signal: controller.signal,
    });
    if (response.status === 410) throw await compactedError(response);
    if (!response.ok) throw new Error(`Run events request failed with HTTP ${response.status}`);
    return response.json() as Promise<RunEventsPage>;
  };
  const sequencer = new RunEventSequencer(
    options.runId,
    options.after ?? 0,
    fetchPage,
    options.onEvent,
  );

  const recoverCompactedHistory = async (
    problem: EventHistoryCompactedProblem,
  ): Promise<void> => {
    let snapshotUrl = problem.snapshot_url;
    if (options.connection) {
      const path = new URL(snapshotUrl, 'http://local.invalid').pathname;
      const expected = `/api/v1/organizations/${options.organizationId}/runs/${options.runId}/snapshot`;
      if (path !== expected && path !== `/api/v1/runs/${options.runId}/snapshot`) {
        throw new Error('Snapshot does not belong to this computer and Run');
      }
      snapshotUrl = `${root}/snapshot`;
    }
    const response = await authenticatedFetch(snapshotUrl, {
      credentials: 'include',
      signal: controller.signal,
    });
    if (!response.ok) {
      throw new Error(`Run snapshot request failed with HTTP ${response.status}`);
    }
    const snapshot = assertSnapshot(await response.json());
    if (
      snapshot.run_id !== options.runId
      || snapshot.through_sequence !== problem.snapshot_through_sequence
    ) {
      throw new Error('RunEvent snapshot does not match the compacted history response');
    }
    await options.onSnapshot?.(snapshot);
    sequencer.reset(snapshot.through_sequence);
  };

  const done = (async () => {
    let retryDelay = 250;
    while (!controller.signal.aborted) {
      try {
        const response = await authenticatedFetch(`${root}/stream?after=${sequencer.cursor}`, {
          credentials: 'include',
          headers: {
            Accept: 'text/event-stream',
            'Last-Event-ID': String(sequencer.cursor),
          },
          signal: controller.signal,
        });
        if (response.status === 410) {
          await recoverCompactedHistory((await compactedError(response)).problem);
          retryDelay = 250;
          continue;
        }
        if (!response.ok) throw new Error(`Run stream failed with HTTP ${response.status}`);
        if (!response.body) throw new Error('Run stream has no response body');
        options.onConnectionChange?.(true);
        retryDelay = 250;
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        const frames = new SSEFrameBuffer();
        let complete = false;
        while (!complete && !controller.signal.aborted) {
          const chunk = await reader.read();
          complete = chunk.done;
          const decoded = decoder.decode(chunk.value ?? new Uint8Array(), {
            stream: !complete,
          });
          for (const event of frames.push(decoded, complete)) {
            await sequencer.accept(event);
            if (TERMINAL_RUN_EVENTS.has(event.type)) {
              controller.abort();
              break;
            }
          }
        }
        options.onConnectionChange?.(false);
        if (!controller.signal.aborted) throw new Error('Run stream disconnected');
      } catch (value) {
        options.onConnectionChange?.(false);
        if (controller.signal.aborted) break;
        if (value instanceof RunStreamAuthenticationError) {
          options.onError?.(value);
          controller.abort();
          break;
        }
        let handledError = value;
        if (value instanceof RunHistoryCompactedError) {
          try {
            await recoverCompactedHistory(value.problem);
            retryDelay = 250;
            continue;
          } catch (recoveryError) {
            handledError = recoveryError;
          }
        }
        const error = handledError instanceof Error
          ? handledError
          : new Error(String(handledError));
        options.onError?.(error);
        await delay(retryDelay, controller.signal);
        retryDelay = Math.min(retryDelay * 2, 5000);
      }
    }
  })();

  return {
    abort: () => controller.abort(),
    get cursor() {
      return sequencer.cursor;
    },
    done,
  };
}
