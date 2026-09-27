import { describe, expect, it } from "vitest";
import recipes from "../../../../../backend/app_center/kitchen_assistant/assets/recipes.json";
import type {
  Inventory,
  KitchenState,
  Recipe,
} from "@/services/kitchenAssistant";
import {
  deductionPreview,
  purchaseList,
  receivePurchases,
  weekRecipes,
  deductInventory,
  expiryStatus,
  finishCooking,
  recommend,
  secondsLeft,
  shoppingList,
  startCooking,
  weeklyMenu,
} from "../kitchen/domain";
const menu = recipes as Recipe[];
const initial = (): KitchenState => ({
  recipes: menu,
  inventory: [],
  records: [],
  servings: 2,
  cooking: null,
  selectedRecipeIds: [menu[0].id, menu[1].id],
  checkedShoppingItems: [],
  weeklyMenu: [],
});

describe("kitchen meal workflow", () => {
  it("merges names and units, scales servings, and preserves sources", () => {
    const list = shoppingList(menu.slice(0, 2), 4);
    expect(list.find((i) => i.name === "生抽")).toMatchObject({
      amount: 4,
      unit: "勺",
      sources: ["番茄炒蛋", "清炒上海青"],
    });
    const variant = {
      ...menu[0],
      ingredients: [
        { ...menu[0].ingredients[0], name: "生抽", unit: "克", amount: 3 },
      ],
    };
    expect(
      shoppingList([menu[0], variant], 2).filter((i) => i.name === "生抽"),
    ).toHaveLength(2);
  });
  it("deducts matching units across batches in expiry order without using expired stock", () => {
    const inventory: Inventory[] = [
      {
        id: "later",
        name: "番茄",
        unit: "个",
        amount: 3,
        category: "蔬菜",
        expireDate: "2026-09-30",
      },
      {
        id: "soon",
        name: "番茄",
        unit: "个",
        amount: 1,
        category: "蔬菜",
        expireDate: "2026-09-27",
      },
      {
        id: "expired",
        name: "番茄",
        unit: "个",
        amount: 4,
        category: "蔬菜",
        expireDate: "2026-09-26",
      },
      {
        id: "other-unit",
        name: "番茄",
        unit: "克",
        amount: 500,
        category: "蔬菜",
        expireDate: null,
      },
    ];
    expect(
      deductInventory(inventory, [menu[0]], 2, "2026-09-27").map(
        (i) => i.amount,
      ),
    ).toEqual([2, 0, 4, 500]);
    expect(inventory[0].amount).toBe(3);
    expect(
      deductInventory(inventory, [menu[0]], 8, "2026-09-27").map(
        (i) => i.amount,
      ),
    ).toEqual([0, 0, 4, 500]);
  });
  it("records actual start time, clears plan and can skip inventory deductions", () => {
    const start = new Date("2026-09-27T10:00:00Z");
    const cooking = startCooking(initial(), start);
    expect(cooking.cooking?.steps).toEqual({ r1: 0, r2: 0 });
    const completed = finishCooking(
      cooking,
      false,
      new Date("2026-09-27T10:20:00Z"),
    );
    expect(completed.records[0]).toMatchObject({
      startedAt: start.toISOString(),
      recipeNames: ["番茄炒蛋", "清炒上海青"],
      rating: 0,
    });
    expect(completed.selectedRecipeIds).toEqual([]);
    expect(completed.cooking).toBeNull();
    expect(finishCooking(completed, false).records).toHaveLength(1);
  });
  it("uses calendar dates for expiration and restores elapsed timers", () => {
    expect(expiryStatus("2026-09-27", "2026-09-27")).toBe("soon");
    expect(expiryStatus("2026-09-30", "2026-09-27")).toBe("soon");
    expect(expiryStatus("2026-10-01", "2026-09-27")).toBe("normal");
    expect(expiryStatus("2026-09-26", "2026-09-27")).toBe("expired");
    expect(secondsLeft(61000, 30000)).toBe(31);
    expect(secondsLeft(61000, 70000)).toBe(0);
  });
  it("prioritizes usable soon-expiring stock and handles empty menus", () => {
    const recommended = recommend(
      menu,
      [
        {
          id: "a",
          name: "上海青",
          amount: 300,
          unit: "克",
          category: "青菜",
          expireDate: "2026-09-28",
        },
      ],
      "2026-09-27",
    );
    expect(recommended[0].name).toBe("清炒上海青");
    expect(weeklyMenu(menu)).toHaveLength(7);
    expect(weeklyMenu([])).toEqual([]);
    expect(weeklyMenu(menu.slice(0, 1))[0].dinner).toHaveLength(1);
  });
});
it("subtracts only usable matching inventory and previews batch deductions", () => {
  const state = startCooking(initial());
  state.inventory = [
    {
      id: "a",
      name: "番茄",
      amount: 1,
      unit: "个",
      expireDate: null,
      category: "蔬果",
    },
    {
      id: "b",
      name: "番茄",
      amount: 100,
      unit: "克",
      expireDate: null,
      category: "蔬果",
    },
    {
      id: "c",
      name: "番茄",
      amount: 9,
      unit: "个",
      expireDate: "2020-01-01",
      category: "蔬果",
    },
  ];
  expect(expiryStatus(null)).toBe("unknown");
  expect(
    purchaseList([menu[0]], 2, state.inventory).find((i) => i.name === "番茄"),
  ).toMatchObject({ amount: 2, available: 1, missing: 1 });
  expect(deductionPreview(state)).toEqual([
    expect.objectContaining({ id: "a", used: 1, remaining: 0 }),
  ]);
  const received = receivePurchases(state, [
    { id: "new", name: "番茄", amount: 1, unit: "个", expireDate: null },
  ]);
  expect(received.inventory).toHaveLength(4);
  expect(
    purchaseList([menu[0]], 2, received.inventory).find(
      (i) => i.name === "番茄",
    )?.missing,
  ).toBe(0);
});
it("counts repeated meals in weekly purchasing and handles month boundaries", () => {
  const days = weeklyMenu(menu, "2026-09-28");
  expect(days[6].date).toBe("2026-10-04");
  const repeated = [{ date: "2026-09-28", lunch: ["r1"], dinner: ["r1"] }];
  expect(
    shoppingList(weekRecipes(repeated, menu), 2).find((i) => i.name === "番茄")
      ?.amount,
  ).toBe(4);
});
it("checks quantities, unit compatibility, recent meals and cooking time for recommendations", () => {
  const tomato = menu[0];
  const other = { ...tomato, id: "alternative", name: "另一道菜" };
  const records = [
    {
      id: "r",
      recipeNames: [tomato.name],
      startedAt: "",
      finishedAt: "",
      servings: 2,
      rating: 0,
      tasteNotes: "",
      healthSummary: "",
    },
  ];
  expect(recommend([tomato, other], [], "2026-09-27", 2, records)[0].id).toBe(
    "alternative",
  );
  expect(
    recommend(menu, [], "2026-09-27", 2, [], 10).every(
      (r) => r.durationMinutes <= 10,
    ),
  ).toBe(true);
  const stock: Inventory[] = [
    {
      id: "a",
      name: "番茄",
      amount: 1,
      unit: "克",
      expireDate: null,
      category: "蔬菜",
    },
  ];
  expect(recommend([tomato, other], stock).map((r) => r.id)).toEqual(
    recommend([tomato, other], []).map((r) => r.id),
  );
});

// v2 behavior: constraints, date-based allocations, snapshots and safe repeat.
import {
  defaultPreferences,
  generateMenu,
  menuPurchaseList,
  repeatCooking,
} from "../kitchen/domain";
it("allocates stock once across dates using each meal serving count and expiry", () => {
  const state = initial();
  const recipe = {
    ...menu[0],
    ingredients: [
      { id: "i", name: "大米", amount: 500, unit: "克", type: "main" as const },
    ],
  };
  state.recipes = [recipe];
  state.inventory = [
    {
      id: "batch",
      name: "大米",
      amount: 1,
      unit: "千克",
      category: "主食",
      expireDate: "2026-10-01",
    },
    {
      id: "unknown",
      name: "大米",
      amount: 100,
      unit: "克",
      category: "主食",
      expireDate: null,
    },
  ];
  state.weeklyMenu = [
    {
      date: "2026-10-01",
      breakfast: [recipe.id],
      lunch: [recipe.id],
      dinner: [],
      settings: {
        breakfast: { servings: 1, count: 1, locked: false, skipped: false },
        lunch: { servings: 2, count: 1, locked: false, skipped: false },
      },
    },
    {
      date: "2026-10-02",
      lunch: [recipe.id],
      dinner: [recipe.id],
      settings: {
        dinner: { servings: 2, count: 1, locked: false, skipped: true },
      },
    },
  ];
  expect(menuPurchaseList(state, "2026-10-01", "2026-10-02")[0]).toMatchObject({
    amount: 1250,
    available: 850,
    missing: 400,
    unit: "克",
  });
  expect(state.inventory[0].amount).toBe(1);
});
it("converts only mass and volume and keeps count units separate", () => {
  const r = {
    ...menu[0],
    ingredients: [
      { id: "i", name: "牛奶", amount: 0.5, unit: "升", type: "main" as const },
    ],
  };
  const stock: Inventory[] = [
    {
      id: "a",
      name: "牛奶",
      unit: "毫升",
      amount: 300,
      category: "奶",
      expireDate: null,
    },
    {
      id: "b",
      name: "牛奶",
      unit: "杯",
      amount: 2,
      category: "奶",
      expireDate: null,
    },
  ];
  expect(purchaseList([r], 2, stock)[0]).toMatchObject({
    unit: "毫升",
    amount: 500,
    missing: 200,
  });
  expect(deductInventory(stock, [r], 2).map((i) => i.amount)).toEqual([0, 2]);
});
it("preserves locked and skipped meals without relaxing hard restrictions", () => {
  const state = initial();
  state.preferences = {
    ...defaultPreferences,
    avoid: ["鸡蛋"],
    equipment: [],
    maxMinutes: 10,
  };
  state.weeklyMenu = [
    {
      date: "2026-10-01",
      breakfast: ["r1"],
      lunch: ["r1"],
      dinner: ["r3"],
      settings: {
        breakfast: { servings: 3, count: 1, locked: true, skipped: false },
        dinner: { servings: 2, count: 2, locked: false, skipped: true },
      },
    },
  ];
  const result = generateMenu(state, "2026-10-01");
  expect(result.menu[0].breakfast).toEqual(["r1"]);
  expect(result.menu[0].settings?.breakfast?.servings).toBe(3);
  expect(result.menu[0].dinner).toEqual(["r3"]);
  expect(result.menu[0].lunch).toEqual(["r2"]);
  expect(result.warnings.length).toBeGreaterThan(0);
  expect(result.menu[1].breakfast).toEqual([]);
});
it("retains snapshots when a recipe changes and restores deleted recipes on repeat", () => {
  const state = startCooking(initial());
  const frozen = structuredClone(state.cooking!.recipeSnapshots);
  state.recipes = state.recipes.map((r) => ({ ...r, name: "changed" }));
  state.servings = 8;
  const finished = finishCooking(state, false);
  expect(finished.records[0].recipeSnapshots).toEqual(frozen);
  expect(finished.records[0].servings).toBe(2);
  finished.recipes = [];
  const repeated = repeatCooking(finished, finished.records[0]);
  expect(repeated.recipes).toHaveLength(2);
  expect(repeated.selectedRecipeIds).toEqual(["r1", "r2"]);
  expect(repeatCooking(repeated, finished.records[0]).recipes).toHaveLength(2);
});
it("excludes missing equipment and excess spice, and lowers disliked ingredients", () => {
  const r = menu[0];
  const allowed = { ...r, id: "allowed", name: "替代" };
  const spicy = { ...r, id: "spicy", spicy: 3 };
  const oven = { ...r, id: "oven", equipment: ["烤箱"] };
  expect(
    recommend(
      [allowed, spicy, oven],
      [],
      undefined,
      2,
      [],
      60,
      defaultPreferences,
      500,
    ).map((r) => r.id),
  ).toEqual(["allowed"]);
});
