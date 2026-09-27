import { useEffect, useRef, useState } from "react";
import { cookingRecipes } from "./domain";
import type { KitchenState } from "@/services/kitchenAssistant";

export function useTimerAlerts(
  state: KitchenState | undefined,
  now: number,
  namespace = "default",
) {
  const [sound, setSound] = useState(false);
  const [notify, setNotify] = useState(false);
  const [notice, setNotice] = useState("");
  const audio = useRef<AudioContext>();
  const notified = useRef(new Set<string>());
  const storageKey = `kitchen-timer-alerts:${namespace}`;
  useEffect(() => {
    try {
      const saved: unknown = JSON.parse(
        sessionStorage.getItem(storageKey) ?? "[]",
      );
      if (Array.isArray(saved))
        for (const key of saved)
          if (typeof key === "string") notified.current.add(key);
    } catch {
      /* Page-local deduplication still works. */
    }
  }, [storageKey]);
  useEffect(
    () => () => {
      void audio.current?.close();
    },
    [],
  );
  async function toggleSound() {
    if (sound) {
      setSound(false);
      return;
    }
    try {
      audio.current ??= new AudioContext();
      await audio.current.resume();
      setSound(true);
      setNotice("声音提醒已开启，请保持页面打开。");
    } catch {
      setNotice("当前浏览器无法开启声音，请留意页面倒计时。");
    }
  }
  async function toggleNotifications() {
    if (notify) {
      setNotify(false);
      return;
    }
    if (!("Notification" in window)) {
      setNotice("当前浏览器不支持桌面通知。");
      return;
    }
    try {
      const permission = await Notification.requestPermission();
      setNotify(permission === "granted");
      setNotice(
        permission === "granted"
          ? "已开启页面运行期间的桌面通知。"
          : "通知未获允许，请使用页面或声音提醒。",
      );
    } catch {
      setNotice("无法开启桌面通知，请使用页面提醒。");
    }
  }
  useEffect(() => {
    if (!state?.cooking) return;
    for (const [id, deadline] of Object.entries(state.cooking.timers)) {
      const key = `${state.cooking.startedAt}:${id}:${deadline}`;
      if (deadline > now || notified.current.has(key)) continue;
      notified.current.add(key);
      try {
        sessionStorage.setItem(
          storageKey,
          JSON.stringify([...notified.current].slice(-500)),
        );
      } catch {
        /* Page-local deduplication still works. */
      }
      const meta = state.cooking.timerMeta?.[id];
      const recipe = cookingRecipes(state).find(
        (r) => r.id === (meta?.recipeId ?? id),
      );
      const name = `${recipe?.name ?? "菜品"}${meta ? ` · ${recipe?.steps.find((s) => s.id === meta.stepId)?.title ?? "步骤"}` : ""}`;
      setNotice(`${name}计时结束，请查看火候。`);
      if (sound && audio.current?.state === "running") {
        const context = audio.current;
        const oscillator = context.createOscillator();
        const gain = context.createGain();
        oscillator.frequency.value = 880;
        gain.gain.value = 0.15;
        oscillator.connect(gain);
        gain.connect(context.destination);
        oscillator.start();
        oscillator.stop(context.currentTime + 0.7);
        if ("vibrate" in navigator) navigator.vibrate([200, 100, 200]);
      }
      if (
        notify &&
        "Notification" in window &&
        Notification.permission === "granted"
      ) {
        try {
          new Notification("厨房助手 · 计时结束", {
            body: `${name}已到时间。`,
            tag: key,
          });
        } catch {
          /* The in-page notice remains available on unsupported mobile browsers. */
        }
      }
    }
  }, [state, now, sound, notify, storageKey]);
  return { sound, notify, notice, toggleSound, toggleNotifications };
}
