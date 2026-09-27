import { useEffect, useState } from "react";
import { Alert, Checkbox, Modal, Spin } from "antd";
import type {
  KitchenState,
  Recipe,
  kitchenApi,
} from "@/services/kitchenAssistant";
export function CatalogPicker({
  service,
  state,
  busy,
  commit,
  onClose,
}: {
  service: ReturnType<typeof kitchenApi>;
  state: KitchenState;
  busy: boolean;
  commit: (change: (s: KitchenState) => KitchenState) => Promise<boolean>;
  onClose: () => void;
}) {
  const [recipes, setRecipes] = useState<Recipe[]>();
  const [checked, setChecked] = useState<string[]>([]);
  const [error, setError] = useState("");
  useEffect(() => {
    let alive = true;
    service
      .catalog()
      .then((r) => alive && setRecipes(r))
      .catch(() => alive && setError("精选菜谱加载失败，请关闭后重试。"));
    return () => {
      alive = false;
    };
  }, [service]);
  const exists = (r: Recipe) =>
    state.recipes.some((v) => v.catalogId === r.catalogId || v.id === r.id);
  return (
    <Modal
      open
      title="添加精选家常菜 · 30 道"
      width={800}
      onCancel={onClose}
      okText={`添加 ${checked.length} 道`}
      confirmLoading={busy}
      okButtonProps={{
        disabled:
          !checked.length || state.recipes.length + checked.length > 500,
      }}
      onOk={async () => {
        if (
          await commit((s) => ({
            ...s,
            recipes: [
              ...s.recipes,
              ...(recipes ?? []).filter(
                (r) =>
                  checked.includes(r.id) &&
                  !s.recipes.some(
                    (v) => v.catalogId === r.catalogId || v.id === r.id,
                  ),
              ),
            ],
          }))
        )
          onClose();
      }}
    >
      <p>选择后添加到自己的菜谱库，已有菜谱不会被覆盖。</p>
      {error && <Alert type="error" message={error} />}
      {!recipes && !error && <Spin />}
      {recipes && (
        <>
          <Checkbox
            checked={recipes
              .filter((r) => !exists(r))
              .every((r) => checked.includes(r.id))}
            onChange={(e) =>
              setChecked(
                e.target.checked
                  ? recipes.filter((r) => !exists(r)).map((r) => r.id)
                  : [],
              )
            }
          >
            全选可添加菜谱
          </Checkbox>
          <div className="kitchen-recipes">
            {recipes.map((r) => (
              <label className="kitchen-card" key={r.id}>
                <Checkbox
                  disabled={exists(r)}
                  checked={checked.includes(r.id)}
                  onChange={(e) =>
                    setChecked(
                      e.target.checked
                        ? [...checked, r.id]
                        : checked.filter((id) => id !== r.id),
                    )
                  }
                >
                  {r.name}
                  {exists(r) ? " · 已添加" : ""}
                </Checkbox>
                <p>
                  {r.category} · {r.durationMinutes} 分钟 ·{" "}
                  {r.equipment?.join("、")}
                </p>
              </label>
            ))}
          </div>
        </>
      )}
      {state.recipes.length + checked.length > 500 && (
        <Alert type="warning" message="超过 500 道菜谱上限，请减少选择。" />
      )}
    </Modal>
  );
}
