import type { KitchenState } from "@/services/kitchenAssistant";
import { cookingRecipes, secondsLeft } from "./domain";

export function kitchenTimers(state: KitchenState, now: number) {
  const cooking = state.cooking;
  if (!cooking) return [];
  const recipes = cookingRecipes(state);
  return [...new Set([
    ...Object.keys(cooking.timers),
    ...Object.keys(cooking.pausedTimers ?? {}),
  ])].map((id) => {
    const meta = cooking.timerMeta?.[id];
    const recipeId = meta?.recipeId ?? id;
    const recipe = recipes.find((item) => item.id === recipeId);
    const step = recipe?.steps.find((item) => item.id === meta?.stepId);
    const paused = cooking.pausedTimers?.[id] !== undefined;
    const remaining = cooking.pausedTimers?.[id] ?? secondsLeft(cooking.timers[id], now);
    const recipeName = recipe?.name ?? "菜品";
    return { id, recipeId, recipeName, stepName: step?.title ?? "菜品计时", paused, remaining,
      name: `${recipeName}${meta ? ` · ${step?.title ?? "步骤"}` : ""}` };
  });
}

export function formatCountdown(seconds: number) {
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}
