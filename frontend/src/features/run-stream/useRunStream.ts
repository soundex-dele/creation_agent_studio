import { useCallback, useEffect, useRef, useState } from 'react';

import {
  createRunEventState,
  ingestRunEvent,
  restoreRunEventSnapshot,
  type RunEventState,
} from '@/entities/run';
import { streamRunEvents, type RunStreamHandle } from '@/services/runStream';


export interface UseRunStreamOptions {
  organizationId: string;
  runId: string | null;
  enabled?: boolean;
}


export interface UseRunStreamResult {
  state: RunEventState;
  connected: boolean;
  error: Error | null;
  reset: () => void;
}


export function useRunStream({
  organizationId,
  runId,
  enabled = true,
}: UseRunStreamOptions): UseRunStreamResult {
  const [state, setState] = useState<RunEventState>(() =>
    createRunEventState(runId),
  );
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const handleRef = useRef<RunStreamHandle | null>(null);

  const reset = useCallback(() => {
    setState(createRunEventState(runId));
    setError(null);
  }, [runId]);

  useEffect(() => {
    handleRef.current?.abort();
    handleRef.current = null;
    setState(createRunEventState(runId));
    setConnected(false);
    setError(null);
    if (!enabled || !runId) return undefined;

    const handle = streamRunEvents({
      organizationId,
      runId,
      onEvent: (event) => {
        setState((current) => ingestRunEvent(current, event).state);
      },
      onSnapshot: (snapshot) => {
        setState(restoreRunEventSnapshot(snapshot));
      },
      onConnectionChange: (value) => {
        setConnected(value);
        if (value) setError(null);
      },
      onError: setError,
    });
    handleRef.current = handle;
    return () => {
      handle.abort();
      if (handleRef.current === handle) handleRef.current = null;
    };
  }, [enabled, organizationId, runId]);

  return { state, connected, error, reset };
}
