import type {
  CookingRecord,
  Inventory,
  KitchenState,
  Meal,
  MealSettings,
  MenuDay,
  Preferences,
  Recipe,
} from "@/services/kitchenAssistant";
import { localDate } from "@/services/ideasTodos";
export { localDate };
export const meals: Meal[] = ["breakfast", "lunch", "dinner"];
export const mealLabels = { breakfast: "早餐", lunch: "午餐", dinner: "晚餐" };
export const defaultPreferences: Preferences = {
  servings: 2,
  avoid: [],
  dislike: [],
  spicy: 1,
  equipment: ["炒锅", "汤锅", "蒸锅", "电饭煲", "平底锅"],
  maxMinutes: 60,
};
export const mealSettings = (
  day: MenuDay,
  meal: Meal,
  servings = 2,
): MealSettings =>
  day.settings?.[meal] ?? {
    servings,
    locked: false,
    skipped: false,
    count: meal === "breakfast" ? 1 : 2,
  };
export const amountText = (amount: number) =>
  Number(amount.toFixed(2)).toLocaleString("zh-CN");
const round = (n: number) => Number(n.toFixed(6));
export function normalizedUnit(unit: string): { unit: string; factor: number } {
  return (
    (
      {
        千克: { unit: "克", factor: 1000 },
        克: { unit: "克", factor: 1 },
        升: { unit: "毫升", factor: 1000 },
        毫升: { unit: "毫升", factor: 1 },
      } as Record<string, { unit: string; factor: number }>
    )[unit] ?? { unit, factor: 1 }
  );
}
export interface ShoppingItem {
  key: string;
  name: string;
  amount: number;
  unit: string;
  type: string;
  sources: string[];
}
export function shoppingList(
  recipes: Recipe[],
  servings: number,
): ShoppingItem[] {
  const merged = new Map<string, ShoppingItem>();
  for (const recipe of recipes)
    for (const ingredient of recipe.ingredients) {
      const { unit, factor } = normalizedUnit(ingredient.unit);
      const key = JSON.stringify([ingredient.name, unit]);
      const item = merged.get(key) ?? {
        key,
        name: ingredient.name,
        unit,
        type: ingredient.type,
        amount: 0,
        sources: [],
      };
      item.amount = round(
        item.amount + (ingredient.amount * factor * servings) / recipe.servings,
      );
      if (!item.sources.includes(recipe.name)) item.sources.push(recipe.name);
      merged.set(key, item);
    }
  const order = ["main", "side", "seasoning"];
  return [...merged.values()].sort(
    (a, b) =>
      order.indexOf(a.type) - order.indexOf(b.type) ||
      a.name.localeCompare(b.name, "zh-CN"),
  );
}
export function expiryStatus(
  date: string | null,
  today = localDate(),
): "unknown" | "normal" | "soon" | "expired" {
  if (!date) return "unknown";
  const days = Math.round(
    (Date.parse(`${date}T00:00:00Z`) - Date.parse(`${today}T00:00:00Z`)) /
      86400000,
  );
  return days < 0 ? "expired" : days <= 3 ? "soon" : "normal";
}
export interface PurchaseItem extends ShoppingItem {
  available: number;
  missing: number;
}
function allocate(
  items: ShoppingItem[],
  inventory: Inventory[],
  date: string,
): PurchaseItem[] {
  return items.map((item) => {
    let remaining = item.amount;
    const batches = inventory
      .filter(
        (i) =>
          i.name === item.name &&
          normalizedUnit(i.unit).unit === item.unit &&
          expiryStatus(i.expireDate, date) !== "expired",
      )
      .sort((a, b) =>
        (a.expireDate ?? "9999").localeCompare(b.expireDate ?? "9999"),
      );
    for (const batch of batches) {
      const factor = normalizedUnit(batch.unit).factor;
      const used = Math.min(batch.amount * factor, remaining);
      batch.amount = round(batch.amount - used / factor);
      remaining = round(remaining - used);
    }
    return {
      ...item,
      available: round(item.amount - remaining),
      missing: remaining,
    };
  });
}
export function purchaseList(
  recipes: Recipe[],
  servings: number,
  inventory: Inventory[],
  today = localDate(),
): PurchaseItem[] {
  return allocate(
    shoppingList(recipes, servings),
    inventory.map((i) => ({ ...i })),
    today,
  ).map((item) => ({
    ...item,
    available: round(
      inventory
        .filter(
          (batch) =>
            batch.name === item.name &&
            normalizedUnit(batch.unit).unit === item.unit &&
            expiryStatus(batch.expireDate, today) !== "expired",
        )
        .reduce(
          (sum, batch) =>
            sum + batch.amount * normalizedUnit(batch.unit).factor,
          0,
        ),
    ),
  }));
}
export function menuPurchaseList(
  state: KitchenState,
  start: string,
  end: string,
): PurchaseItem[] {
  const inventory = state.inventory.map((i) => ({ ...i }));
  const merged = new Map<string, PurchaseItem>();
  for (const day of [...state.weeklyMenu].sort((a, b) =>
    a.date.localeCompare(b.date),
  )) {
    if (day.date < start || day.date > end) continue;
    for (const meal of meals) {
      const settings = mealSettings(day, meal, state.servings);
      if (settings.skipped) continue;
      const recipes = (day[meal] ?? []).flatMap(
        (id) => state.recipes.find((r) => r.id === id) ?? [],
      );
      for (const row of allocate(
        shoppingList(recipes, settings.servings),
        inventory,
        day.date,
      )) {
        const old = merged.get(row.key);
        merged.set(
          row.key,
          old
            ? {
                ...old,
                amount: round(old.amount + row.amount),
                available: round(old.available + row.available),
                missing: round(old.missing + row.missing),
                sources: [...new Set([...old.sources, ...row.sources])],
              }
            : row,
        );
      }
    }
  }
  return [...merged.values()].sort(
    (a, b) =>
      a.type.localeCompare(b.type) || a.name.localeCompare(b.name, "zh-CN"),
  );
}
export function conflicts(recipe: Recipe, preferences: Preferences): string[] {
  const reasons: string[] = [];
  for (const name of preferences.avoid)
    if (recipe.ingredients.some((i) => i.name.includes(name)))
      reasons.push(`含避免食材：${name}`);
  if (recipe.durationMinutes > preferences.maxMinutes)
    reasons.push("超过单道菜用时上限");
  if ((recipe.spicy ?? 0) > preferences.spicy) reasons.push("超过辣度偏好");
  if (recipe.equipment?.some((e) => !preferences.equipment.includes(e)))
    reasons.push("缺少所需厨具");
  return reasons;
}
export function recommendationReasons(
  recipe: Recipe,
  state: KitchenState,
): string[] {
  const rows = purchaseList([recipe], state.servings, state.inventory);
  const reasons: string[] = [];
  if (rows.every((i) => i.missing === 0)) reasons.push("库存较齐");
  if (
    state.inventory.some(
      (i) =>
        i.amount > 0 &&
        expiryStatus(i.expireDate) === "soon" &&
        recipe.ingredients.some(
          (r) =>
            r.name === i.name &&
            normalizedUnit(r.unit).unit === normalizedUnit(i.unit).unit,
        ),
    )
  )
    reasons.push("优先消耗");
  if (
    !state.records.slice(0, 3).some((r) => r.recipeNames.includes(recipe.name))
  )
    reasons.push("近期少做");
  if (recipe.favorite) reasons.push("已收藏");
  return reasons;
}
export function recommend(
  recipes: Recipe[],
  inventory: Inventory[],
  today = localDate(),
  servings = 2,
  records: CookingRecord[] = [],
  maxMinutes = 1440,
  preferences?: Preferences,
  limit = 3,
): Recipe[] {
  const recent = new Set(records.slice(0, 3).flatMap((r) => r.recipeNames));
  const score = (recipe: Recipe) => {
    const rows = purchaseList([recipe], servings, inventory, today);
    return (
      rows.reduce(
        (sum, item) =>
          sum +
          ((item.type === "main" ? 3 : 1) *
            Math.min(item.available, item.amount)) /
            Math.max(item.amount, 0.000001),
        0,
      ) /
        Math.max(rows.length, 1) +
      (inventory.some(
        (i) =>
          i.amount > 0 &&
          expiryStatus(i.expireDate, today) === "soon" &&
          recipe.ingredients.some(
            (r) =>
              r.name === i.name &&
              normalizedUnit(r.unit).unit === normalizedUnit(i.unit).unit,
          ),
      )
        ? 1
        : 0) +
      (recipe.favorite ? 0.4 : 0) -
      (recent.has(recipe.name) ? 0.5 : 0) -
      (preferences?.dislike.filter((n) =>
        recipe.ingredients.some((i) => i.name.includes(n)),
      ).length ?? 0)
    );
  };
  return recipes
    .filter(
      (r) =>
        r.durationMinutes <= maxMinutes &&
        (!preferences || !conflicts(r, preferences).length),
    )
    .sort(
      (a, b) =>
        score(b) - score(a) ||
        a.durationMinutes - b.durationMinutes ||
        a.id.localeCompare(b.id),
    )
    .slice(0, limit);
}
export function generateMenu(
  state: KitchenState,
  startDate = localDate(),
): { menu: MenuDay[]; warnings: string[] } {
  const preferences = state.preferences ?? defaultPreferences;
  const used = new Map<string, number>();
  const warnings: string[] = [];
  const menu: MenuDay[] = Array.from({ length: 7 }, (_, index) => {
    const date = new Date(`${startDate}T12:00:00`);
    date.setDate(date.getDate() + index);
    const key = localDate(date);
    const existing = state.weeklyMenu.find((d) => d.date === key);
    return existing
      ? structuredClone(existing)
      : { date: key, breakfast: [], lunch: [], dinner: [], settings: {} };
  });
  for (const day of menu)
    for (const meal of meals)
      if (
        mealSettings(day, meal, preferences.servings).locked &&
        !mealSettings(day, meal, preferences.servings).skipped
      )
        for (const id of day[meal] ?? []) used.set(id, (used.get(id) ?? 0) + 1);
  for (const day of menu)
    for (const meal of meals) {
      const settings = mealSettings(day, meal, preferences.servings);
      day.settings = { ...day.settings, [meal]: settings };
      if (settings.locked || settings.skipped) continue;
      const marker = { breakfast: "早", lunch: "中", dinner: "晚" }[meal];
      const candidates = recommend(
        state.recipes.filter((r) =>
          r.mealTimes.some((t) => t.includes(marker) || t === meal),
        ),
        state.inventory,
        day.date,
        settings.servings,
        state.records,
        preferences.maxMinutes,
        preferences,
        500,
      );
      candidates.sort((a, b) => (used.get(a.id) ?? 0) - (used.get(b.id) ?? 0));
      day[meal] = candidates.slice(0, settings.count).map((r) => r.id);
      if (day[meal]!.length < settings.count)
        warnings.push(
          `${day.date}${mealLabels[meal]}：符合条件的菜谱不足，已保留可用菜品。`,
        );
      for (const id of day[meal]!) {
        if (used.has(id))
          warnings.push(
            `${day.date}${mealLabels[meal]}：${state.recipes.find((r) => r.id === id)?.name}本周重复安排。`,
          );
        used.set(id, (used.get(id) ?? 0) + 1);
      }
    }
  return { menu, warnings };
}
export interface Purchase {
  id: string;
  name: string;
  unit: string;
  amount: number;
  expireDate: string | null;
}
export function receivePurchases(
  state: KitchenState,
  purchases: Purchase[],
): KitchenState {
  return {
    ...state,
    inventory: [
      ...purchases
        .filter((p) => p.amount > 0)
        .map((p) => ({ ...p, category: "采购入库", location: "常温" })),
      ...state.inventory,
    ],
    checkedShoppingItems: [],
  };
}
export const cookingRecipes = (state: KitchenState) =>
  state.cooking?.recipeSnapshots ??
  state.recipes.filter((r) => state.cooking?.recipeIds.includes(r.id));
export function deductionPreview(state: KitchenState, today = localDate()) {
  const after = deductInventory(
    state.inventory,
    cookingRecipes(state),
    state.cooking?.servings ?? state.servings,
    today,
  );
  return state.inventory
    .map((item, i) => ({
      ...item,
      used: round(item.amount - after[i].amount),
      remaining: after[i].amount,
    }))
    .filter((item) => item.used > 0);
}
export function startCooking(
  state: KitchenState,
  now = new Date(),
): KitchenState {
  if (state.cooking || !state.selectedRecipeIds.length) return state;
  return {
    ...state,
    cooking: {
      startedAt: now.toISOString(),
      recipeIds: [...state.selectedRecipeIds],
      currentId: state.selectedRecipeIds[0],
      steps: Object.fromEntries(state.selectedRecipeIds.map((id) => [id, 0])),
      completedIds: [],
      timers: {},
      timerMeta: {},
      recipeSnapshots: structuredClone(
        state.recipes.filter((r) => state.selectedRecipeIds.includes(r.id)),
      ),
      servings: state.servings,
      prepared: [],
    },
  };
}
export function deductInventory(
  inventory: Inventory[],
  recipes: Recipe[],
  servings: number,
  today = localDate(),
): Inventory[] {
  const result = inventory.map((item) => ({ ...item }));
  allocate(shoppingList(recipes, servings), result, today);
  return result;
}
export function finishCooking(
  state: KitchenState,
  deduct: boolean,
  now = new Date(),
): KitchenState {
  if (!state.cooking) return state;
  const recipes = cookingRecipes(state);
  const servings = state.cooking.servings ?? state.servings;
  return {
    ...state,
    inventory: deduct
      ? deductInventory(state.inventory, recipes, servings)
      : state.inventory,
    records: [
      {
        id: crypto.randomUUID(),
        recipeNames: recipes.map((r) => r.name),
        recipeSnapshots: structuredClone(recipes),
        startedAt: state.cooking.startedAt,
        finishedAt: now.toISOString(),
        servings,
        rating: 0,
        tasteNotes: "",
        healthSummary: "",
      },
      ...state.records,
    ],
    cooking: null,
    selectedRecipeIds: [],
    checkedShoppingItems: [],
  };
}
export function repeatCooking(
  state: KitchenState,
  record: CookingRecord,
): KitchenState {
  if (state.cooking) return state;
  const originals =
    record.recipeSnapshots ??
    record.recipeNames.flatMap(
      (name) => state.recipes.find((r) => r.name === name) ?? [],
    );
  const missing = originals.filter(
    (r) => !state.recipes.some((s) => s.id === r.id),
  );
  return {
    ...state,
    recipes: [...state.recipes, ...structuredClone(missing)],
    selectedRecipeIds: originals.map((r) => r.id),
    servings: record.servings,
    checkedShoppingItems: [],
  };
}
export function weeklyMenu(
  recipes: Recipe[],
  startDate = localDate(),
): MenuDay[] {
  if (!recipes.length) return [];
  return Array.from({ length: 7 }, (_, day) => {
    const date = new Date(`${startDate}T12:00:00`);
    date.setDate(date.getDate() + day);
    const lunch = [recipes[day % recipes.length].id];
    const dinner =
      recipes.length > 1
        ? [recipes[(day + 1) % recipes.length].id]
        : [...lunch];
    if (recipes.length > 2 && day % 2 === 0)
      dinner.push(recipes[(day + 2) % recipes.length].id);
    return { date: localDate(date), lunch, dinner };
  });
}
export function weekRecipes(menu: MenuDay[], recipes: Recipe[]): Recipe[] {
  return menu
    .flatMap((day) =>
      meals.flatMap((meal) =>
        mealSettings(day, meal).skipped ? [] : (day[meal] ?? []),
      ),
    )
    .flatMap((id) => recipes.find((r) => r.id === id) ?? []);
}
export const secondsLeft = (deadline: number, now = Date.now()) =>
  Math.max(0, Math.ceil((deadline - now) / 1000));
