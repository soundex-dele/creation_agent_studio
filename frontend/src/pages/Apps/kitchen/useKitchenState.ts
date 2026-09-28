import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  kitchenApi,
  statePatch,
  type KitchenPatch,
  type KitchenSnapshot,
  type KitchenState,
} from "@/services/kitchenAssistant";
import { entryError } from "@/services/ideasTodos";

type Change = (state: KitchenState) => KitchenState;
interface Pending {
  patch: KitchenPatch;
  change: Change;
  conflict: boolean;
}
export function useKitchenState(base: string) {
  const service = useMemo(() => kitchenApi(base), [base]);
  const [snapshot, setSnapshot] = useState<KitchenSnapshot>();
  const current = useRef<KitchenSnapshot>();
  const lock = useRef(false);
  const alive = useRef(true);
  const pendingRef = useRef<Pending>();
  const [pending, setPending] = useState<Pending>();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  const accept = useCallback((value: KitchenSnapshot) => {
    if (alive.current) {
      current.current = value;
      setSnapshot(value);
    }
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    lock.current = true;
    setSaving(true);
    setError("");
    service
      .load(controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) accept(value);
      })
      .catch((err) => {
        if (!controller.signal.aborted) setError(entryError(err));
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          lock.current = false;
          setSaving(false);
        }
      });
    return () => controller.abort();
  }, [service, reload, accept]);
  async function send(operation: Pending): Promise<boolean> {
    lock.current = true;
    setSaving(true);
    setError("");
    try {
      const value = await service.save(operation.patch);
      if (alive.current) {
        accept(value);
        pendingRef.current = undefined;
        setPending(undefined);
      }
      return true;
    } catch (err) {
      if (alive.current) {
        const next = {
          ...operation,
          conflict:
            (err as { response?: { status?: number } }).response?.status ===
            409,
        };
        pendingRef.current = next;
        setPending(next);
        setError(entryError(err));
      }
      return false;
    } finally {
      lock.current = false;
      if (alive.current) setSaving(false);
    }
  }
  async function commit(change: Change, aiTaskId?: string): Promise<boolean> {
    if (lock.current || pendingRef.current || !current.current) return false;
    let operation: Pending;
    try {
      operation = {
        change,
        conflict: false,
        patch: {
          ...statePatch(current.current, change(current.current.data)),
          ...(aiTaskId ? { aiTaskId } : {}),
        },
      };
    } catch (err) {
      // Preparation errors occur before send's network error handling.
      if (alive.current) setError(err instanceof Error ? err.message : entryError(err));
      return false;
    }
    return send(operation);
  }
  async function retry() {
    const operation = pendingRef.current;
    if (!operation || lock.current) return;
    if (!operation.conflict) {
      await send(operation);
      return;
    }
    lock.current = true;
    setSaving(true);
    try {
      const latest = await service.load();
      accept(latest);
      // Reapply the explicit user action to fresh state only after the user
      // chooses this recovery. Network retries retain the original operation ID.
      await send({
        ...operation,
        conflict: false,
        patch: {
          ...statePatch(latest, operation.change(latest.data)),
          ...(operation.patch.aiTaskId
            ? { aiTaskId: operation.patch.aiTaskId }
            : {}),
        },
      });
    } catch (err) {
      if (alive.current) setError(entryError(err));
    } finally {
      lock.current = false;
      if (alive.current) setSaving(false);
    }
  }
  function refresh(discard = false) {
    if (lock.current || (pendingRef.current && !discard)) return;
    if (discard) {
      pendingRef.current = undefined;
      setPending(undefined);
    }
    setReload((v) => v + 1);
  }
  return {
    service,
    snapshot,
    busy: saving || !!pending,
    saving,
    error,
    pending,
    commit,
    retry,
    refresh,
  };
}
