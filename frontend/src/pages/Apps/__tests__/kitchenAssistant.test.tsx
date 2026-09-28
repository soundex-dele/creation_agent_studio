// @vitest-environment jsdom
import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { ConfigProvider } from "antd";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "@/services/api";
import type {
  KitchenPatch,
  KitchenSnapshot,
  Recipe,
} from "@/services/kitchenAssistant";
import recipes from "../../../../../backend/app_center/kitchen_assistant/assets/recipes.json";
import { KitchenWorkspace } from "../KitchenAssistantPage";
import { applicationPath } from "@/lib/applicationCatalog";
vi.mock("@/services/api", () => ({
  api: { get: vi.fn(), patch: vi.fn(), post: vi.fn(), delete: vi.fn() },
}));
let root: Root;
let container: HTMLDivElement;
let snapshot: KitchenSnapshot;
const settle = async () =>
  act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 25));
  });
const click = async (element: HTMLElement) => {
  await act(async () => element.click());
  await settle();
};
const button = (label: string) => {
  const found = [
    ...document.querySelectorAll<HTMLButtonElement>("button"),
  ].find((el) => el.textContent?.replace(/\s/g, "") === label);
  expect(found, label).toBeDefined();
  return found!;
};
const tab = async (prefix: string) =>
  click(
    [...container.querySelectorAll<HTMLElement>('[role="tab"]')].find((el) =>
      el.textContent?.startsWith(prefix),
    )!,
  );
const render = async () => {
  await act(async () =>
    root.render(
      createElement(
        MemoryRouter,
        {},
        createElement(
          ConfigProvider,
          { theme: { token: { motion: false } } },
          createElement(KitchenWorkspace, { base: "/kitchen" }),
        ),
      ),
    ),
  );
  await settle();
};
beforeEach(() => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  // Exercise the whole kitchen workflow under phone/LAN HTTP capabilities.
  vi.stubGlobal('crypto', {
    getRandomValues: globalThis.crypto.getRandomValues.bind(globalThis.crypto),
  });
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({
      matches: false,
      addListener() {},
      removeListener() {},
      addEventListener() {},
      removeEventListener() {},
    })),
  );
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
  const original = window.getComputedStyle.bind(window);
  vi.spyOn(window, "getComputedStyle").mockImplementation((el) => original(el));
  snapshot = {
    revision: 0,
    data: {
      recipes: recipes as Recipe[],
      inventory: [],
      records: [],
      selectedRecipeIds: [],
      checkedShoppingItems: [],
      servings: 2,
      cooking: null,
      weeklyMenu: [],
    },
  };
  vi.mocked(api.get).mockImplementation(async (url) =>
    url.endsWith("/records")
      ? { count: snapshot.data.records.length, results: snapshot.data.records }
      : structuredClone(snapshot),
  );
  vi.mocked(api.patch).mockImplementation(async (_url, value) => {
    const patch = structuredClone(value as KitchenPatch);
    snapshot = {
      ...snapshot,
      data: {
        ...snapshot.data,
        ...patch.changes,
        records: [...patch.appendRecords, ...snapshot.data.records],
      },
      revision: snapshot.revision + 1,
    };
    return snapshot;
  });
  localStorage.clear();
  sessionStorage.clear();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.restoreAllMocks();
  vi.resetAllMocks();
  vi.unstubAllGlobals();
});
it("opens the dedicated application from the catalog", () => {
  expect(
    applicationPath(
      {
        id: "kitchen-assistant",
        applicationId: 42,
        kind: "custom",
        rendererKey: "kitchen-assistant",
      },
      "home",
    ),
  ).toBe("/applications/42/kitchen-assistant?entry=home");
});
it("completes a two-dish meal and saves its history", async () => {
  await render();
  await tab("菜谱");
  await click(button("加入待制作"));
  await click(button("加入待制作"));
  await tab("菜单");
  expect(container.textContent).toContain("采购清单");
  const soy = [...container.querySelectorAll(".kitchen-shopping-item")].find(
    (el) => el.textContent?.includes("生抽"),
  );
  expect(soy?.textContent).toContain("2 勺");
  expect(soy?.textContent).toContain("番茄炒蛋、清炒上海青");
  await click(button("进入制作模式"));
  expect(document.body.textContent).toContain("处理食材");
  await click(button("启动本步计时"));
  expect(Object.values(snapshot.data.cooking!.timers)[0]).toBeGreaterThan(
    Date.now(),
  );
  await click(button("下一步"));
  await click(button("下一步"));
  await click(button("完成这道菜"));
  expect(snapshot.data.cooking?.currentId).toBe("r2");
  await click(button("下一步"));
  await click(button("下一步"));
  await click(button("完成这道菜"));
  await click(button("保存下厨记录"));
  expect(snapshot.data.records).toHaveLength(1);
  expect(snapshot.data.records[0].recipeNames).toEqual([
    "番茄炒蛋",
    "清炒上海青",
  ]);
  expect(snapshot.data.cooking).toBeNull();
  expect(container.textContent).toContain("下厨记录 · 1");
});

it("keeps primary navigation below the scroll pane and opens meal planning from an empty meal", async () => {
  await render();
  const workspace = container.querySelector('.kitchen-workspace')!;
  const page = workspace.querySelector('.kitchen-page')!;
  const navigation = workspace.querySelector('nav[aria-label="厨房助手导航"]')!;
  expect(page.nextElementSibling).toBe(navigation);
  expect(navigation.parentElement).toBe(workspace);
  expect(navigation.querySelectorAll('[role="tab"]')).toHaveLength(5);
  expect(page.contains(navigation)).toBe(false);
  await click(container.querySelector<HTMLButtonElement>('[aria-label="安排早餐"]')!);
  expect(navigation.querySelector('[aria-selected="true"]')?.textContent).toBe('菜单');
  expect(page.textContent).toContain('这一餐的安排');
  await tab('菜谱');
  await click(button('添加菜谱'));
  expect(container.querySelector('.kitchen-bottom-navigation')).toBeNull();
});
it("keeps the saved state when a write conflicts and offers reload", async () => {
  await render();
  vi.mocked(api.patch).mockRejectedValueOnce({
    response: {
      status: 409,
      data: { detail: "数据已在其他页面更新，请刷新后重试。" },
    },
  });
  await click(button("加入待制作"));
  expect(snapshot.data.selectedRecipeIds).toEqual([]);
  expect(container.textContent).toContain("数据已在其他页面更新");
  await click(button("在最新数据上重试"));
  expect(snapshot.data.selectedRecipeIds).toHaveLength(1);
  expect(api.get).toHaveBeenCalledTimes(2);
});
it("adds a recipe from a phone HTTP context without crypto.randomUUID", async () => {
  const getRandomValues = globalThis.crypto.getRandomValues.bind(globalThis.crypto);
  vi.stubGlobal('crypto', { getRandomValues });
  await render();
  await click(button('加入待制作'));
  expect(api.patch).toHaveBeenCalledOnce();
  const patch = vi.mocked(api.patch).mock.calls[0][1] as KitchenPatch;
  expect(patch.operationId).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  expect(snapshot.data.selectedRecipeIds).toHaveLength(1);
  expect(button('已加入·移出清单')).toBeDefined();
  await tab('菜单');
  expect(container.textContent).toContain('待制作 · 1 道');
});
it('shows progress until adding a recipe is actually saved', async () => {
  await render();
  let finishSave!: (snapshot: KitchenSnapshot) => void;
  vi.mocked(api.patch).mockImplementationOnce(() => new Promise(resolve => { finishSave = resolve; }));
  const add = button('加入待制作');
  await click(add);
  expect(add.classList.contains('ant-btn-loading')).toBe(true);
  expect(snapshot.data.selectedRecipeIds).toEqual([]);
  const patch = vi.mocked(api.patch).mock.calls[0][1] as KitchenPatch;
  await act(async () => finishSave({
    revision: 1,
    data: { ...snapshot.data, ...patch.changes },
  }));
  await settle();
  expect(button('已加入·移出清单').classList.contains('ant-btn-loading')).toBe(false);
  expect(document.body.textContent).toContain('已加入待制作，可在底部「菜单」查看');
});
it('reports request preparation failures instead of silently dropping a click', async () => {
  vi.stubGlobal('crypto', undefined);
  await render();
  await click(button('加入待制作'));
  expect(api.patch).not.toHaveBeenCalled();
  expect(snapshot.data.selectedRecipeIds).toEqual([]);
  expect(container.textContent).toContain('当前浏览器无法生成操作标识');
  expect(document.body.textContent).toContain('保存未成功');
});
it("restores saved cooking progress and elapsed timers on mount", async () => {
  snapshot.data.selectedRecipeIds = ["r1"];
  snapshot.data.cooking = {
    startedAt: new Date().toISOString(),
    recipeIds: ["r1"],
    currentId: "r1",
    steps: { r1: 1 },
    completedIds: [],
    timers: { r1: Date.now() - 1000 },
  };
  await render();
  expect(container.textContent).toContain("计时结束");
  await click(button("继续制作"));
  expect(document.body.textContent).toContain("炒鸡蛋");
  expect(button("启动本步计时").disabled).toBe(true);
});
const inputValue = async (selector: string, value: string) => {
  const input = document.querySelector<HTMLInputElement | HTMLTextAreaElement>(
    selector,
  )!;
  expect(input).not.toBeNull();
  await act(async () => {
    const prototype =
      input.tagName === "TEXTAREA"
        ? HTMLTextAreaElement.prototype
        : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(prototype, "value")!.set!.call(
      input,
      value,
    );
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
};
it("adds inventory and a user-edited recipe through validated forms", async () => {
  await render();
  await tab("我的厨房");
  await click(button("添加食材"));
  await inputValue("#name", "土豆");
  await click(button("保存"));
  expect(snapshot.data.inventory[0]).toMatchObject({
    name: "土豆",
    amount: 1,
    unit: "个",
    expireDate: null,
  });
  await tab("菜谱");
  await click(button("添加菜谱"));
  await inputValue("#name", "清炒土豆");
  await inputValue('[aria-label="食材1名称"]', "土豆");
  await inputValue('[aria-label="食材1数量"]', "2");
  await inputValue('[aria-label="步骤1标题"]', "炒熟");
  await inputValue('[aria-label="步骤1做法"]', "土豆切片后炒熟");
  await click(button("保存菜谱"));
  expect(snapshot.data.recipes[0]).toMatchObject({
    name: "清炒土豆",
    source: "手动整理",
  });
  expect(snapshot.data.recipes[0].ingredients[0]).toMatchObject({
    name: "土豆",
    amount: 2,
  });
});
it("retains recipe step references when editing quantities", async () => {
  await render();
  await click(button("番茄炒蛋"));
  await click(button("编辑"));
  const original = snapshot.data.recipes[0];
  await inputValue('[aria-label="食材1数量"]', "3");
  await click(button("保存菜谱"));
  expect(snapshot.data.recipes[0].ingredients[0].amount).toBe(3);
  expect(snapshot.data.recipes[0].steps[1].ingredientIds).toEqual(
    original.steps[1].ingredientIds,
  );
});
it("preserves ingredient identity through deletion, insertion and reordering", async () => {
  await render();
  await click(button("番茄炒蛋"));
  await click(button("编辑"));
  const eggId = snapshot.data.recipes[0].ingredients.find(
    (i) => i.name === "鸡蛋",
  )!.id;
  await click(button("删除食材"));
  await click(button("下移食材"));
  await click(button("添加食材行"));
  await inputValue('[aria-label="食材5名称"]', "白胡椒");
  await click(button("保存菜谱"));
  const result = snapshot.data.recipes[0];
  expect(result.steps.find((s) => s.title === "炒鸡蛋")?.ingredientIds).toEqual(
    [eggId],
  );
  expect(result.ingredients.find((i) => i.id === eggId)?.name).toBe("鸡蛋");
  expect(result.ingredients.some((i) => i.name === "番茄")).toBe(false);
  expect(new Set(result.ingredients.map((i) => i.id)).size).toBe(
    result.ingredients.length,
  );
});
it("preserves step associations when steps are reordered", async () => {
  await render();
  await click(button("番茄炒蛋"));
  await click(button("编辑"));
  const original = snapshot.data.recipes[0].steps[0];
  await click(button("下移步骤"));
  await click(button("保存菜谱"));
  expect(snapshot.data.recipes[0].steps[1]).toEqual(original);
});
it("sends only changed fields and preserves operation identity on a network retry", async () => {
  await render();
  vi.mocked(api.patch).mockRejectedValueOnce(new Error("network"));
  await click(button("加入待制作"));
  const first = vi.mocked(api.patch).mock.calls[0][1] as KitchenPatch;
  expect(Object.keys(first.changes).sort()).toEqual(["selectedRecipeIds"]);
  expect(first.appendRecords).toEqual([]);
  await click(button("重试原操作"));
  const second = vi.mocked(api.patch).mock.calls[1][1] as KitchenPatch;
  expect(second).toEqual(first);
  expect(snapshot.data.selectedRecipeIds).toHaveLength(1);
});
it("receives only the shortage into a new inventory batch", async () => {
  snapshot.data.selectedRecipeIds = ["r1"];
  snapshot.data.inventory = [
    {
      id: "existing",
      name: "番茄",
      amount: 1,
      unit: "个",
      expireDate: null,
      category: "蔬果",
    },
  ];
  await render();
  await tab("菜单");
  const row = [...container.querySelectorAll(".kitchen-shopping-item")].find(
    (el) => el.textContent?.includes("番茄"),
  )!;
  expect(row.textContent).toContain("已有 1 · 还缺 1");
  await click(row.querySelector("input")!);
  await click(button("确认购买并入库（1项）"));
  await inputValue('[aria-label="番茄到期日期"]', "2026-10-02");
  await click(button("确认入库"));
  expect(
    snapshot.data.inventory
      .filter((i) => i.name === "番茄")
      .reduce((sum, i) => sum + i.amount, 0),
  ).toBe(2);
  expect(snapshot.data.inventory[0].expireDate).toBe("2026-10-02");
  expect(snapshot.data.checkedShoppingItems).toEqual([]);
});
it("pauses, extends and resumes a timer without resetting its remaining duration", async () => {
  snapshot.data.selectedRecipeIds = ["r1"];
  snapshot.data.cooking = {
    startedAt: new Date().toISOString(),
    recipeIds: ["r1"],
    currentId: "r1",
    steps: { r1: 0 },
    completedIds: [],
    timers: { r1: Date.now() + 120000 },
  };
  await render();
  await click(container.querySelector('[aria-label="番茄炒蛋暂停计时"]')!);
  const remaining = snapshot.data.cooking!.pausedTimers!.r1;
  expect(remaining).toBeGreaterThan(115);
  expect(snapshot.data.cooking!.timers.r1).toBeUndefined();
  await click(container.querySelector('[aria-label="番茄炒蛋增加一分钟"]')!);
  expect(snapshot.data.cooking!.pausedTimers!.r1).toBe(remaining + 60);
  await click(container.querySelector('[aria-label="番茄炒蛋继续计时"]')!);
  expect(snapshot.data.cooking!.pausedTimers!.r1).toBeUndefined();
  expect(snapshot.data.cooking!.timers.r1).toBeGreaterThan(Date.now() + 170000);
});
it("offers a dated editable weekly plan and an aggregated shopping list", async () => {
  await render();
  await tab("菜单");
  await inputValue('[aria-label="周菜单开始日期"]', "2026-10-01");
  await click(button("生成参考菜单"));
  expect(snapshot.data.weeklyMenu).toHaveLength(0);
  await click(button("应用菜单"));
  expect(snapshot.data.weeklyMenu).toHaveLength(7);
  expect(snapshot.data.weeklyMenu[0].date).toBe("2026-10-01");
  expect(snapshot.data.weeklyMenu[6].date).toBe("2026-10-07");
  expect(container.textContent).toContain("一周采购汇总");
  await click(button("选用午餐"));
  expect(snapshot.data.selectedRecipeIds).toEqual(
    snapshot.data.weeklyMenu[0].lunch,
  );
});
it("imports selected catalog recipes without overwriting existing recipes", async () => {
  const catalog =
    await import("../../../../../backend/app_center/kitchen_assistant/assets/catalog.json");
  vi.mocked(api.get).mockImplementation(async (url) =>
    url.endsWith("/catalog")
      ? catalog.default
      : url.endsWith("/records")
        ? { count: 0, results: [] }
        : structuredClone(snapshot),
  );
  await render();
  await click(button("添加精选菜谱"));
  const choice = [...document.querySelectorAll("label")].find((el) =>
    el.textContent?.includes("燕麦牛奶粥"),
  )!;
  await click(choice.querySelector("input")!);
  await click(button("添加1道"));
  expect(snapshot.data.recipes).toHaveLength(4);
  expect(snapshot.data.recipes[0].name).toBe("番茄炒蛋");
  expect(snapshot.data.recipes[3].catalogId).toBe("kitchen-catalog-01");
});
it("saves household preferences and uses the default meal size", async () => {
  await render();
  await tab("我的厨房");
  await tab("家庭偏好");
  await inputValue('[aria-label="默认人数"]', "4");
  await click(button("保存偏好"));
  expect(snapshot.data.preferences?.servings).toBe(4);
  expect(snapshot.data.servings).toBe(4);
});
it("starts two step timers for the same dish and preserves preparation progress", async () => {
  snapshot.data.selectedRecipeIds = ["r1"];
  await render();
  await tab("菜单");
  await click(button("进入制作模式"));
  const prepared = [
    ...container.querySelectorAll('input[type="checkbox"]'),
  ][0] as HTMLInputElement;
  await click(prepared);
  await click(button("启动本步计时"));
  await click(button("下一步"));
  await click(button("启动本步计时"));
  expect(Object.keys(snapshot.data.cooking!.timers)).toHaveLength(2);
  expect(
    Object.values(snapshot.data.cooking!.timerMeta!).map((t) => t.stepId),
  ).toEqual(["s1", "s2"]);
  expect(snapshot.data.cooking!.prepared).toEqual(["r1:s1"]);
  await click(button("返回厨房"));
  await click(button("继续制作"));
  expect(snapshot.data.cooking!.recipeSnapshots![0].name).toBe("番茄炒蛋");
});
it("keeps the meal and date-range shopping checkboxes independent", async () => {
  snapshot.data.selectedRecipeIds = ["r1"];
  snapshot.data.weeklyMenu = [
    { date: "2026-10-01", lunch: ["r1"], dinner: [] },
  ];
  await render();
  await tab("菜单");
  const row = [...container.querySelectorAll(".kitchen-shopping-item")].find(
    (el) => el.textContent?.includes("番茄"),
  )!;
  await click(row.querySelector("input")!);
  expect(snapshot.data.shoppingScopes?.meal.checked).toHaveLength(1);
  await click(button("一周采购汇总"));
  const rangeRow = [
    ...container.querySelectorAll(".kitchen-shopping-item"),
  ].find((el) => el.textContent?.includes("番茄"))!;
  expect(rangeRow.querySelector("input")?.checked).toBe(false);
});
it("restores an editor draft for the same kitchen and leaves another kitchen isolated", async () => {
  await render();
  await tab("菜谱");
  await click(button("添加菜谱"));
  await inputValue("#name", "草稿菜谱");
  await click(button("返回"));
  await click(button("保留并离开"));
  await click(button("添加菜谱"));
  expect((document.querySelector("#name") as HTMLInputElement).value).toBe(
    "草稿菜谱",
  );
  await act(async () => root.unmount());
  root = createRoot(container);
  await act(async () =>
    root.render(
      createElement(
        MemoryRouter,
        {},
        createElement(KitchenWorkspace, { base: "/different-kitchen" }),
      ),
    ),
  );
  await settle();
  await tab("菜谱");
  await click(button("添加菜谱"));
  expect((document.querySelector("#name") as HTMLInputElement).value).toBe("");
});
it("previews AI menu results and applies only after confirmation with task identity", async () => {
  const menu = Array.from({ length: 7 }, (_, i) => ({
    date: `2026-10-0${i + 1}`,
    breakfast: [],
    lunch: ["r1"],
    dinner: ["r2"],
  }));
  const task = {
    id: "ai-menu",
    kind: "menu",
    instruction: "安排一周",
    revision: 0,
    status: "succeeded",
    result: { menu },
    error: "",
  };
  vi.mocked(api.get).mockImplementation(async (url) =>
    url.endsWith("/ai/tasks") ? [task] : structuredClone(snapshot),
  );
  await render();
  await click(button("让AI帮忙安排"));
  await click(button("预览菜单"));
  expect(snapshot.data.weeklyMenu).toEqual([]);
  await click(button("确认应用"));
  expect(snapshot.data.weeklyMenu).toHaveLength(7);
  expect((vi.mocked(api.patch).mock.calls[0][1] as KitchenPatch).aiTaskId).toBe(
    "ai-menu",
  );
});
it("retries an AI submission with the same request key after a lost response", async () => {
  vi.mocked(api.get).mockImplementation(async (url) =>
    url.endsWith("/ai/tasks") ? [] : structuredClone(snapshot),
  );
  vi.mocked(api.post)
    .mockRejectedValueOnce(new Error("network"))
    .mockResolvedValueOnce({
      id: "task",
      kind: "menu",
      instruction: "安排晚饭",
      status: "queued",
      result: {},
      error: "",
      revision: 0,
    });
  await render();
  await click(button("让AI帮忙安排"));
  await inputValue('[aria-label="AI 输入"]', "安排晚饭");
  await click(button("生成"));
  expect(document.body.textContent).toContain("提交失败");
  await click(button("重试原请求"));
  expect(vi.mocked(api.post).mock.calls[0][1]).toEqual(
    vi.mocked(api.post).mock.calls[1][1],
  );
  expect(snapshot.data.weeklyMenu).toEqual([]);
});
