import { useState } from "react";
import { Alert, Button, InputNumber, Select } from "antd";
import type { KitchenState, Preferences } from "@/services/kitchenAssistant";
import { defaultPreferences } from "./domain";
export function PreferencesPanel({
  state,
  busy,
  commit,
}: {
  state: KitchenState;
  busy: boolean;
  commit: (change: (s: KitchenState) => KitchenState) => Promise<boolean>;
}) {
  const [value, setValue] = useState<Preferences>(
    state.preferences ?? { ...defaultPreferences, servings: state.servings },
  );
  const [saved, setSaved] = useState(false);
  const change = (patch: Partial<Preferences>) => {
    setValue((v) => ({ ...v, ...patch }));
    setSaved(false);
  };
  return (
    <section className="kitchen-card">
      <h2>家庭饮食偏好</h2>
      <p>自动推荐会排除避免食材；手动选菜仍可查看冲突并自行决定。</p>
      <div className="kitchen-form-grid">
        <label>
          默认人数
          <InputNumber
            aria-label="默认人数"
            value={value.servings}
            min={1}
            max={8}
            precision={0}
            onChange={(v) => v && change({ servings: v })}
          />
        </label>
        <label>
          单道菜用时上限（分钟）
          <InputNumber
            value={value.maxMinutes}
            min={1}
            max={1440}
            precision={0}
            onChange={(v) => v && change({ maxMinutes: v })}
          />
        </label>
        <label>
          避免食材
          <Select
            aria-label="避免食材"
            mode="tags"
            value={value.avoid}
            tokenSeparators={["，", ","]}
            onChange={(v) => change({ avoid: v })}
          />
        </label>
        <label>
          不喜欢的食材
          <Select
            mode="tags"
            value={value.dislike}
            tokenSeparators={["，", ","]}
            onChange={(v) => change({ dislike: v })}
          />
        </label>
        <label>
          可接受辣度
          <Select
            value={value.spicy}
            options={["不辣", "微辣", "中辣", "重辣"].map((label, value) => ({
              label,
              value,
            }))}
            onChange={(v) => change({ spicy: v })}
          />
        </label>
        <label>
          常用厨具
          <Select
            mode="tags"
            value={value.equipment}
            options={defaultPreferences.equipment
              .concat(["烤箱", "空气炸锅", "微波炉"])
              .map((value) => ({ value, label: value }))}
            onChange={(v) => change({ equipment: v })}
          />
        </label>
      </div>
      <Button
        type="primary"
        disabled={busy}
        onClick={async () => {
          if (
            await commit((s) => ({
              ...s,
              preferences: value,
              servings: s.cooking ? s.servings : value.servings,
            }))
          )
            setSaved(true);
        }}
      >
        保存偏好
      </Button>
      {saved && <Alert type="success" message="偏好已保存" />}
    </section>
  );
}
