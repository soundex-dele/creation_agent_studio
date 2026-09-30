import { Button } from "antd";
import type { KitchenState } from "@/services/kitchenAssistant";
import { secondsLeft } from "./domain";
import { formatCountdown, kitchenTimers } from "./timers";

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
  const timers = kitchenTimers(state, now);
  const recipeIds = [...new Set(timers.map((timer) => timer.recipeId))];
  return (
    <div className="kitchen-timers" aria-label="全部菜品计时器">
      {recipeIds.map((recipeId) => (
        <section className="kitchen-timer-group" key={recipeId} aria-label={`${timers.find((timer) => timer.recipeId === recipeId)!.recipeName}倒计时`}>
          <h3>{timers.find((timer) => timer.recipeId === recipeId)!.recipeName}</h3>
          {timers.filter((timer) => timer.recipeId === recipeId).map(({ id, paused, remaining, name, stepName }) => {
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
              <div key={id} className={`kitchen-timer-item${remaining === 0 ? " is-finished" : ""}`}>
                <div className="kitchen-timer-heading"><span>{stepName}</span><span className="kitchen-timer-state">{remaining === 0 ? "请查看火候" : paused ? "已暂停" : "计时中"}</span></div>
                <strong role={remaining === 0 ? "status" : "timer"} aria-label={`${name}剩余时间`}>
                  {remaining === 0
                    ? "计时结束"
                    : formatCountdown(remaining)}
                </strong>
                <div className="kitchen-timer-controls">
                  <Button
                    disabled={busy || remaining === 0}
                    aria-label={`${name}${paused ? "继续计时" : "暂停计时"}`}
                    onClick={() => update(paused ? "resume" : "pause")}
                  >
                    {paused ? "继续" : "暂停"}
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
              </div>
            );
          })}
        </section>
      ))}
    </div>
  );
}
