import { useState } from "react";
import {
  Alert,
  Button,
  Checkbox,
  Input,
  InputNumber,
  Modal,
  Select,
} from "antd";
import type { KitchenState, MenuDay } from "@/services/kitchenAssistant";
import {
  conflicts,
  defaultPreferences,
  generateMenu,
  localDate,
  mealLabels,
  meals,
  mealSettings,
} from "./domain";
export function WeekPlanner({
  state,
  busy,
  commit,
}: {
  state: KitchenState;
  busy: boolean;
  commit: (change: (state: KitchenState) => KitchenState) => Promise<boolean>;
}) {
  const [start, setStart] = useState(state.weeklyMenu[0]?.date ?? localDate());
  const [preview, setPreview] = useState<ReturnType<typeof generateMenu>>();
  const [copied, setCopied] = useState<{ ids: string[]; servings: number }>();
  const update = (date: string, change: (day: MenuDay) => MenuDay) =>
    void commit((s) => ({
      ...s,
      weeklyMenu: s.weeklyMenu.map((day) =>
        day.date === date ? change(day) : day,
      ),
    }));
  const render = (days: MenuDay[], readOnly = false) => (
    <div className="kitchen-week">
      {days.map((day) => (
        <section className="kitchen-card" key={day.date}>
          <h3>{day.date}</h3>
          {meals.map((meal) => {
            const settings = mealSettings(day, meal, state.servings);
            const ids = day[meal] ?? [];
            const changeSettings = (patch: Partial<typeof settings>) =>
              update(day.date, (d) => ({
                ...d,
                settings: {
                  ...d.settings,
                  [meal]: {
                    ...mealSettings(d, meal, state.servings),
                    ...patch,
                  },
                },
              }));
            const warnings = ids.flatMap((id) => {
              const r = state.recipes.find((r) => r.id === id);
              return r
                ? conflicts(r, state.preferences ?? defaultPreferences).map(
                    (c) => `${r.name}：${c}`,
                  )
                : ["菜谱已不存在"];
            });
            return (
              <div className="kitchen-meal" key={meal}>
                <h4>
                  {mealLabels[meal]} · {settings.servings} 人
                  {settings.skipped ? " · 不在家吃" : ""}
                  {settings.locked ? " · 已锁定" : ""}
                </h4>
                {readOnly ? (
                  <p>
                    {ids
                      .map((id) => state.recipes.find((r) => r.id === id)?.name)
                      .join("、") || "待安排"}
                  </p>
                ) : (
                  <>
                    <div className="kitchen-actions">
                      <Checkbox
                        disabled={busy}
                        checked={settings.locked}
                        onChange={(e) =>
                          changeSettings({ locked: e.target.checked })
                        }
                      >
                        锁定
                      </Checkbox>
                      <Checkbox
                        disabled={busy}
                        checked={settings.skipped}
                        onChange={(e) =>
                          changeSettings({ skipped: e.target.checked })
                        }
                      >
                        不在家吃
                      </Checkbox>
                    </div>
                    <div className="kitchen-form-grid">
                      <label>
                        人数
                        <InputNumber
                          aria-label={`${day.date}${mealLabels[meal]}人数`}
                          min={1}
                          max={8}
                          precision={0}
                          value={settings.servings}
                          disabled={busy || settings.locked}
                          onChange={(v) => v && changeSettings({ servings: v })}
                        />
                      </label>
                      <label>
                        计划菜数
                        <InputNumber
                          min={1}
                          max={8}
                          precision={0}
                          value={settings.count}
                          disabled={busy || settings.locked}
                          onChange={(v) => v && changeSettings({ count: v })}
                        />
                      </label>
                    </div>
                    <label>
                      {mealLabels[meal]}菜品
                      <Select
                        mode="multiple"
                        aria-label={`${day.date}${mealLabels[meal]}`}
                        disabled={busy || settings.locked || settings.skipped}
                        value={ids}
                        options={state.recipes.map((r) => ({
                          value: r.id,
                          label: r.name,
                        }))}
                        onChange={(values) =>
                          update(day.date, (d) => ({ ...d, [meal]: values }))
                        }
                      />
                    </label>
                    {warnings.length > 0 && (
                      <p role="status">{warnings.join("；")}</p>
                    )}
                    <div className="kitchen-actions">
                      <Button
                        disabled={
                          busy ||
                          !!state.cooking ||
                          !ids.length ||
                          settings.skipped
                        }
                        onClick={() =>
                          void commit((s) => ({
                            ...s,
                            selectedRecipeIds: ids,
                            servings: settings.servings,
                            checkedShoppingItems: [],
                          }))
                        }
                      >
                        选用{mealLabels[meal]}
                      </Button>
                      <Button
                        onClick={() =>
                          setCopied({
                            ids: [...ids],
                            servings: settings.servings,
                          })
                        }
                      >
                        复制本餐
                      </Button>
                      <Button
                        disabled={
                          busy || !copied || settings.locked || settings.skipped
                        }
                        onClick={() =>
                          copied &&
                          update(day.date, (d) => ({
                            ...d,
                            [meal]: copied.ids.filter((id) =>
                              state.recipes.some((r) => r.id === id),
                            ),
                            settings: {
                              ...d.settings,
                              [meal]: {
                                ...settings,
                                servings: copied.servings,
                              },
                            },
                          }))
                        }
                      >
                        粘贴本餐
                      </Button>
                      <Button
                        disabled={busy || settings.locked || settings.skipped}
                        onClick={() => {
                          const candidateState = {
                            ...state,
                            recipes: state.recipes.filter(
                              (r) => !ids.includes(r.id),
                            ),
                            weeklyMenu: state.weeklyMenu.map((d) => ({
                              ...d,
                              settings: Object.fromEntries(
                                meals.map((m) => [
                                  m,
                                  {
                                    ...mealSettings(d, m, state.servings),
                                    locked: d.date !== day.date || m !== meal,
                                  },
                                ]),
                              ),
                            })),
                          };
                          const result = generateMenu(
                            candidateState,
                            state.weeklyMenu[0]?.date ?? start,
                          );
                          const replacement =
                            result.menu.find((d) => d.date === day.date)?.[
                              meal
                            ] ?? [];
                          setPreview({
                            menu: state.weeklyMenu.map((d) =>
                              d.date === day.date
                                ? { ...d, [meal]: replacement }
                                : d,
                            ),
                            warnings: result.warnings.filter((w) =>
                              w.startsWith(`${day.date}${mealLabels[meal]}`),
                            ),
                          });
                        }}
                      >
                        换一餐
                      </Button>
                    </div>
                    {ids.map((id) => (
                      <div className="kitchen-row" key={id}>
                        <span>
                          {state.recipes.find((r) => r.id === id)?.name}
                        </span>
                        <Select
                          aria-label={`替换${state.recipes.find((r) => r.id === id)?.name}`}
                          placeholder="换一道"
                          disabled={busy || settings.locked || settings.skipped}
                          value={undefined}
                          options={state.recipes
                            .filter((r) => !ids.includes(r.id))
                            .map((r) => ({ value: r.id, label: r.name }))}
                          onChange={(replacement) =>
                            update(day.date, (d) => ({
                              ...d,
                              [meal]: (d[meal] ?? []).map((r) =>
                                r === id ? replacement : r,
                              ),
                            }))
                          }
                        />
                      </div>
                    ))}
                  </>
                )}
              </div>
            );
          })}
        </section>
      ))}
    </div>
  );
  return (
    <>
      <div className="kitchen-section-heading">
        <div>
          <h2>一周菜单</h2>
          <p>三餐独立人数；锁定和不在家吃的安排不会被自动替换。</p>
        </div>
        <div className="kitchen-actions">
          <Input
            type="date"
            aria-label="周菜单开始日期"
            value={start}
            onChange={(e) => setStart(e.target.value)}
          />
          <Button
            disabled={busy || !start}
            onClick={() => setPreview(generateMenu(state, start))}
          >
            生成参考菜单
          </Button>
        </div>
      </div>
      {render(state.weeklyMenu)}
      {!state.weeklyMenu.length && (
        <p>选择开始日期，生成七天菜单；确认前可查看每餐安排。</p>
      )}
      {preview && (
        <Modal
          open
          title="确认菜单安排"
          width={1000}
          onCancel={() => setPreview(undefined)}
          okText="应用菜单"
          confirmLoading={busy}
          onOk={async () => {
            if (
              await commit((s) => ({
                ...s,
                weeklyMenu: preview.menu.map((day) => {
                  const current = s.weeklyMenu.find((d) => d.date === day.date);
                  if (!current) return day;
                  const result = { ...day, settings: { ...day.settings } };
                  for (const meal of meals) {
                    const config = mealSettings(current, meal, s.servings);
                    if (config.locked || config.skipped) {
                      result[meal] = current[meal] ?? [];
                      result.settings[meal] = config;
                    }
                  }
                  return result;
                }),
              }))
            )
              setPreview(undefined);
          }}
        >
          {preview.warnings.length > 0 && (
            <Alert
              type="warning"
              message="部分餐次需要留意"
              description={
                <ul>
                  {preview.warnings.map((w, i) => (
                    <li key={i}>{w}</li>
                  ))}
                </ul>
              }
            />
          )}
          {render(preview.menu, true)}
        </Modal>
      )}
    </>
  );
}
