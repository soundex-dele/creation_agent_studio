import { useEffect, useRef, useState } from "react";
import {
  Alert,
  Button,
  Checkbox,
  Empty,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Spin,
  Tabs,
  Tag,
} from "antd";
import {
  ArrowLeftOutlined,
  BookOutlined,
  ClockCircleOutlined,
  PlusOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useOrganizationStore } from "@/stores/useOrganizationStore";
import { useAuthStore } from "@/stores/useAuthStore";
import { tenantApiRoot } from "@/services/tenantContext";
import { resolveApplicationPresentation } from "@/lib/applicationPresentation";
import type { AITask, Inventory, Recipe } from "@/services/kitchenAssistant";
import {
  amountText,
  conflicts,
  cookingRecipes,
  deductionPreview,
  defaultPreferences,
  expiryStatus,
  finishCooking,
  localDate,
  mealLabels,
  meals,
  mealSettings,
  menuPurchaseList,
  purchaseList,
  recommend,
  recommendationReasons,
  repeatCooking,
  startCooking,
} from "./kitchen/domain";
import { InventoryEditor, RecipeEditor } from "./kitchen/Editors";
import { useKitchenState } from "./kitchen/useKitchenState";
import { ShoppingPanel } from "./kitchen/ShoppingPanel";
import { WeekPlanner } from "./kitchen/WeekPlanner";
import { RecordHistory } from "./kitchen/RecordHistory";
import { TimerPanel } from "./kitchen/TimerPanel";
import { useTimerAlerts } from "./kitchen/useTimerAlerts";
import { CookingView } from "./kitchen/CookingView";
import { PreferencesPanel } from "./kitchen/PreferencesPanel";
import { CatalogPicker } from "./kitchen/CatalogPicker";
import { AIPanel } from "./kitchen/AIPanel";
import "./KitchenAssistantPage.css";
const expiryLabels = {
  unknown: "未设置到期日",
  normal: "正常",
  soon: "即将到期",
  expired: "已过期",
};
type Editor =
  | { kind: "recipe"; item?: Recipe; missing?: string[] }
  | { kind: "inventory"; item?: Inventory };
export function KitchenWorkspace({
  base,
  showHeader = true,
}: {
  base: string;
  showHeader?: boolean;
}) {
  const pageRoot = useRef<HTMLElement>(null);
  const navigate = useNavigate();
  const userId = useAuthStore((s) => s.user?.id);
  const {
    service,
    snapshot,
    busy,
    saving,
    error,
    pending,
    commit,
    retry,
    refresh,
  } = useKitchenState(base);
  const [tab, setTab] = useState("home");
  const [myTab, setMyTab] = useState("inventory");
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("全部");
  const [mealFilter, setMealFilter] = useState("全部");
  const [difficulty, setDifficulty] = useState("全部");
  const [tagFilter, setTagFilter] = useState("全部");
  const [favorites, setFavorites] = useState(false);
  const [maxMinutes, setMaxMinutes] = useState(1440);
  const [inventoryFilter, setInventoryFilter] = useState("all");
  const [stockSearch, setStockSearch] = useState("");
  const [stockCategory, setStockCategory] = useState("全部");
  const [location, setLocation] = useState("全部");
  const [detail, setDetail] = useState<string>();
  const [detailServings, setDetailServings] = useState(2);
  const [editor, setEditor] = useState<Editor>();
  const [catalogOpen, setCatalogOpen] = useState(false);
  const [ai, setAI] = useState<{ kind: AITask["kind"]; recipeId?: string }>();
  const [cookingOpen, setCookingOpen] = useState(false);
  const [finishOpen, setFinishOpen] = useState(false);
  const [deduct, setDeduct] = useState(true);
  const [now, setNow] = useState(Date.now());
  const [shoppingMode, setShoppingMode] = useState("meal");
  const [start, setStart] = useState(localDate());
  const [end, setEnd] = useState(() => {
    const d = new Date();
    d.setDate(d.getDate() + 6);
    return localDate(d);
  });
  useEffect(() => {
    if (pageRoot.current) pageRoot.current.scrollTop = 0;
  }, [tab, editor?.kind, cookingOpen]);
  const state = snapshot?.data;
  const cooking = state?.cooking;
  const hasTimers = !!cooking && Object.keys(cooking.timers).length > 0;
  useEffect(() => {
    if (!hasTimers) return;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [hasTimers]);
  const alerts = useTimerAlerts(state, now, `${userId ?? "current"}:${base}`);
  const selected =
    state?.recipes.filter((r) => state.selectedRecipeIds.includes(r.id)) ?? [];
  const recipeDetail = state?.recipes.find((r) => r.id === detail);
  const expiring =
    state?.inventory.filter(
      (i) =>
        i.amount > 0 &&
        ["soon", "expired"].includes(expiryStatus(i.expireDate)),
    ) ?? [];
  const prefs = state?.preferences ?? defaultPreferences;
  const toggleRecipe = (id: string) =>
    void commit((s) =>
      s.cooking
        ? s
        : {
            ...s,
            selectedRecipeIds: s.selectedRecipeIds.includes(id)
              ? s.selectedRecipeIds.filter((v) => v !== id)
              : [...s.selectedRecipeIds, id],
            checkedShoppingItems: [],
          },
    );
  const begin = async () => {
    if (state?.cooking || (await commit((s) => startCooking(s))))
      setCookingOpen(true);
  };
  const recipeCards = (recipes: Recipe[]) =>
    recipes.length ? (
      <div className="kitchen-recipes">
        {recipes.map((recipe) => (
          <article className="kitchen-card" key={recipe.id}>
            <div className="kitchen-card-top">
              <span className="kitchen-recipe-icon">
                <BookOutlined />
              </span>
              <Tag>{recipe.category}</Tag>
              <Button
                aria-label={`${recipe.name}${recipe.favorite ? "取消收藏" : "收藏"}`}
                aria-pressed={!!recipe.favorite}
                disabled={busy}
                onClick={() =>
                  void commit((s) => ({
                    ...s,
                    recipes: s.recipes.map((r) =>
                      r.id === recipe.id ? { ...r, favorite: !r.favorite } : r,
                    ),
                  }))
                }
              >
                {recipe.favorite ? "已收藏" : "收藏"}
              </Button>
            </div>
            <button
              className="kitchen-recipe-title"
              onClick={() => {
                setDetail(recipe.id);
                setDetailServings(state?.servings ?? 2);
              }}
            >
              {recipe.name}
            </button>
            <p>{recipe.intro}</p>
            <div className="kitchen-actions">
              {state &&
                recommendationReasons(recipe, state).map((r) => (
                  <Tag key={r}>{r}</Tag>
                ))}
              {recipe.tags?.map((t) => (
                <Tag key={t}>{t}</Tag>
              ))}
            </div>
            <div className="kitchen-meta">
              <span>
                <ClockCircleOutlined /> {recipe.durationMinutes} 分钟
              </span>
              <span>{recipe.difficulty}</span>
              <span>{recipe.servings} 人份</span>
            </div>
            {!!conflicts(recipe, prefs).length && (
              <p className="kitchen-muted">
                {conflicts(recipe, prefs).join("；")}
              </p>
            )}
            <Button
              block
              disabled={busy || !!cooking}
              type={
                state?.selectedRecipeIds.includes(recipe.id)
                  ? "primary"
                  : "default"
              }
              onClick={() => toggleRecipe(recipe.id)}
            >
              {state?.selectedRecipeIds.includes(recipe.id)
                ? "已加入 · 移出清单"
                : "加入待制作"}
            </Button>
          </article>
        ))}
      </div>
    ) : (
      <Empty description="没有符合条件的菜谱，可调整筛选或添加精选菜谱" />
    );
  const draftKey = `kitchen-draft:${userId ?? "current"}:${base}:${editor?.item?.id ?? "new"}`;
  return (
    <main className="kitchen-page app-scroll-page" ref={pageRoot}>
      {showHeader && (
        <header className="kitchen-header">
          <div>
            <Button
              type="text"
              icon={<ArrowLeftOutlined />}
              onClick={() => navigate("/apps")}
            >
              应用中心
            </Button>
            <h1>厨房助手</h1>
            <p>把每一顿家常饭，安排得刚刚好。</p>
          </div>
          <span className="kitchen-eyebrow">YOUR EVERYDAY KITCHEN</span>
        </header>
      )}
      {error && (
        <Alert
          type="error"
          showIcon
          message={error}
          description={
            pending ? "操作已保留，可重试或放弃后刷新。" : "加载失败，请重试。"
          }
          action={
            <div className="kitchen-actions">
              {pending && (
                <Button disabled={saving} onClick={() => void retry()}>
                  {pending.conflict ? "在最新数据上重试" : "重试原操作"}
                </Button>
              )}
              <Button disabled={saving} onClick={() => refresh(true)}>
                {pending ? "放弃本次操作并刷新" : "刷新重试"}
              </Button>
            </div>
          }
        />
      )}
      {!state ? (
        <div className="kitchen-loading">
          {busy ? (
            <Spin tip="正在准备厨房…" />
          ) : (
            <Empty description="暂时无法打开厨房" />
          )}
        </div>
      ) : (
        <>
          <div className="kitchen-status">
            <span>
              {error ? "操作待处理" : busy ? "正在同步…" : "数据私有 · 已保存"}{" "}
              · {state.recipes.length} 道菜谱
            </span>
            <Button
              type="text"
              icon={<ReloadOutlined />}
              disabled={busy}
              onClick={() => refresh()}
            >
              刷新
            </Button>
          </div>
          {editor?.kind === "recipe" ? (
            <RecipeEditor
              key={draftKey}
              draftKey={draftKey}
              recipe={editor.item}
              missing={editor.missing}
              onClose={() => setEditor(undefined)}
              onSave={(item) =>
                commit((s) => ({
                  ...s,
                  recipes: s.recipes.some((r) => r.id === item.id)
                    ? s.recipes.map((r) => (r.id === item.id ? item : r))
                    : [item, ...s.recipes],
                  checkedShoppingItems: [],
                }))
              }
            />
          ) : (
            <>
              {cooking && (
                <>
                  <div className="kitchen-resume">
                    <span>
                      一顿饭正在制作中 · {cooking.completedIds.length}/
                      {cooking.recipeIds.length} 道已完成
                    </span>
                    <Button onClick={() => setCookingOpen(true)}>
                      继续制作
                    </Button>
                  </div>
                  <div className="kitchen-actions">
                    <Button
                      aria-pressed={alerts.sound}
                      onClick={() => void alerts.toggleSound()}
                    >
                      {alerts.sound ? "关闭声音提醒" : "开启声音提醒"}
                    </Button>
                    <Button
                      aria-pressed={alerts.notify}
                      onClick={() => void alerts.toggleNotifications()}
                    >
                      {alerts.notify ? "关闭桌面通知" : "开启桌面通知"}
                    </Button>
                  </div>
                  {alerts.notice && <p role="status">{alerts.notice}</p>}
                </>
              )}
              {cookingOpen && cooking ? (
                <CookingView
                  state={state}
                  now={now}
                  busy={busy}
                  commit={commit}
                  onBack={() => setCookingOpen(false)}
                  onFinish={() => setFinishOpen(true)}
                  onAsk={(recipeId) => setAI({ kind: "question", recipeId })}
                />
              ) : (
                <>
                  {cooking && (
                    <TimerPanel
                      state={state}
                      now={now}
                      busy={busy}
                      commit={commit}
                    />
                  )}
                  <Tabs
                    activeKey={tab}
                    onChange={setTab}
                    items={[
                      { key: "home", label: "今日" },
                      { key: "recipes", label: "菜谱" },
                      {
                        key: "plan",
                        label: `菜单${selected.length ? ` · ${selected.length}` : ""}`,
                      },
                      { key: "shopping", label: "采购" },
                      { key: "kitchen", label: "我的厨房" },
                    ]}
                  />
                  {tab === "home" && (
                    <>
                      <section className="kitchen-hero">
                        <div>
                          <span className="kitchen-eyebrow">
                            A LITTLE PLANNING, A LOVELY MEAL
                          </span>
                          <h2>今天，吃点什么？</h2>
                          <p>安排三餐，买好食材，慢慢做，好好吃。</p>
                          <div className="kitchen-actions">
                            <Button
                              type="primary"
                              size="large"
                              onClick={() => setTab("plan")}
                            >
                              安排今天的饭
                            </Button>
                            <Button onClick={() => setAI({ kind: "menu" })}>
                              让 AI 帮忙安排
                            </Button>
                          </div>
                        </div>
                        <div className="kitchen-hero-note">
                          <span>这一餐</span>
                          <strong>
                            {String(selected.length).padStart(2, "0")}
                          </strong>
                          <span>道菜 · {state.servings} 人</span>
                        </div>
                      </section>
                      <div className="kitchen-section-heading">
                        <h2>今日三餐</h2>
                        <Button onClick={() => setTab("shopping")}>
                          本餐采购缺口 ·{" "}
                          {
                            purchaseList(
                              selected,
                              state.servings,
                              state.inventory,
                            ).filter((i) => i.missing > 0).length
                          }{" "}
                          项
                        </Button>
                      </div>
                      <div className="kitchen-recipes">
                        {meals.map((meal) => {
                          const day = state.weeklyMenu.find(
                            (d) => d.date === localDate(),
                          );
                          const cfg = day
                            ? mealSettings(day, meal, state.servings)
                            : undefined;
                          const ids = day?.[meal] ?? [];
                          return (
                            <section className="kitchen-card" key={meal}>
                              <h3>{mealLabels[meal]}</h3>
                              <p>
                                {cfg?.skipped
                                  ? "不在家吃"
                                  : ids
                                      .map(
                                        (id) =>
                                          state.recipes.find((r) => r.id === id)
                                            ?.name,
                                      )
                                      .join("、") || "还没有安排"}
                              </p>
                              {cfg && <p>{cfg.servings} 人</p>}
                              <Button
                                disabled={
                                  busy ||
                                  !!cooking ||
                                  !ids.length ||
                                  cfg?.skipped
                                }
                                onClick={() =>
                                  void commit((s) => ({
                                    ...s,
                                    selectedRecipeIds: ids,
                                    servings: cfg!.servings,
                                    checkedShoppingItems: [],
                                  })).then((ok) => ok && setTab("plan"))
                                }
                              >
                                选用{mealLabels[meal]}
                              </Button>
                            </section>
                          );
                        })}
                      </div>
                      {expiring.length > 0 && (
                        <Alert
                          type="warning"
                          showIcon
                          message={`${expiring.length} 项食材需要留意到期日期`}
                          action={
                            <Button
                              onClick={() => {
                                setInventoryFilter("attention");
                                setMyTab("inventory");
                                setTab("kitchen");
                              }}
                            >
                              查看库存
                            </Button>
                          }
                        />
                      )}
                      <div className="kitchen-section-heading">
                        <div>
                          <h2>为这一餐找点灵感</h2>
                          <p>根据饮食偏好、可用库存和近期下厨记录推荐。</p>
                        </div>
                        <Button onClick={() => setCatalogOpen(true)}>
                          添加精选菜谱
                        </Button>
                      </div>
                      <Select
                        aria-label="推荐用时"
                        value={maxMinutes}
                        onChange={setMaxMinutes}
                        options={[
                          { value: 1440, label: "不限单道菜用时" },
                          { value: 15, label: "单道菜 15 分钟内" },
                          { value: 30, label: "单道菜 30 分钟内" },
                        ]}
                      />
                      {recipeCards(
                        recommend(
                          state.recipes,
                          state.inventory,
                          undefined,
                          state.servings,
                          state.records,
                          maxMinutes,
                          prefs,
                        ),
                      )}
                      <div className="kitchen-section-heading">
                        <h2>最近下厨</h2>
                        <Button
                          onClick={() => {
                            setMyTab("history");
                            setTab("kitchen");
                          }}
                        >
                          查看记录
                        </Button>
                      </div>
                      {state.records[0] ? (
                        <section className="kitchen-card">
                          <h3>{state.records[0].recipeNames.join("、")}</h3>
                          <p>
                            {state.records[0].tasteNotes ||
                              "给这顿饭写一点心得吧。"}
                          </p>
                        </section>
                      ) : (
                        <Empty description="完成第一顿饭后，这里会出现下厨记录。" />
                      )}
                    </>
                  )}
                  {tab === "recipes" && (
                    <>
                      <div className="kitchen-toolbar">
                        <Input.Search
                          aria-label="搜索菜谱"
                          placeholder="菜名、食材、标签"
                          allowClear
                          value={search}
                          onChange={(e) => setSearch(e.target.value)}
                        />
                        <Select
                          aria-label="菜谱分类"
                          value={category}
                          onChange={setCategory}
                          options={[
                            "全部",
                            ...new Set(state.recipes.map((r) => r.category)),
                          ].map((value) => ({ value, label: value }))}
                        />
                        <Button
                          icon={<PlusOutlined />}
                          disabled={busy || !!cooking}
                          onClick={() => setEditor({ kind: "recipe" })}
                        >
                          添加菜谱
                        </Button>
                        <Button
                          disabled={busy}
                          onClick={() => setCatalogOpen(true)}
                        >
                          添加精选菜谱
                        </Button>
                        <Button
                          disabled={!!cooking}
                          onClick={() => setAI({ kind: "recipe" })}
                        >
                          文字导入
                        </Button>
                      </div>
                      <div className="kitchen-toolbar">
                        <Checkbox
                          checked={favorites}
                          onChange={(e) => setFavorites(e.target.checked)}
                        >
                          只看收藏
                        </Checkbox>
                        <Select
                          aria-label="餐次筛选"
                          value={mealFilter}
                          onChange={setMealFilter}
                          options={["全部", "早", "中", "晚"].map((value) => ({
                            value,
                            label: value === "全部" ? "全部餐次" : `${value}餐`,
                          }))}
                        />
                        <Select
                          aria-label="难度筛选"
                          value={difficulty}
                          onChange={setDifficulty}
                          options={["全部", "简单", "中等", "复杂"].map(
                            (value) => ({
                              value,
                              label: value === "全部" ? "全部难度" : value,
                            }),
                          )}
                        />
                        <Select
                          aria-label="标签筛选"
                          value={tagFilter}
                          onChange={setTagFilter}
                          options={[
                            "全部",
                            ...new Set(
                              state.recipes.flatMap((r) => r.tags ?? []),
                            ),
                          ].map((value) => ({
                            value,
                            label: value === "全部" ? "全部标签" : value,
                          }))}
                        />
                        <Select
                          aria-label="单道菜时间筛选"
                          value={maxMinutes}
                          onChange={setMaxMinutes}
                          options={[
                            { value: 1440, label: "不限单道菜用时" },
                            { value: 15, label: "15 分钟内" },
                            { value: 30, label: "30 分钟内" },
                            { value: 60, label: "60 分钟内" },
                          ]}
                        />
                      </div>
                      {recipeCards(
                        state.recipes.filter(
                          (r) =>
                            (category === "全部" || r.category === category) &&
                            (!favorites || r.favorite) &&
                            (mealFilter === "全部" ||
                              r.mealTimes.some((m) =>
                                m.includes(mealFilter),
                              )) &&
                            (difficulty === "全部" ||
                              r.difficulty === difficulty) &&
                            (tagFilter === "全部" ||
                              r.tags?.includes(tagFilter)) &&
                            r.durationMinutes <= maxMinutes &&
                            `${r.name} ${r.ingredients.map((i) => i.name).join(" ")} ${r.tags?.join(" ")}`.includes(
                              search.trim(),
                            ),
                        ),
                      )}
                    </>
                  )}
                  {tab === "plan" && (
                    <>
                      <div className="kitchen-section-heading">
                        <div>
                          <h2>这一餐的安排</h2>
                          <p>选菜后查看采购缺口，再进入制作。</p>
                        </div>
                        <label className="kitchen-servings">
                          用餐人数
                          <InputNumber
                            aria-label="用餐人数"
                            value={state.servings}
                            min={1}
                            max={8}
                            precision={0}
                            disabled={busy || !!cooking}
                            onChange={(v) =>
                              v &&
                              void commit((s) => ({
                                ...s,
                                servings: v,
                                checkedShoppingItems: [],
                              }))
                            }
                          />
                        </label>
                      </div>
                      {selected.length ? (
                        <div className="kitchen-plan-grid">
                          <section className="kitchen-card">
                            <h3>待制作 · {selected.length} 道</h3>
                            {selected.map((r) => (
                              <div key={r.id}>
                                <div className="kitchen-row">
                                  <button
                                    className="kitchen-link"
                                    onClick={() => {
                                      setDetail(r.id);
                                      setDetailServings(state.servings);
                                    }}
                                  >
                                    {r.name}
                                  </button>
                                  <Button
                                    disabled={busy || !!cooking}
                                    onClick={() => toggleRecipe(r.id)}
                                  >
                                    移出
                                  </Button>
                                </div>
                                {conflicts(r, prefs).length > 0 && (
                                  <p>{conflicts(r, prefs).join("；")}</p>
                                )}
                              </div>
                            ))}
                            <Button
                              type="primary"
                              block
                              disabled={busy}
                              onClick={() => void begin()}
                            >
                              {cooking ? "继续制作" : "进入制作模式"}
                            </Button>
                          </section>
                          <ShoppingPanel
                            state={state}
                            recipes={selected}
                            busy={busy}
                            commit={commit}
                          />
                        </div>
                      ) : (
                        <Empty description="先选几道菜，就能生成采购清单。">
                          <Button onClick={() => setTab("recipes")}>
                            去选菜
                          </Button>
                        </Empty>
                      )}
                      <div className="kitchen-section-heading">
                        <Button onClick={() => setAI({ kind: "menu" })}>
                          AI 按条件安排一周
                        </Button>
                        <Button
                          onClick={() => {
                            setShoppingMode("range");
                            setStart(state.weeklyMenu[0]?.date ?? localDate());
                            setEnd(
                              state.weeklyMenu[state.weeklyMenu.length - 1]
                                ?.date ?? end,
                            );
                            setTab("shopping");
                          }}
                        >
                          一周采购汇总
                        </Button>
                      </div>
                      <WeekPlanner state={state} busy={busy} commit={commit} />
                    </>
                  )}
                  {tab === "shopping" && (
                    <>
                      <h2>采购清单</h2>
                      <div className="kitchen-toolbar">
                        <Select
                          value={shoppingMode}
                          onChange={setShoppingMode}
                          options={[
                            { value: "meal", label: "本餐" },
                            { value: "range", label: "按日期范围" },
                          ]}
                        />
                        {shoppingMode === "range" && (
                          <>
                            <label>
                              开始
                              <Input
                                type="date"
                                value={start}
                                onChange={(e) => setStart(e.target.value)}
                              />
                            </label>
                            <label>
                              结束
                              <Input
                                type="date"
                                value={end}
                                onChange={(e) => setEnd(e.target.value)}
                              />
                            </label>
                          </>
                        )}
                      </div>
                      {shoppingMode === "range" &&
                      (!start || !end || start > end) ? (
                        <Alert type="warning" message="请选择有效日期范围。" />
                      ) : (
                        <ShoppingPanel
                          key={
                            shoppingMode === "meal" ? "meal" : `${start}:${end}`
                          }
                          scope={
                            shoppingMode === "meal"
                              ? "meal"
                              : `range:${start}:${end}`
                          }
                          state={state}
                          recipes={selected}
                          rows={
                            shoppingMode === "range"
                              ? menuPurchaseList(state, start, end)
                              : undefined
                          }
                          busy={busy}
                          commit={commit}
                        />
                      )}
                    </>
                  )}
                  {tab === "kitchen" && (
                    <>
                      <Tabs
                        activeKey={myTab}
                        onChange={setMyTab}
                        items={[
                          { key: "inventory", label: "食材库存" },
                          { key: "history", label: "下厨记录" },
                          { key: "preferences", label: "家庭偏好" },
                        ]}
                      />
                      {myTab === "preferences" && (
                        <PreferencesPanel
                          state={state}
                          busy={busy}
                          commit={commit}
                        />
                      )}
                      {myTab === "history" && (
                        <RecordHistory
                          service={service}
                          revision={snapshot.revision}
                          onChanged={() => refresh()}
                          onRepeat={(record) => {
                            if (cooking) {
                              Modal.info({
                                title: "先完成或放弃当前制作，再开始另一餐。",
                              });
                              return;
                            }
                            const missing =
                              record.recipeSnapshots?.filter(
                                (r) =>
                                  !state.recipes.some((s) => s.id === r.id),
                              ) ?? [];
                            const run = async () => {
                              if (await commit((s) => repeatCooking(s, record)))
                                setTab("plan");
                            };
                            if (missing.length)
                              Modal.confirm({
                                title: "恢复缺失菜谱并再做一次？",
                                content: missing.map((r) => r.name).join("、"),
                                onOk: run,
                              });
                            else if (
                              !record.recipeSnapshots?.length &&
                              record.recipeNames.some(
                                (n) => !state.recipes.some((r) => r.name === n),
                              )
                            )
                              Modal.info({
                                title:
                                  "旧记录缺少快照，部分菜谱已不存在，请手动重新选菜。",
                              });
                            else void run();
                          }}
                        />
                      )}
                      {myTab === "inventory" && (
                        <>
                          <div className="kitchen-section-heading">
                            <div>
                              <h2>食材库存</h2>
                              <p>按到期日期排序；未知日期显示在最后。</p>
                            </div>
                            <Button
                              disabled={busy}
                              onClick={() => setEditor({ kind: "inventory" })}
                            >
                              添加食材
                            </Button>
                          </div>
                          <div className="kitchen-toolbar">
                            <Input.Search
                              aria-label="搜索库存"
                              value={stockSearch}
                              onChange={(e) => setStockSearch(e.target.value)}
                              placeholder="食材名称"
                            />
                            <Select
                              aria-label="库存筛选"
                              value={inventoryFilter}
                              onChange={setInventoryFilter}
                              options={[
                                { value: "all", label: "全部食材" },
                                {
                                  value: "attention",
                                  label: "即将到期 / 已过期",
                                },
                                { value: "zero", label: "零库存" },
                                { value: "positive", label: "有库存" },
                              ]}
                            />
                            <Select
                              value={stockCategory}
                              onChange={setStockCategory}
                              options={[
                                "全部",
                                ...new Set(
                                  state.inventory.map((i) => i.category),
                                ),
                              ].map((value) => ({
                                value,
                                label: value === "全部" ? "全部分类" : value,
                              }))}
                            />
                            <Select
                              value={location}
                              onChange={setLocation}
                              options={["全部", "冷藏", "冷冻", "常温"].map(
                                (value) => ({
                                  value,
                                  label: value === "全部" ? "全部位置" : value,
                                }),
                              )}
                            />
                          </div>
                          <div className="kitchen-inventory">
                            {state.inventory
                              .filter(
                                (i) =>
                                  i.name.includes(stockSearch.trim()) &&
                                  (stockCategory === "全部" ||
                                    i.category === stockCategory) &&
                                  (location === "全部" ||
                                    (i.location ?? "常温") === location) &&
                                  (inventoryFilter === "all" ||
                                    (inventoryFilter === "attention" &&
                                      ["soon", "expired"].includes(
                                        expiryStatus(i.expireDate),
                                      )) ||
                                    (inventoryFilter === "zero" &&
                                      i.amount === 0) ||
                                    (inventoryFilter === "positive" &&
                                      i.amount > 0)),
                              )
                              .sort((a, b) =>
                                (a.expireDate ?? "9999").localeCompare(
                                  b.expireDate ?? "9999",
                                ),
                              )
                              .map((item) => (
                                <article className="kitchen-card" key={item.id}>
                                  <div className="kitchen-row">
                                    <h3>{item.name}</h3>
                                    <Tag>
                                      {
                                        expiryLabels[
                                          expiryStatus(item.expireDate)
                                        ]
                                      }
                                    </Tag>
                                  </div>
                                  <strong>
                                    {amountText(item.amount)} {item.unit}
                                  </strong>
                                  <p>
                                    {item.category} · {item.location ?? "常温"}{" "}
                                    ·{" "}
                                    {item.expireDate
                                      ? `${item.expireDate} 到期`
                                      : "未设置到期日"}
                                  </p>
                                  <div className="kitchen-actions">
                                    <Button
                                      disabled={busy}
                                      onClick={() =>
                                        setEditor({ kind: "inventory", item })
                                      }
                                    >
                                      编辑
                                    </Button>
                                    <Popconfirm
                                      title="删除这项库存？"
                                      onConfirm={() =>
                                        commit((s) => ({
                                          ...s,
                                          inventory: s.inventory.filter(
                                            (i) => i.id !== item.id,
                                          ),
                                        }))
                                      }
                                    >
                                      <Button danger disabled={busy}>
                                        删除
                                      </Button>
                                    </Popconfirm>
                                  </div>
                                </article>
                              ))}
                          </div>
                          {!state.inventory.length && (
                            <Empty description="记录现有食材，让下一顿饭更好安排。" />
                          )}
                        </>
                      )}
                    </>
                  )}
                </>
              )}
            </>
          )}
          {catalogOpen && (
            <CatalogPicker
              service={service}
              state={state}
              busy={busy}
              commit={commit}
              onClose={() => setCatalogOpen(false)}
            />
          )}
          {ai && (
            <AIPanel
              service={service}
              state={state}
              revision={snapshot.revision}
              busy={busy}
              commit={commit}
              initialKind={ai.kind}
              recipeId={ai.recipeId}
              onClose={() => setAI(undefined)}
              onRecipe={(item, missing) => {
                setAI(undefined);
                setEditor({ kind: "recipe", item, missing });
              }}
            />
          )}
        </>
      )}
      {recipeDetail && (
        <Modal
          open
          title={recipeDetail.name}
          width={720}
          onCancel={() => setDetail(undefined)}
          footer={
            <div className="kitchen-actions">
              <Popconfirm
                title="删除这道菜谱？"
                onConfirm={async () => {
                  if (
                    await commit((s) => ({
                      ...s,
                      recipes: s.recipes.filter(
                        (r) => r.id !== recipeDetail.id,
                      ),
                      selectedRecipeIds: s.selectedRecipeIds.filter(
                        (id) => id !== recipeDetail.id,
                      ),
                      weeklyMenu: s.weeklyMenu.map((d) => ({
                        ...d,
                        breakfast: d.breakfast?.filter(
                          (id) => id !== recipeDetail.id,
                        ),
                        lunch: d.lunch.filter((id) => id !== recipeDetail.id),
                        dinner: d.dinner.filter((id) => id !== recipeDetail.id),
                      })),
                    }))
                  )
                    setDetail(undefined);
                }}
              >
                <Button danger disabled={busy || !!cooking}>
                  删除
                </Button>
              </Popconfirm>
              <Button
                disabled={busy || !!cooking}
                onClick={() => {
                  setEditor({ kind: "recipe", item: recipeDetail });
                  setDetail(undefined);
                }}
              >
                编辑
              </Button>
              <Button
                disabled={busy || !!cooking}
                onClick={() => {
                  const copy = structuredClone(recipeDetail);
                  copy.id = crypto.randomUUID();
                  delete copy.catalogId;
                  copy.name += "（副本）";
                  setEditor({ kind: "recipe", item: copy });
                  setDetail(undefined);
                }}
              >
                复制菜谱
              </Button>
              <Button
                onClick={() => {
                  setAI({ kind: "question", recipeId: recipeDetail.id });
                  setDetail(undefined);
                }}
              >
                问 AI
              </Button>
              <Button
                disabled={busy || !!cooking}
                onClick={() => toggleRecipe(recipeDetail.id)}
              >
                {state?.selectedRecipeIds.includes(recipeDetail.id)
                  ? "移出清单"
                  : "加入待制作"}
              </Button>
            </div>
          }
        >
          <p>{recipeDetail.intro}</p>
          <Tag>{recipeDetail.durationMinutes} 分钟</Tag>
          <label>
            用量预览人数
            <InputNumber
              value={detailServings}
              min={1}
              max={8}
              precision={0}
              onChange={(v) => v && setDetailServings(v)}
            />
          </label>
          <h3>食材用量</h3>
          {recipeDetail.ingredients.map((i) => (
            <div className="kitchen-row" key={i.id}>
              <span>{i.name}</span>
              <span>
                {amountText(
                  (i.amount * detailServings) / recipeDetail.servings,
                )}{" "}
                {i.unit}
              </span>
            </div>
          ))}
          <h3>制作方法</h3>
          {recipeDetail.steps.map((step, index) => (
            <section className="kitchen-detail-step" key={step.id}>
              <h4>
                {index + 1}. {step.title}
              </h4>
              <p>{step.description}</p>
              <small>
                {step.heatLevel} · {step.durationMinutes} 分钟
              </small>
            </section>
          ))}
          <h3>小贴士</h3>
          <ul>
            {recipeDetail.tips.map((tip, i) => (
              <li key={i}>{tip}</li>
            ))}
          </ul>
          <p>来源：{recipeDetail.source}</p>
        </Modal>
      )}
      {editor?.kind === "inventory" && (
        <InventoryEditor
          item={editor.item}
          onClose={() => setEditor(undefined)}
          onSave={(item) =>
            commit((s) => ({
              ...s,
              inventory: s.inventory.some((i) => i.id === item.id)
                ? s.inventory.map((i) => (i.id === item.id ? item : i))
                : [item, ...s.inventory],
            }))
          }
        />
      )}
      {finishOpen && cooking && state && (
        <Modal
          open
          title="一顿饭做好了"
          onCancel={() => setFinishOpen(false)}
          okText="保存下厨记录"
          cancelText="继续查看"
          confirmLoading={busy}
          onOk={async () => {
            if (
              await commit((s) =>
                s.cooking?.startedAt === cooking.startedAt
                  ? finishCooking(s, deduct)
                  : s,
              )
            ) {
              setFinishOpen(false);
              setCookingOpen(false);
              setTab("kitchen");
              setMyTab("history");
            }
          }}
        >
          <p>
            {cookingRecipes(state)
              .map((r) => r.name)
              .join("、")}
          </p>
          <Checkbox
            checked={deduct}
            onChange={(e) => setDeduct(e.target.checked)}
          >
            按本餐用量扣减库存
          </Checkbox>
          <p>只使用未过期的兼容单位库存，优先扣减最早到期批次。</p>
          {deduct && (
            <div aria-label="库存扣减预览">
              {deductionPreview(state).map((item) => (
                <div className="kitchen-row" key={item.id}>
                  <span>
                    {item.name} · {item.expireDate ?? "未设置到期日"}
                  </span>
                  <span>
                    扣减 {amountText(item.used)} {item.unit}，剩余{" "}
                    {amountText(item.remaining)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </Modal>
      )}
    </main>
  );
}
export default function KitchenAssistantPage() {
  const { applicationId } = useParams<{ applicationId: string }>();
  const [params] = useSearchParams();
  const organizationId = useOrganizationStore((s) => s.currentOrganizationId);
  const userId = useAuthStore((s) => s.user?.id);
  if (!organizationId || !applicationId || !userId)
    return <Empty description="请选择组织并登录后使用。" />;
  return (
    <KitchenWorkspace
      key={`${organizationId}:${applicationId}:${userId}`}
      base={`${tenantApiRoot(organizationId)}/applications/${applicationId}/kitchen-assistant`}
      showHeader={resolveApplicationPresentation(params).showApplicationHeader}
    />
  );
}
