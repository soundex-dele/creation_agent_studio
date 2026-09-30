import { createUuid } from "@/lib/uuid";
import { useState } from "react";
import { Button, Checkbox, Popconfirm, Progress, Tag } from "antd";
import { ChefHat, CheckCircle, Timer } from "@phosphor-icons/react";
import type { KitchenState } from "@/services/kitchenAssistant";
import { amountText, cookingRecipes } from "./domain";
import { formatCountdown, kitchenTimers } from "./timers";
export function CookingView({
  state,
  now,
  busy,
  commit,
  onBack,
  onFinish,
  onAsk,
}: {
  state: KitchenState;
  now: number;
  busy: boolean;
  commit: (change: (s: KitchenState) => KitchenState) => Promise<boolean>;
  onBack: () => void;
  onFinish: () => void;
  onAsk: (id: string) => void;
}) {
  const [large, setLarge] = useState(true);
  const cooking = state.cooking!;
  const recipes = cookingRecipes(state);
  const timers = kitchenTimers(state, now);
  const recipe = recipes.find((r) => r.id === cooking.currentId);
  const step = recipe?.steps[cooking.steps[recipe.id]];
  if (!recipe || !step)
    return (
      <section>
        <p>制作进度无法读取，请刷新后重试。</p>
        <Button onClick={onBack}>返回厨房</Button>
      </section>
    );
  const timerExists =
    cooking.timers[recipe.id] !== undefined ||
    cooking.pausedTimers?.[recipe.id] !== undefined ||
    Object.values(cooking.timerMeta ?? {}).some(
      (m) => m.recipeId === recipe.id && m.stepId === step.id,
    );
  const prep = recipes.flatMap((r) =>
    r.steps
      .filter((s) => s.phase === "prep")
      .map((s) => ({ key: `${r.id}:${s.id}`, name: r.name, step: s })),
  );
  return (
    <section className={`kitchen-cooking ${large ? "kitchen-large" : ""}`}>
      <div className="kitchen-section-heading">
        <div>
          <span className="kitchen-eyebrow"><ChefHat size={18} aria-hidden="true" /> 一起开火，从容上桌</span>
          <h2>制作模式</h2>
          <p>{recipes.length} 道菜同时安排 · 已完成 {cooking.completedIds.length} 道</p>
        </div>
        <div className="kitchen-actions">
          <Button onClick={onBack}>返回厨房</Button>
          <Button aria-pressed={large} onClick={() => setLarge(!large)}>
            {large ? "标准字号" : "大字模式"}
          </Button>
          <Button onClick={() => onAsk(recipe.id)}>问 AI</Button>
        </div>
      </div>
      <div className="kitchen-dish-board" role="group" aria-label="同时制作的菜品">
        {recipes.map((dish) => {
          const completed = cooking.completedIds.includes(dish.id);
          const dishTimers = timers.filter((timer) => timer.recipeId === dish.id);
          const running = dishTimers.filter((timer) => !timer.paused);
          const next = running.length ? Math.min(...running.map((timer) => timer.remaining)) : null;
          return (
            <button
              key={dish.id}
              className="kitchen-dish-card"
              aria-label={`切换制作${dish.name}`}
              aria-pressed={dish.id === recipe.id}
              disabled={busy}
              onClick={() => void commit((s) => s.cooking ? ({ ...s, cooking: { ...s.cooking, currentId: dish.id } }) : s)}
            >
              <span className="kitchen-dish-card-top"><ChefHat size={20} aria-hidden="true" /><span>{completed ? "已完成" : dish.id === recipe.id ? "正在查看" : "点击切换"}</span>{completed && <CheckCircle size={18} aria-hidden="true" />}</span>
              <strong>{dish.name}</strong>
              <span className="kitchen-dish-step">步骤 {(cooking.steps[dish.id] ?? 0) + 1}/{dish.steps.length} · {dish.steps[cooking.steps[dish.id] ?? 0]?.title}</span>
              <span className="kitchen-dish-timing"><Timer size={16} aria-hidden="true" />{next === 0 ? "计时已到，请查看火候" : next !== null ? `${dishTimers.length} 个计时 · ${formatCountdown(next)}` : dishTimers.length ? "计时已暂停" : "暂无计时"}</span>
            </button>
          );
        })}
      </div>
      <p className="kitchen-muted">点击菜品可随时切换步骤；其他菜的计时会继续。</p>
      <details>
        <summary>
          本餐备菜清单 · {(cooking.prepared ?? []).length}/{prep.length}
        </summary>
        {prep.map((p) => (
          <div className="kitchen-card" key={p.key}>
            <Checkbox
              disabled={busy}
              checked={cooking.prepared?.includes(p.key)}
              onChange={(e) =>
                void commit((s) => ({
                  ...s,
                  cooking: {
                    ...s.cooking!,
                    prepared: e.target.checked
                      ? [...new Set([...(s.cooking?.prepared ?? []), p.key])]
                      : (s.cooking?.prepared ?? []).filter((k) => k !== p.key),
                  },
                }))
              }
            >
              {p.name} · {p.step.title}
            </Checkbox>
            <p>{p.step.description}</p>
          </div>
        ))}
        {!prep.length && <p>这些菜谱没有单独的备菜步骤。</p>}
      </details>
      <article className="kitchen-active-step">
        <div className="kitchen-eyebrow"><ChefHat size={18} aria-hidden="true" />{recipe.name}</div>
        <Progress
          percent={Math.round(
            ((cooking.steps[recipe.id] + 1) / recipe.steps.length) * 100,
          )}
          showInfo={false}
        />
        <span>
          步骤 {cooking.steps[recipe.id] + 1} / {recipe.steps.length}
        </span>
        <h2>{step.title}</h2>
        <p className="kitchen-instruction">{step.description}</p>
        <Tag>{step.heatLevel}</Tag>
        <Tag>{step.durationMinutes} 分钟</Tag>
        <div className="kitchen-step-ingredients">
          {recipe.ingredients
            .filter((i) => step.ingredientIds.includes(i.id))
            .map((i) => (
              <span key={i.id}>
                {i.name}{" "}
                {amountText(
                  (i.amount * (cooking.servings ?? state.servings)) /
                    recipe.servings,
                )}{" "}
                {i.unit}
              </span>
            ))}
        </div>
        <Button
          icon={<Timer size={20} aria-hidden="true" />}
          disabled={busy || !step.durationMinutes || timerExists}
          onClick={() => {
            const id = createUuid();
            const deadline = Date.now() + step.durationMinutes * 60000;
            void commit((s) => ({
              ...s,
              cooking: {
                ...s.cooking!,
                timers: { ...s.cooking!.timers, [id]: deadline },
                timerMeta: {
                  ...s.cooking!.timerMeta,
                  [id]: { recipeId: recipe.id, stepId: step.id },
                },
              },
            }));
          }}
        >
          {timerExists ? "本步已添加计时" : "启动本步计时"}
        </Button>
        <p className="kitchen-muted">
          添加后，点击右下角计时图标查看各道菜的倒计时。
        </p>
        <details>
          <summary>步骤总览与小贴士</summary>
          {recipe.steps.map((item, index) => (
            <div className="kitchen-detail-step" key={item.id}>
              <Button
                disabled={busy}
                onClick={() =>
                  void commit((s) => ({
                    ...s,
                    cooking: {
                      ...s.cooking!,
                      steps: { ...s.cooking!.steps, [recipe.id]: index },
                    },
                  }))
                }
              >
                {index + 1}. {item.title}
              </Button>
              <p>{item.description}</p>
            </div>
          ))}
          <p>{recipe.tips.join(" ")}</p>
        </details>
        <div className="kitchen-cooking-nav">
          <Button
            disabled={busy || cooking.steps[recipe.id] === 0}
            onClick={() =>
              void commit((s) => ({
                ...s,
                cooking: {
                  ...s.cooking!,
                  steps: {
                    ...s.cooking!.steps,
                    [recipe.id]: s.cooking!.steps[recipe.id] - 1,
                  },
                },
              }))
            }
          >
            上一步
          </Button>
          <Button
            type="primary"
            disabled={busy}
            onClick={async () => {
              if (cooking.steps[recipe.id] < recipe.steps.length - 1) {
                await commit((s) => ({
                  ...s,
                  cooking: {
                    ...s.cooking!,
                    steps: {
                      ...s.cooking!.steps,
                      [recipe.id]: s.cooking!.steps[recipe.id] + 1,
                    },
                  },
                }));
                return;
              }
              const completedIds = [
                ...new Set([...cooking.completedIds, recipe.id]),
              ];
              const next = cooking.recipeIds.find(
                (id) => !completedIds.includes(id),
              );
              if (
                (await commit((s) => ({
                  ...s,
                  cooking: {
                    ...s.cooking!,
                    completedIds,
                    currentId: next ?? recipe.id,
                  },
                }))) &&
                !next
              )
                onFinish();
            }}
          >
            {cooking.steps[recipe.id] < recipe.steps.length - 1
              ? "下一步"
              : "完成这道菜"}
          </Button>
        </div>
      </article>
      <div className="kitchen-cooking-footer">
        {cooking.completedIds.length === cooking.recipeIds.length && (
          <Button type="primary" onClick={onFinish}>
            保存本餐记录
          </Button>
        )}
        <Popconfirm
          title="结束本次制作并保留待制作清单？"
          description="步骤与计时将清除，不会生成记录或扣减库存。"
          onConfirm={async () => {
            if (await commit((s) => ({ ...s, cooking: null }))) onBack();
          }}
        >
          <Button danger disabled={busy}>
            放弃本次制作
          </Button>
        </Popconfirm>
      </div>
    </section>
  );
}
