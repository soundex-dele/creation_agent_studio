import { Button } from "antd";
import type { KitchenState } from "@/services/kitchenAssistant";
import { cookingRecipes, secondsLeft } from "./domain";

export function TimerPanel({
  state,
  now,
  busy,
  commit,
}: {
  state: KitchenState;
  now: number;
  busy: boolean;
  commit: (change: (state: KitchenState) => KitchenState) => Promise<boolean>;
}) {
  const cooking = state.cooking;
  if (!cooking) return null;
  const ids = [
    ...new Set([
      ...Object.keys(cooking.timers),
      ...Object.keys(cooking.pausedTimers ?? {}),
    ]),
  ];
  return (
    <div className="kitchen-timers" aria-label="全部菜品计时器">
      {ids.map((id) => {
        const paused = cooking.pausedTimers?.[id];
        const remaining = paused ?? secondsLeft(cooking.timers[id], now);
        const meta = cooking.timerMeta?.[id];
        const recipe = cookingRecipes(state).find(
          (r) => r.id === (meta?.recipeId ?? id),
        );
        const name = `${recipe?.name ?? "菜品"}${meta ? ` · ${recipe?.steps.find((s) => s.id === meta.stepId)?.title ?? "步骤"}` : ""}`;
        const update = (action: "clear" | "pause" | "resume" | "extend") =>
          void commit((s) => {
            if (!s.cooking) return s;
            const timerMeta = { ...s.cooking.timerMeta };
            const timers = { ...s.cooking.timers };
            const pausedTimers = { ...s.cooking.pausedTimers };
            if (action === "clear") {
              delete timers[id];
              delete pausedTimers[id];
              delete timerMeta[id];
            }
            if (action === "pause") {
              pausedTimers[id] = secondsLeft(timers[id]);
              delete timers[id];
            }
            if (action === "resume") {
              timers[id] = Date.now() + (pausedTimers[id] ?? 0) * 1000;
              delete pausedTimers[id];
            }
            if (action === "extend") {
              if (pausedTimers[id] !== undefined) pausedTimers[id] += 60;
              else timers[id] = Math.max(Date.now(), timers[id] ?? 0) + 60000;
            }
            return {
              ...s,
              cooking: { ...s.cooking, timers, pausedTimers, timerMeta },
            };
          });
        return (
          <div key={id} className={remaining === 0 ? "is-finished" : ""}>
            <span>{name}</span>
            <strong role={remaining === 0 ? "status" : "timer"}>
              {paused !== undefined ? "已暂停 · " : ""}
              {remaining === 0
                ? "计时结束"
                : `${Math.floor(remaining / 60)}:${String(remaining % 60).padStart(2, "0")}`}
            </strong>
            <Button
              disabled={busy || remaining === 0}
              aria-label={`${name}${paused !== undefined ? "继续计时" : "暂停计时"}`}
              onClick={() => update(paused !== undefined ? "resume" : "pause")}
            >
              {paused !== undefined ? "继续" : "暂停"}
            </Button>
            <Button
              disabled={busy || remaining >= 86340}
              aria-label={`${name}增加一分钟`}
              onClick={() => update("extend")}
            >
              ＋1 分钟
            </Button>
            <Button
              disabled={busy}
              aria-label={`${name}清除计时`}
              onClick={() => update("clear")}
            >
              清除
            </Button>
          </div>
        );
      })}
    </div>
  );
}
