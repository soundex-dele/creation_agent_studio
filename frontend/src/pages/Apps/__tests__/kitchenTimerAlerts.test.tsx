// @vitest-environment jsdom
import { act, createElement, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useTimerAlerts } from "../kitchen/useTimerAlerts";
import type { KitchenState } from "@/services/kitchenAssistant";

let root: Root;
let container: HTMLDivElement;
const now = Date.now();
const state: KitchenState = {
  recipes: [],
  inventory: [],
  records: [],
  selectedRecipeIds: ["r1"],
  servings: 2,
  checkedShoppingItems: [],
  weeklyMenu: [],
  cooking: {
    startedAt: new Date(now).toISOString(),
    recipeIds: ["r1"],
    currentId: "r1",
    steps: { r1: 0 },
    completedIds: [],
    timers: { r1: now + 1000 },
  },
};
function Harness() {
  const [tick, setTick] = useState(now);
  const alerts = useTimerAlerts(state, tick);
  return createElement(
    "div",
    {},
    createElement(
      "button",
      { onClick: () => void alerts.toggleNotifications() },
      "通知",
    ),
    createElement(
      "button",
      { onClick: () => setTick((t) => t + 1000) },
      "过一秒",
    ),
    createElement("span", {}, alerts.notice),
  );
}
const click = async (text: string) =>
  act(async () =>
    [...container.querySelectorAll("button")]
      .find((b) => b.textContent === text)!
      .click(),
  );
beforeEach(() => {
  sessionStorage.clear();
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.unstubAllGlobals();
});
it("requests permission only on a click and emits one notification per deadline", async () => {
  const emitted = vi.fn();
  const permission = vi.fn(async () => "granted");
  vi.stubGlobal(
    "Notification",
    class {
      static permission = "granted";
      static requestPermission = permission;
      constructor(...args: unknown[]) {
        emitted(...args);
      }
    },
  );
  await act(async () => root.render(createElement(Harness)));
  expect(permission).not.toHaveBeenCalled();
  await click("通知");
  await click("过一秒");
  await click("过一秒");
  expect(permission).toHaveBeenCalledTimes(1);
  expect(emitted).toHaveBeenCalledTimes(1);
  expect(container.textContent).toContain("计时结束");
  await act(async () => root.unmount());
  root = createRoot(container);
  await act(async () => root.render(createElement(Harness)));
  await click("通知");
  await click("过一秒");
  expect(emitted).toHaveBeenCalledTimes(1);
});
it("explains denied permission and still displays the in-page completion", async () => {
  vi.stubGlobal(
    "Notification",
    class {
      static permission = "denied";
      static requestPermission = async () => "denied";
    },
  );
  await act(async () => root.render(createElement(Harness)));
  await click("通知");
  expect(container.textContent).toContain("通知未获允许");
  await click("过一秒");
  expect(container.textContent).toContain("计时结束");
});
