import { useState } from "react";
import { Button, Checkbox, Popconfirm, Progress, Select, Tag } from "antd";
import type { KitchenState } from "@/services/kitchenAssistant";
import { amountText, cookingRecipes } from "./domain";
import { TimerPanel } from "./TimerPanel";
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
        <h2>制作模式</h2>
        <div className="kitchen-actions">
          <Button onClick={onBack}>返回厨房</Button>
          <Button aria-pressed={large} onClick={() => setLarge(!large)}>
            {large ? "标准字号" : "大字模式"}
          </Button>
          <Button onClick={() => onAsk(recipe.id)}>问 AI</Button>
        </div>
      </div>
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
      <TimerPanel state={state} now={now} busy={busy} commit={commit} />
      <Select
        aria-label="当前制作菜谱"
        value={recipe.id}
        disabled={busy}
        onChange={(id) =>
          void commit((s) => ({
            ...s,
            cooking: { ...s.cooking!, currentId: id },
          }))
        }
        options={recipes.map((r) => ({
          value: r.id,
          label: `${r.name}${cooking.completedIds.includes(r.id) ? " · 已完成" : ""}`,
        }))}
      />
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
        disabled={busy || !step.durationMinutes || timerExists}
        onClick={() => {
          const id = crypto.randomUUID();
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
        启动本步计时
      </Button>
      <p className="kitchen-muted">
        计时可跨步骤继续；页面关闭或系统挂起时无法保证提醒。
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
    </section>
  );
}
