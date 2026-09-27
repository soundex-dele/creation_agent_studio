import { api } from "./api";

export interface Ingredient {
  id: string;
  name: string;
  amount: number;
  unit: string;
  type: "main" | "side" | "seasoning";
}
export interface CookingStep {
  id: string;
  title: string;
  description: string;
  phase: "prep" | "cook" | "finish";
  durationMinutes: number;
  heatLevel: string;
  ingredientIds: string[];
  mediaUrls: string[];
}
export interface Recipe {
  id: string;
  name: string;
  category: string;
  intro: string;
  difficulty: string;
  servings: number;
  durationMinutes: number;
  mealTimes: string[];
  ingredients: Ingredient[];
  steps: CookingStep[];
  tips: string[];
  source: string;
  createdAt: string;
  updatedAt: string;
  favorite?: boolean;
  tags?: string[];
  equipment?: string[];
  spicy?: number;
  catalogId?: string;
}
export interface Inventory {
  id: string;
  name: string;
  amount: number;
  unit: string;
  category: string;
  expireDate: string | null;
  location?: string;
}
export interface CookingRecord {
  id: string;
  recipeNames: string[];
  startedAt: string;
  finishedAt: string;
  servings: number;
  rating: number;
  tasteNotes: string;
  healthSummary: string;
  revision?: number;
  recipeSnapshots?: Recipe[];
}
export interface Cooking {
  startedAt: string;
  recipeIds: string[];
  currentId: string;
  steps: Record<string, number>;
  completedIds: string[];
  timers: Record<string, number>;
  pausedTimers?: Record<string, number>;
  timerMeta?: Record<string, { recipeId: string; stepId: string }>;
  recipeSnapshots?: Recipe[];
  servings?: number;
  prepared?: string[];
}
export type Meal = "breakfast" | "lunch" | "dinner";
export interface MealSettings {
  servings: number;
  locked: boolean;
  skipped: boolean;
  count: number;
}
export interface MenuDay {
  date: string;
  breakfast?: string[];
  lunch: string[];
  dinner: string[];
  settings?: Partial<Record<Meal, MealSettings>>;
}
export interface Preferences {
  servings: number;
  avoid: string[];
  dislike: string[];
  spicy: number;
  equipment: string[];
  maxMinutes: number;
}
export interface ManualPurchase {
  id: string;
  name: string;
  amount: number;
  unit: string;
  type: string;
}
export interface ShoppingScope {
  checked: string[];
  manual: ManualPurchase[];
}
export interface KitchenState {
  recipes: Recipe[];
  inventory: Inventory[];
  records: CookingRecord[];
  selectedRecipeIds: string[];
  checkedShoppingItems: string[];
  servings: number;
  cooking: Cooking | null;
  weeklyMenu: MenuDay[];
  schemaVersion?: number;
  preferences?: Preferences;
  shoppingScopes?: Record<string, ShoppingScope>;
}
export interface KitchenSnapshot {
  revision: number;
  data: KitchenState;
  recordCount?: number;
}
export interface KitchenPatch {
  aiTaskId?: string;
  schemaVersion?: number;
  revision: number;
  operationId: string;
  changes: Partial<Omit<KitchenState, "records">>;
  appendRecords: CookingRecord[];
}
export interface RecordPage {
  count: number;
  results: CookingRecord[];
}
export interface AITask {
  id: string;
  kind: "recipe" | "menu" | "question";
  instruction: string;
  status: string;
  revision: number;
  result: {
    recipe?: Recipe;
    missing?: string[];
    menu?: MenuDay[];
    answer?: string;
  };
  error: string;
  recipeId?: string;
  parentId?: string;
}
export const kitchenApi = (base: string) => ({
  load: (signal?: AbortSignal) =>
    api.get<KitchenSnapshot>(`${base}/state`, undefined, { signal }),
  save: (patch: KitchenPatch) =>
    api.patch<KitchenSnapshot>(`${base}/state`, patch),
  history: (
    page: number,
    signal?: AbortSignal,
    filters: { search?: string; start?: string; end?: string } = {},
  ) => api.get<RecordPage>(`${base}/records`, { page, ...filters }, { signal }),
  catalog: () => api.get<Recipe[]>(`${base}/catalog`),
  tasks: () => api.get<AITask[]>(`${base}/ai/tasks`),
  task: (id: string) => api.get<AITask>(`${base}/ai/tasks/${id}`),
  createTask: (input: {
    kind: AITask["kind"];
    instruction: string;
    revision: number;
    requestKey: string;
    recipeId?: string;
    parentId?: string;
    startDate?: string;
  }) => api.post<AITask>(`${base}/ai/tasks`, input),
  cancelTask: (id: string) =>
    api.post<AITask>(`${base}/ai/tasks/${id}/cancel`, {}),
  editRecord: (record: CookingRecord) =>
    api.patch<CookingRecord>(
      `${base}/records/${encodeURIComponent(record.id)}`,
      {
        revision: record.revision ?? 0,
        rating: record.rating,
        tasteNotes: record.tasteNotes,
      },
    ),
  deleteRecord: (record: CookingRecord) =>
    api.delete(
      `${base}/records/${encodeURIComponent(record.id)}?revision=${record.revision ?? 0}`,
    ),
});
export function statePatch(
  before: KitchenSnapshot,
  after: KitchenState,
  operationId = crypto.randomUUID(),
): KitchenPatch {
  const changes: Partial<Omit<KitchenState, "records">> = {};
  for (const key of Object.keys(after) as (keyof KitchenState)[]) {
    if (
      key !== "records" &&
      JSON.stringify(before.data[key]) !== JSON.stringify(after[key])
    )
      Object.assign(changes, { [key]: after[key] });
  }
  if (changes.selectedRecipeIds || changes.servings || changes.weeklyMenu) {
    const scopes = after.shoppingScopes ?? {};
    changes.shoppingScopes = Object.fromEntries(
      Object.entries(scopes).map(([key, scope]) => [
        key,
        (key === "meal" && (changes.selectedRecipeIds || changes.servings)) ||
        (key.startsWith("range:") && changes.weeklyMenu)
          ? { ...scope, checked: [] }
          : scope,
      ]),
    );
    if (
      JSON.stringify(changes.shoppingScopes) ===
      JSON.stringify(before.data.shoppingScopes ?? {})
    )
      delete changes.shoppingScopes;
  }
  return {
    schemaVersion: 2,
    revision: before.revision,
    operationId,
    changes,
    appendRecords: after.records.filter(
      (r) => !before.data.records.some((old) => old.id === r.id),
    ),
  };
}
