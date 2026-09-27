import { useEffect, useState } from "react";
import { Alert, Button, Input, Modal, Select, Tag } from "antd";
import type {
  AITask,
  KitchenState,
  Recipe,
  kitchenApi,
} from "@/services/kitchenAssistant";
import { localDate, mealLabels, meals } from "./domain";
const active = new Set([
  "queued",
  "running",
  "waiting_input",
  "waiting_children",
  "cancelling",
]);
const statuses: Record<string, string> = {
  queued: "等待中",
  running: "生成中",
  waiting_input: "等待输入",
  waiting_children: "处理中",
  cancelling: "正在取消",
  cancelled: "已取消",
  succeeded: "已完成",
  failed: "失败",
};
export function AIPanel({
  service,
  state,
  revision,
  busy,
  commit,
  recipeId,
  initialKind = "recipe",
  onRecipe,
  onClose,
}: {
  service: ReturnType<typeof kitchenApi>;
  state: KitchenState;
  revision: number;
  busy: boolean;
  commit: (
    change: (s: KitchenState) => KitchenState,
    aiTaskId?: string,
  ) => Promise<boolean>;
  recipeId?: string;
  initialKind?: AITask["kind"];
  onRecipe: (recipe: Recipe, missing: string[]) => void;
  onClose: () => void;
}) {
  const [kind, setKind] = useState(initialKind);
  const [instruction, setInstruction] = useState("");
  const [start, setStart] = useState(state.weeklyMenu[0]?.date ?? localDate());
  const [tasks, setTasks] = useState<AITask[]>([]);
  const [error, setError] = useState("");
  const [sending, setSending] = useState(false);
  const [parent, setParent] = useState<string>();
  const [preview, setPreview] = useState<{ task: AITask; revision: number }>();
  const [pending, setPending] =
    useState<Parameters<typeof service.createTask>[0]>();
  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const refresh = async () => {
      try {
        const value = await service.tasks();
        if (alive) {
          setTasks(value);
          timer = setTimeout(
            refresh,
            value.some((t) => active.has(t.status)) ? 2000 : 10000,
          );
        }
      } catch {
        if (alive) {
          setError("AI 任务加载失败，将自动重试。");
          timer = setTimeout(refresh, 10000);
        }
      }
    };
    void refresh();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [service]);
  const previewMenu = preview?.task.result.menu?.map((day) => {
    const current = state.weeklyMenu.find((d) => d.date === day.date);
    if (!current) return day;
    const next = { ...day, settings: { ...day.settings } };
    for (const meal of meals) {
      const config = current.settings?.[meal];
      if (config?.locked || config?.skipped) {
        next[meal] = current[meal] ?? [];
        next.settings[meal] = config;
      }
    }
    return next;
  });
  const submit = async (retry = false) => {
    const input =
      retry && pending
        ? pending
        : {
            kind,
            instruction,
            revision,
            requestKey: crypto.randomUUID(),
            recipeId,
            parentId: parent,
            startDate: kind === "menu" ? start : undefined,
          };
    setSending(true);
    setError("");
    setPending(input);
    try {
      const task = await service.createTask(input);
      setTasks((old) => [task, ...old.filter((t) => t.id !== task.id)]);
      setPending(undefined);
    } catch {
      setError(
        "提交失败，输入已保留。可安全重试原请求；如果数据已更新，请放弃原请求后重新生成。",
      );
    } finally {
      setSending(false);
    }
  };
  return (
    <Modal
      open
      title="AI 厨房助手"
      width={900}
      footer={null}
      onCancel={onClose}
    >
      <p>AI 结果先预览确认，再保存到厨房。模型由组织设置提供。</p>
      <div className="kitchen-toolbar">
        <Select
          aria-label="AI 功能"
          value={kind}
          onChange={(v) => {
            setKind(v);
            setParent(undefined);
          }}
          options={[
            { value: "recipe", label: "文字整理菜谱" },
            { value: "menu", label: "按条件安排菜单" },
            { value: "question", label: "烹饪问答" },
          ]}
        />
        {kind === "menu" && (
          <label>
            开始日期
            <Input
              type="date"
              value={start}
              onChange={(e) => setStart(e.target.value)}
            />
          </label>
        )}
      </div>
      {parent && (
        <p>
          正在追问上一条回答{" "}
          <Button onClick={() => setParent(undefined)}>开始新问题</Button>
        </p>
      )}
      <Input.TextArea
        aria-label="AI 输入"
        rows={5}
        maxLength={20000}
        value={instruction}
        onChange={(e) => setInstruction(e.target.value)}
        placeholder={
          kind === "recipe"
            ? "粘贴菜谱原文；未写明的数量、份数和时间会标记待补充。"
            : kind === "menu"
              ? "例如：安排下周晚餐，两个人，少辣，优先用鸡蛋和番茄。"
              : "例如：这一步应该用多大的火？"
        }
      />
      <Button
        type="primary"
        disabled={
          busy ||
          sending ||
          !instruction.trim() ||
          !!pending ||
          (kind === "menu" && !start)
        }
        loading={sending}
        onClick={() => void submit()}
      >
        生成
      </Button>
      {error && <Alert type="error" message={error} />}
      {pending && (
        <div className="kitchen-actions">
          <Button disabled={sending} onClick={() => void submit(true)}>
            重试原请求
          </Button>
          <Button onClick={() => setPending(undefined)}>放弃原请求</Button>
        </div>
      )}
      <h3>最近任务</h3>
      {tasks.map((task) => (
        <article className="kitchen-card" key={task.id}>
          <div className="kitchen-row">
            <strong>
              {
                {
                  recipe: "文字整理菜谱",
                  menu: "菜单安排",
                  question: "烹饪问答",
                }[task.kind]
              }
            </strong>
            <Tag>{statuses[task.status] ?? task.status}</Tag>
          </div>
          <p>{task.instruction}</p>
          {task.error && <Alert type="error" message={task.error} />}
          {active.has(task.status) && (
            <Button
              onClick={async () => {
                try {
                  const next = await service.cancelTask(task.id);
                  setTasks((old) =>
                    old.map((t) => (t.id === next.id ? next : t)),
                  );
                } catch {
                  setError("取消失败，请重试。");
                }
              }}
            >
              取消任务
            </Button>
          )}
          {task.status === "failed" && (
            <Button
              onClick={() => {
                setKind(task.kind);
                setInstruction(task.instruction);
                setParent(task.parentId);
              }}
            >
              填回输入，手动重试
            </Button>
          )}
          {task.status === "succeeded" && (
            <>
              {task.result.answer && (
                <>
                  <p className="kitchen-ai-answer">{task.result.answer}</p>
                  <Button
                    onClick={() => {
                      setKind("question");
                      setParent(task.id);
                      setInstruction("");
                    }}
                  >
                    继续追问
                  </Button>
                </>
              )}
              {task.result.recipe && (
                <>
                  <p>
                    {task.result.recipe.name} ·{" "}
                    {task.result.missing?.length
                      ? `${task.result.missing.length} 项待补充`
                      : "待核对"}
                  </p>
                  <Button
                    disabled={busy || !!state.cooking}
                    onClick={() =>
                      onRecipe(task.result.recipe!, task.result.missing ?? [])
                    }
                  >
                    核对并编辑菜谱
                  </Button>
                </>
              )}
              {task.result.menu && (
                <Button
                  disabled={busy}
                  onClick={() => setPreview({ task, revision })}
                >
                  预览菜单
                </Button>
              )}
            </>
          )}
        </article>
      ))}
      {preview && (
        <Modal
          open
          title="AI 菜单预览"
          width={800}
          okText="确认应用"
          onCancel={() => setPreview(undefined)}
          confirmLoading={busy}
          onOk={async () => {
            if (preview.revision !== revision) {
              setError("预览期间数据有变化，请重新打开预览。");
              setPreview(undefined);
              return;
            }
            const menu = previewMenu!;
            if (
              menu.some((d) =>
                meals.some((m) =>
                  (d[m] ?? []).some(
                    (id) => !state.recipes.some((r) => r.id === id),
                  ),
                ),
              )
            ) {
              setError("生成结果引用的菜谱已删除，请重新生成菜单。");
              return;
            }
            if (
              await commit(
                (s) => ({
                  ...s,
                  weeklyMenu: menu.map((day) => {
                    const current = s.weeklyMenu.find(
                      (d) => d.date === day.date,
                    );
                    if (!current) return day;
                    const next = { ...day, settings: { ...day.settings } };
                    for (const meal of meals) {
                      const cfg = current.settings?.[meal];
                      if (cfg?.locked || cfg?.skipped) {
                        next[meal] = current[meal] ?? [];
                        next.settings[meal] = cfg;
                      }
                    }
                    return next;
                  }),
                }),
                preview.task.id,
              )
            )
              setPreview(undefined);
          }}
        >
          {preview.task.revision !== revision && (
            <Alert
              type="warning"
              message="厨房数据在生成后有变化，请核对当前偏好和安排；锁定的餐次仍会保留。"
            />
          )}
          {previewMenu?.map((day) => (
            <section key={day.date}>
              <h4>{day.date}</h4>
              {meals.map((meal) => (
                <p key={meal}>
                  {mealLabels[meal]} ·{" "}
                  {day.settings?.[meal]?.servings ?? state.servings} 人：
                  {day.settings?.[meal]?.skipped
                    ? "不在家吃"
                    : (day[meal] ?? [])
                        .map(
                          (id) =>
                            state.recipes.find((r) => r.id === id)?.name ??
                            "菜谱已删除",
                        )
                        .join("、") || "待安排"}
                </p>
              ))}
            </section>
          ))}
        </Modal>
      )}
    </Modal>
  );
}
