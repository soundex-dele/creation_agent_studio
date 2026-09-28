import { createUuid } from "@/lib/uuid";
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
import type { KitchenState, Recipe } from "@/services/kitchenAssistant";
import {
  amountText,
  normalizedUnit,
  purchaseList,
  receivePurchases,
  type Purchase,
  type PurchaseItem,
} from "./domain";
export function ShoppingPanel({
  state,
  recipes,
  busy,
  commit,
  allowReceive = true,
  scope = "meal",
  rows,
}: {
  state: KitchenState;
  recipes: Recipe[];
  busy: boolean;
  commit: (change: (state: KitchenState) => KitchenState) => Promise<boolean>;
  allowReceive?: boolean;
  scope?: string;
  rows?: PurchaseItem[];
}) {
  const saved = state.shoppingScopes?.[scope] ?? {
    checked: scope === "meal" ? state.checkedShoppingItems : [],
    manual: [],
  };
  const manual = saved.manual.map((i) => {
    const u = normalizedUnit(i.unit);
    return {
      ...i,
      key: `manual:${i.id}`,
      unit: u.unit,
      amount: i.amount * u.factor,
      available: 0,
      missing: i.amount * u.factor,
      sources: ["手动添加"],
    };
  });
  const items = [
    ...(rows ?? purchaseList(recipes, state.servings, state.inventory)),
    ...manual,
  ].sort(
    (a, b) =>
      ["main", "side", "seasoning"].indexOf(a.type) -
      ["main", "side", "seasoning"].indexOf(b.type),
  );
  const [purchases, setPurchases] = useState<Purchase[]>();
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [extra, setExtra] = useState({
    name: "",
    amount: 1,
    unit: "个",
    type: "main",
  });
  const selected = items.filter(
    (i) => saved.checked.includes(i.key) && i.missing > 0,
  );
  const changeChecked = (key: string, checked: boolean) =>
    void commit((s) => {
      const current = s.shoppingScopes?.[scope] ?? saved;
      return {
        ...s,
        shoppingScopes: {
          ...s.shoppingScopes,
          [scope]: {
            ...current,
            checked: checked
              ? [...new Set([...current.checked, key])]
              : current.checked.filter((k) => k !== key),
          },
        },
      };
    });
  return (
    <section className="kitchen-card">
      <h3>采购清单</h3>
      <p>按实际人数和用餐日期计算，过期库存不抵扣需求。</p>
      <Button
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(
              items
                .filter((i) => i.missing > 0)
                .map(
                  (i) => `${i.name}：需购买 ${amountText(i.missing)} ${i.unit}`,
                )
                .join("\n"),
            );
            setNotice("采购清单已复制");
          } catch {
            setError("无法访问剪贴板，请手动选择清单文字复制。");
          }
        }}
      >
        复制采购清单
      </Button>
      {notice && <p role="status">{notice}</p>}
      {error && <Alert type="error" message={error} />}
      {items.map((item) => (
        <div className="kitchen-shopping-item" key={item.key}>
          <Checkbox
            disabled={busy || item.missing === 0}
            checked={saved.checked.includes(item.key)}
            onChange={(e) => changeChecked(item.key, e.target.checked)}
          >
            {item.name}
            <small>
              {
                (
                  { main: "主料", side: "辅料", seasoning: "调料" } as Record<
                    string,
                    string
                  >
                )[item.type]
              }{" "}
              · {item.sources.join("、")}
            </small>
          </Checkbox>
          <div>
            <strong>
              需要 {amountText(item.amount)} {item.unit}
            </strong>
            <small>
              {rows ? "计入库存" : "已有"} {amountText(item.available)} ·{" "}
              {item.missing > 0
                ? `还缺 ${amountText(item.missing)}`
                : "库存足够"}
            </small>
          </div>
          {item.key.startsWith("manual:") && (
            <Button
              disabled={busy}
              onClick={() =>
                void commit((s) => ({
                  ...s,
                  shoppingScopes: {
                    ...s.shoppingScopes,
                    [scope]: {
                      ...(s.shoppingScopes?.[scope] ?? saved),
                      manual: (
                        s.shoppingScopes?.[scope] ?? saved
                      ).manual.filter((i) => `manual:${i.id}` !== item.key),
                      checked: (
                        s.shoppingScopes?.[scope] ?? saved
                      ).checked.filter((k) => k !== item.key),
                    },
                  },
                }))
              }
            >
              移除
            </Button>
          )}
        </div>
      ))}
      {!items.length && <p>暂无采购需求，可以手动添加。</p>}
      <details>
        <summary>手动补充采购项</summary>
        <div className="kitchen-form-grid">
          <label>
            名称
            <Input
              aria-label="补充食材名称"
              value={extra.name}
              maxLength={200}
              onChange={(e) => setExtra({ ...extra, name: e.target.value })}
            />
          </label>
          <label>
            数量
            <InputNumber
              min={0.01}
              max={1000000}
              value={extra.amount}
              onChange={(v) => setExtra({ ...extra, amount: v ?? 0 })}
            />
          </label>
          <label>
            单位
            <Input
              value={extra.unit}
              maxLength={30}
              onChange={(e) => setExtra({ ...extra, unit: e.target.value })}
            />
          </label>
          <label>
            分类
            <Select
              value={extra.type}
              options={[
                { value: "main", label: "主料" },
                { value: "side", label: "辅料" },
                { value: "seasoning", label: "调料" },
              ]}
              onChange={(v) => setExtra({ ...extra, type: v })}
            />
          </label>
        </div>
        <Button
          disabled={
            busy ||
            !extra.name.trim() ||
            !extra.unit.trim() ||
            extra.amount <= 0
          }
          onClick={async () => {
            if (
              await commit((s) => ({
                ...s,
                shoppingScopes: {
                  ...s.shoppingScopes,
                  [scope]: {
                    ...(s.shoppingScopes?.[scope] ?? saved),
                    manual: [
                      ...(s.shoppingScopes?.[scope] ?? saved).manual,
                      {
                        ...extra,
                        name: extra.name.trim(),
                        unit: extra.unit.trim(),
                        id: createUuid(),
                      },
                    ],
                  },
                },
              }))
            )
              setExtra({ name: "", amount: 1, unit: "个", type: "main" });
          }}
        >
          添加采购项
        </Button>
      </details>
      {allowReceive && (
        <Button
          disabled={busy || !selected.length}
          onClick={() => {
            setError("");
            setPurchases(
              selected.map((i) => ({
                id: createUuid(),
                name: i.name,
                unit: i.unit,
                amount: i.missing,
                expireDate: null,
              })),
            );
          }}
        >
          确认购买并入库（{selected.length} 项）
        </Button>
      )}
      {purchases && (
        <Modal
          rootClassName="kitchen-modal"
          open
          title="确认采购入库"
          okText="确认入库"
          cancelText="取消"
          confirmLoading={busy}
          onCancel={() => setPurchases(undefined)}
          onOk={async () => {
            if (
              purchases.some(
                (p) =>
                  !Number.isFinite(p.amount) ||
                  p.amount <= 0 ||
                  p.amount > 1000000,
              )
            ) {
              setError("请填写大于 0 的实际采购数量。");
              return;
            }
            const manualKeys = new Set(
              selected
                .filter((i) => i.key.startsWith("manual:"))
                .map((i) => i.key),
            );
            if (
              await commit((s) => ({
                ...receivePurchases(s, purchases),
                shoppingScopes: {
                  ...s.shoppingScopes,
                  [scope]: {
                    checked: [],
                    manual: (s.shoppingScopes?.[scope] ?? saved).manual.filter(
                      (i) => !manualKeys.has(`manual:${i.id}`),
                    ),
                  },
                },
              }))
            )
              setPurchases(undefined);
            else setError("入库未完成，内容已保留。请处理页面上的失败操作。");
          }}
        >
          <p>新增独立库存批次，未填写到期日的批次标记为日期未知。</p>
          {purchases.map((item, index) => (
            <fieldset className="kitchen-editor-item" key={item.id}>
              <legend>
                {item.name}（{item.unit}）
              </legend>
              <div className="kitchen-form-grid">
                <label>
                  实际采购数量
                  <InputNumber
                    aria-label={`${item.name}采购数量`}
                    min={0.01}
                    max={1000000}
                    value={item.amount}
                    onChange={(amount) =>
                      setPurchases(
                        purchases.map((p, i) =>
                          i === index ? { ...p, amount: amount ?? 0 } : p,
                        ),
                      )
                    }
                  />
                </label>
                <label>
                  到期日期
                  <Input
                    type="date"
                    aria-label={`${item.name}到期日期`}
                    value={item.expireDate ?? ""}
                    onChange={(e) =>
                      setPurchases(
                        purchases.map((p, i) =>
                          i === index
                            ? { ...p, expireDate: e.target.value || null }
                            : p,
                        ),
                      )
                    }
                  />
                </label>
              </div>
            </fieldset>
          ))}
        </Modal>
      )}
    </section>
  );
}
