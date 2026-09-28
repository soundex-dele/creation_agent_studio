# 创作表单模板与品牌资料

创作应用的引导表单和工作流节点使用同一套内置模板及个人模板。

参数按字段合并：**本次明确输入 / 显式工作流映射 > 品牌资料 > 模板 > 应用默认值**。选择模板不标记手动覆盖，切换模板保留本次输入；“恢复继承”移除该字段的手动覆盖。明确清空必填字段会报错，不会自动退回模板值。

## 使用

- 在表单顶部选择“内置模板”或“我的模板”。生成的提示词是本次参数与品牌资料合并后的结果。
- “另存为模板”默认勾选创作偏好，可主动勾选主题或正文；品牌继承值、文件和路径不保存。“管理我的模板”支持编辑和删除。
- 工作流节点保存选用时的模板内容。修改、删除个人模板不会影响已有工作流；重新选择模板可更新节点快照。
- 自动工作流和手动工作流均在开始前选择本次品牌资料，可逐节点继承、替换或停用。品牌不写入共享流程；本次运行与节点重跑使用已解析的品牌快照。
- 模板列表按当前组织、用户、应用和表单隔离。将个人模板用于共享流程时，保存的参数快照作为流程配置对流程读者可见；私人品牌资料仅存于本人运行记录。

## 配置与接口

`guided_prompts[].presets` 包含 `id`、`name`、`description`、`order`、`values`。问题可配置 `preset_save: preference | optional | never`；未配置时推断主题/正文为可选，其余为偏好，文件字段不可保存。模板值必须符合当前表单字段、类型和枚举。

在已有 `/api/v1/apps/{slug}/` 下新增：

- `GET/POST form-presets/`：列出或创建本人模板；查询参数 `prompt_key` 可限定表单。
- `PATCH/DELETE form-presets/{uuid}/`：编辑或删除本人模板。
- `POST compose-prompt/`：增加可选的 `preset: {kind: builtin | personal, id}`；`explicit_fields` 表示真正的手动覆盖。响应增加 `effective_answers` 和 `field_sources`。
- `GET workflow-form-context/?run_id=…&step_key=…`：取得本人手动运行的冻结表单、模板及品牌。预览可传 `workflow_context: {run_id, step_key}`，以及 `use_workflow_preset` / `use_workflow_brand` 控制是否继续继承。

工作流节点使用独立的 `config.form_preset`；保存时新选择只需传 `kind`、`id`，后端验证权限并保存包含名称、`prompt_key`、`values` 的快照。再次保存未改变的快照不会依赖源模板是否仍存在。

工作流 `start/` 和 `manual-session/` 的新建请求接受 `brand_context: {reference, nodes}`；节点项为 `{mode: inherit | disabled | override, reference?}`，引用格式沿用品牌资料库。自动启动可传 `explicit_input_fields`，区分启动表单默认值与本次编辑。旧调用不传这些字段仍然可用。

## 部署与检查

先部署代码并执行数据库迁移，再通过现有应用中心同步命令更新目标组织的应用配置。命令从仓库根目录执行；Windows 使用对应项目虚拟环境解释器。

```sh
backend/.venv/bin/python backend/manage.py migrate
backend/.venv/bin/python backend/manage.py sync_app_center --organization <组织UUID> --package <应用slug>
```

需同步的应用：`wechat-viral-topics`、`wechat-viral-article`、`write-image-text-copy`、`write-short-video-copy`、`html-cover-generator`、`article-html-illustrator`、`gzh-design`、`wechat-html-optimizer`、`markdown-to-html`、`html-to-paged-cards`、`copy-to-jianying`。

自动测试覆盖权限隔离、优先级、模板保存、运行快照、品牌恢复及前端交互。CSS 回归检查覆盖手机、桌面和嵌入页面的高度与滚动约束；这些检查不等同于真实浏览器或设备视觉验证。
