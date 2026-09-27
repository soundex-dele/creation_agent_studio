import { useEffect, useState } from "react";
import { Alert, Button, Form, Input, InputNumber, Modal, Select } from "antd";
import type {
  CookingRecord,
  CookingStep,
  Ingredient,
  Inventory,
  Recipe,
} from "@/services/kitchenAssistant";

const newIngredient = (): Ingredient => ({
  id: crypto.randomUUID(),
  name: "",
  amount: 1,
  unit: "个",
  type: "main",
});
const newStep = (): CookingStep => ({
  id: crypto.randomUUID(),
  title: "",
  description: "",
  phase: "cook",
  durationMinutes: 0,
  heatLevel: "中火",
  ingredientIds: [],
  mediaUrls: [],
});
export function RecipeEditor({
  recipe,
  onClose,
  onSave,
  draftKey = "",
  missing = [],
}: {
  draftKey?: string;
  missing?: string[];
  recipe?: Recipe;
  onClose: () => void;
  onSave: (recipe: Recipe) => Promise<boolean>;
}) {
  const [draft] = useState(() => {
    try {
      return draftKey
        ? (JSON.parse(localStorage.getItem(draftKey) ?? "null") as {
            values: Partial<Recipe>;
            ingredients: Ingredient[];
            steps: CookingStep[];
          } | null)
        : null;
    } catch {
      return null;
    }
  });
  const [dirty, setDirty] = useState(false);
  const [form] = Form.useForm();
  const [id] = useState(() => recipe?.id ?? crypto.randomUUID());
  const [ingredients, setIngredients] = useState<Ingredient[]>(
    () =>
      (draft?.ingredients ?? recipe?.ingredients)?.map((i) => ({ ...i })) ?? [
        newIngredient(),
      ],
  );
  const [steps, setSteps] = useState<CookingStep[]>(
    () =>
      (draft?.steps ?? recipe?.steps)?.map((s) => ({
        ...s,
        ingredientIds: [...s.ingredientIds],
      })) ?? [newStep()],
  );
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const values = Form.useWatch([], form);
  useEffect(() => {
    if (!draftKey) return;
    const timer = window.setTimeout(() => {
      try {
        localStorage.setItem(
          draftKey,
          JSON.stringify({ values: form.getFieldsValue(), ingredients, steps }),
        );
      } catch {
        setError("本机草稿保存失败，请保持编辑页面打开并及时保存菜谱。");
      }
    }, 400);
    return () => window.clearTimeout(timer);
  }, [values, ingredients, steps, draftKey, form]);
  const close = () => {
    if (dirty || draft)
      Modal.confirm({
        title: "保留草稿并离开？",
        content: "填写内容会保存在当前账号的本机草稿中。",
        okText: "保留并离开",
        cancelText: "继续编辑",
        onOk: () => {
          try {
            if (draftKey)
              localStorage.setItem(
                draftKey,
                JSON.stringify({
                  values: form.getFieldsValue(),
                  ingredients,
                  steps,
                }),
              );
          } catch {
            setError("本机草稿保存失败，请先保存菜谱后再离开。");
            return Promise.reject(new Error("草稿未保存"));
          }
          onClose();
        },
      });
    else onClose();
  };
  const changeIngredient = (id: string, patch: Partial<Ingredient>) =>
    setIngredients((items) =>
      items.map((i) => (i.id === id ? { ...i, ...patch } : i)),
    );
  const changeStep = (id: string, patch: Partial<CookingStep>) =>
    setSteps((items) =>
      items.map((i) => (i.id === id ? { ...i, ...patch } : i)),
    );
  function move<T>(items: T[], index: number, delta: number): T[] {
    const result = [...items];
    [result[index], result[index + delta]] = [
      result[index + delta],
      result[index],
    ];
    return result;
  }
  const save = async () => {
    try {
      const values = await form.validateFields();
      if (
        !ingredients.length ||
        ingredients.some(
          (i) =>
            !i.name.trim() ||
            !i.unit.trim() ||
            !Number.isFinite(i.amount) ||
            i.amount < 0 ||
            i.amount > 1000000,
        )
      )
        throw new Error("请填写每项食材的名称、有效数量和单位。");
      if (
        !steps.length ||
        steps.some(
          (s) =>
            !s.title.trim() ||
            !s.description.trim() ||
            !s.heatLevel.trim() ||
            !Number.isInteger(s.durationMinutes) ||
            s.durationMinutes < 0 ||
            s.durationMinutes > 1440,
        )
      )
        throw new Error("请填写每个步骤的标题、做法和火候。");
      const now = new Date().toISOString();
      setSaving(true);
      setError("");
      if (
        await onSave({
          ...recipe,
          ...values,
          id,
          ingredients: ingredients.map((i) => ({
            ...i,
            name: i.name.trim(),
            unit: i.unit.trim(),
          })),
          steps,
          tips: String(values.tips ?? "")
            .split("\n")
            .filter(Boolean),
          mealTimes: values.mealTimes ?? ["中", "晚"],
          source: recipe?.source ?? "手动整理",
          createdAt: recipe?.createdAt ?? now,
          updatedAt: now,
        })
      ) {
        try {
          if (draftKey) localStorage.removeItem(draftKey);
        } catch {
          /* Saving does not depend on local storage. */
        }
        onClose();
      } else
        setError(
          "保存失败，填写内容已保留。可重试，或关闭弹窗后处理页面上的同步冲突。",
        );
    } catch (err) {
      if (err instanceof Error) setError(err.message);
    } finally {
      setSaving(false);
    }
  };
  return (
    <section className="kitchen-editor-view">
      <div className="kitchen-section-heading">
        <h2>{recipe ? "编辑菜谱" : "添加菜谱"}</h2>
        <div className="kitchen-actions">
          <Button onClick={close}>返回</Button>
          <Button type="primary" loading={saving} onClick={() => void save()}>
            保存菜谱
          </Button>
        </div>
      </div>
      {draft && <Alert type="info" message="已恢复本机草稿" />}
      {missing.length > 0 && (
        <Alert
          type="warning"
          message={`AI 未能确认以下信息，请核对原文并补充：${missing.map((key) => (key === "servings" ? "原方人数" : key === "durationMinutes" ? "总用时" : key.startsWith("ingredients.") ? `食材 ${Number(key.split(".")[1]) + 1} 的${key.endsWith(".amount") ? "数量" : "单位"}` : key.startsWith("steps.") ? `步骤 ${Number(key.split(".")[1]) + 1} 的用时` : "菜谱信息")).join("、")}`}
        />
      )}
      <div onChange={() => setDirty(true)} onClick={() => setDirty(true)}>
        {error && <Alert type="error" showIcon message={error} />}
        <Form
          form={form}
          layout="vertical"
          onValuesChange={() => setDirty(true)}
          initialValues={
            draft?.values ??
            (recipe
              ? { ...recipe, tips: recipe.tips.join("\n") }
              : {
                  category: "主菜",
                  difficulty: "简单",
                  servings: 2,
                  durationMinutes: 15,
                  intro: "",
                  tips: "",
                  mealTimes: ["中", "晚"],
                  spicy: 0,
                  equipment: [],
                  tags: [],
                })
          }
        >
          <Form.Item
            name="name"
            label="菜名"
            rules={[{ required: true, whitespace: true }]}
          >
            <Input maxLength={200} />
          </Form.Item>
          <div className="kitchen-form-grid">
            <Form.Item
              name="category"
              label="分类"
              rules={[{ required: true }]}
            >
              <Select
                options={[
                  "早餐",
                  "主菜",
                  "荤菜",
                  "蔬菜",
                  "青菜",
                  "汤类",
                  "主食",
                  "其他",
                ].map((value) => ({ value, label: value }))}
              />
            </Form.Item>
            <Form.Item name="difficulty" label="难度">
              <Select
                options={["简单", "中等", "复杂"].map((value) => ({
                  value,
                  label: value,
                }))}
              />
            </Form.Item>
            <Form.Item
              name="servings"
              label="原方人数"
              rules={[{ required: true }]}
            >
              <InputNumber min={1} max={8} precision={0} />
            </Form.Item>
            <Form.Item
              name="durationMinutes"
              label="总用时（分钟）"
              rules={[{ required: true }]}
            >
              <InputNumber min={1} max={1440} precision={0} />
            </Form.Item>
          </div>
          <div className="kitchen-form-grid">
            <Form.Item
              name="mealTimes"
              label="适用餐次"
              rules={[{ required: true }]}
            >
              <Select
                mode="multiple"
                options={[
                  { value: "早", label: "早餐" },
                  { value: "中", label: "午餐" },
                  { value: "晚", label: "晚餐" },
                ]}
              />
            </Form.Item>
            <Form.Item name="spicy" label="辣度">
              <Select
                options={["不辣", "微辣", "中辣", "重辣"].map(
                  (label, value) => ({ label, value }),
                )}
              />
            </Form.Item>
            <Form.Item name="equipment" label="所需厨具">
              <Select
                mode="tags"
                options={[
                  "炒锅",
                  "汤锅",
                  "蒸锅",
                  "电饭煲",
                  "平底锅",
                  "烤箱",
                ].map((value) => ({ value, label: value }))}
              />
            </Form.Item>
            <Form.Item name="tags" label="自定义标签">
              <Select mode="tags" tokenSeparators={["，", ","]} />
            </Form.Item>
          </div>
          <Form.Item name="intro" label="简介">
            <Input.TextArea rows={2} maxLength={10000} />
          </Form.Item>
          <h3>食材</h3>
          {ingredients.map((item, index) => (
            <fieldset key={item.id} className="kitchen-editor-item">
              <legend>食材 {index + 1}</legend>
              <div className="kitchen-form-grid">
                <label>
                  名称
                  <Input
                    aria-label={`食材${index + 1}名称`}
                    value={item.name}
                    maxLength={200}
                    onChange={(e) =>
                      changeIngredient(item.id, { name: e.target.value })
                    }
                  />
                </label>
                <label>
                  数量
                  <InputNumber
                    aria-label={`食材${index + 1}数量`}
                    min={0}
                    max={1000000}
                    value={item.amount}
                    onChange={(value) =>
                      changeIngredient(item.id, { amount: value ?? NaN })
                    }
                  />
                </label>
                <label>
                  单位
                  <Input
                    aria-label={`食材${index + 1}单位`}
                    value={item.unit}
                    maxLength={30}
                    onChange={(e) =>
                      changeIngredient(item.id, { unit: e.target.value })
                    }
                  />
                </label>
                <label>
                  类型
                  <Select
                    aria-label={`食材${index + 1}类型`}
                    value={item.type}
                    onChange={(type) => changeIngredient(item.id, { type })}
                    options={[
                      { value: "main", label: "主料" },
                      { value: "side", label: "辅料" },
                      { value: "seasoning", label: "调料" },
                    ]}
                  />
                </label>
              </div>
              <div className="kitchen-actions">
                <Button
                  disabled={index === 0}
                  onClick={() => setIngredients(move(ingredients, index, -1))}
                >
                  上移食材
                </Button>
                <Button
                  disabled={index === ingredients.length - 1}
                  onClick={() => setIngredients(move(ingredients, index, 1))}
                >
                  下移食材
                </Button>
                <Button
                  danger
                  onClick={() => {
                    setIngredients(ingredients.filter((i) => i.id !== item.id));
                    setSteps(
                      steps.map((s) => ({
                        ...s,
                        ingredientIds: s.ingredientIds.filter(
                          (id) => id !== item.id,
                        ),
                      })),
                    );
                  }}
                >
                  删除食材
                </Button>
              </div>
            </fieldset>
          ))}
          <Button
            disabled={ingredients.length >= 100}
            onClick={() => setIngredients([...ingredients, newIngredient()])}
          >
            添加食材行
          </Button>
          <h3>制作步骤</h3>
          {steps.map((step, index) => (
            <fieldset key={step.id} className="kitchen-editor-item">
              <legend>步骤 {index + 1}</legend>
              <label>
                标题
                <Input
                  aria-label={`步骤${index + 1}标题`}
                  maxLength={200}
                  value={step.title}
                  onChange={(e) =>
                    changeStep(step.id, { title: e.target.value })
                  }
                />
              </label>
              <label>
                具体做法
                <Input.TextArea
                  aria-label={`步骤${index + 1}做法`}
                  rows={3}
                  maxLength={10000}
                  value={step.description}
                  onChange={(e) =>
                    changeStep(step.id, { description: e.target.value })
                  }
                />
              </label>
              <div className="kitchen-form-grid">
                <label>
                  阶段
                  <Select
                    aria-label={`步骤${index + 1}阶段`}
                    value={step.phase}
                    options={[
                      { value: "prep", label: "备菜" },
                      { value: "cook", label: "烹饪" },
                      { value: "finish", label: "出锅" },
                    ]}
                    onChange={(phase) => changeStep(step.id, { phase })}
                  />
                </label>
                <label>
                  分钟
                  <InputNumber
                    aria-label={`步骤${index + 1}分钟`}
                    min={0}
                    max={1440}
                    precision={0}
                    value={step.durationMinutes}
                    onChange={(value) =>
                      changeStep(step.id, { durationMinutes: value ?? 0 })
                    }
                  />
                </label>
                <label>
                  火候
                  <Input
                    aria-label={`步骤${index + 1}火候`}
                    maxLength={100}
                    value={step.heatLevel}
                    onChange={(e) =>
                      changeStep(step.id, { heatLevel: e.target.value })
                    }
                  />
                </label>
              </div>
              <label>
                本步用到的食材
                <Select
                  mode="multiple"
                  aria-label={`步骤${index + 1}食材`}
                  value={step.ingredientIds}
                  options={ingredients.map((i) => ({
                    value: i.id,
                    label: i.name || "未命名食材",
                  }))}
                  onChange={(ingredientIds) =>
                    changeStep(step.id, { ingredientIds })
                  }
                  placeholder="选择本步骤需要的食材"
                />
              </label>
              <div className="kitchen-actions">
                <Button
                  disabled={index === 0}
                  onClick={() => setSteps(move(steps, index, -1))}
                >
                  上移步骤
                </Button>
                <Button
                  disabled={index === steps.length - 1}
                  onClick={() => setSteps(move(steps, index, 1))}
                >
                  下移步骤
                </Button>
                <Button
                  danger
                  onClick={() =>
                    setSteps(steps.filter((s) => s.id !== step.id))
                  }
                >
                  删除步骤
                </Button>
              </div>
            </fieldset>
          ))}
          <Button
            disabled={steps.length >= 100}
            onClick={() => setSteps([...steps, newStep()])}
          >
            添加步骤
          </Button>
          <Form.Item name="tips" label="小贴士（每行一条）">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </div>
    </section>
  );
}
export function InventoryEditor({
  item,
  onClose,
  onSave,
}: {
  item?: Inventory;
  onClose: () => void;
  onSave: (item: Inventory) => Promise<boolean>;
}) {
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const save = async () => {
    try {
      const values = await form.validateFields();
      setSaving(true);
      if (
        await onSave({
          ...values,
          id: item?.id ?? crypto.randomUUID(),
          expireDate: values.expireDate || null,
        })
      )
        onClose();
      else setError("保存失败，请查看页面错误提示后重试。");
    } finally {
      setSaving(false);
    }
  };
  return (
    <Modal
      open
      title={item ? "编辑库存" : "添加食材"}
      onCancel={onClose}
      onOk={() => void save().catch(() => {})}
      confirmLoading={saving}
      okText="保存"
      cancelText="取消"
    >
      {error && <Alert type="error" message={error} />}
      <Form
        form={form}
        layout="vertical"
        initialValues={item ?? { amount: 1, unit: "个", category: "蔬果" }}
      >
        <Form.Item
          name="name"
          label="食材名称"
          rules={[{ required: true, whitespace: true }]}
        >
          <Input maxLength={200} />
        </Form.Item>
        <div className="kitchen-form-grid">
          <Form.Item name="amount" label="数量" rules={[{ required: true }]}>
            <InputNumber min={0} max={1000000} />
          </Form.Item>
          <Form.Item
            name="unit"
            label="单位"
            rules={[{ required: true, whitespace: true }]}
          >
            <Input maxLength={30} />
          </Form.Item>
        </div>
        <Form.Item
          name="category"
          label="分类"
          rules={[{ required: true, whitespace: true }]}
        >
          <Input maxLength={50} />
        </Form.Item>
        <Form.Item name="location" label="存放位置" initialValue="常温">
          <Select
            options={["冷藏", "冷冻", "常温"].map((value) => ({
              value,
              label: value,
            }))}
          />
        </Form.Item>
        <Form.Item name="expireDate" label="到期日期（可选）">
          <Input type="date" />
        </Form.Item>
      </Form>
    </Modal>
  );
}
export function RecordEditor({
  item,
  onClose,
  onSave,
}: {
  item: CookingRecord;
  onClose: () => void;
  onSave: (item: CookingRecord) => Promise<boolean>;
}) {
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  return (
    <Modal
      open
      title="这顿饭怎么样？"
      onCancel={onClose}
      okText="保存"
      cancelText="取消"
      confirmLoading={saving}
      onOk={() => {
        void form
          .validateFields()
          .then(async (values) => {
            setSaving(true);
            if (await onSave({ ...item, ...values })) onClose();
            else setError("保存失败，请稍后重试。");
          })
          .catch(() => {})
          .finally(() => setSaving(false));
      }}
    >
      {error && <Alert type="error" message={error} />}
      <p>{item.recipeNames.join("、")}</p>
      <Form form={form} layout="vertical" initialValues={item}>
        <Form.Item
          name="rating"
          label="评分（0 表示未评分）"
          rules={[{ required: true }]}
        >
          <InputNumber min={0} max={5} precision={0} />
        </Form.Item>
        <Form.Item name="tasteNotes" label="口味与心得">
          <Input.TextArea rows={4} maxLength={10000} />
        </Form.Item>
      </Form>
    </Modal>
  );
}
