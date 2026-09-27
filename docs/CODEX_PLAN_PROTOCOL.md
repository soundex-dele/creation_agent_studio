# 对话应用的 Codex Plan 协议

依据：[OpenAI App Server 文档](https://developers.openai.com/codex/app-server/)。
本地核对版本：`codex-cli 0.142.5`，使用
`codex app-server generate-json-schema --experimental --out <临时目录>`
导出的 `PlanDeltaNotification` 和 `ItemCompletedNotification` schema。

## 输入与输出

- 切换 Plan 模式后，`turn/start.collaborationMode.mode` 为 `plan`。
- 客户端初始化已开启 `capabilities.experimentalApi`，接收实验性的计划消息。
- 计划文档是 `type: "plan"`、`id`、`text` 组成的消息项，不保证产生磁盘上的 `plan.md` 文件。
- `item/plan/delta` 带有 `threadId`、`turnId`、`itemId`、`delta`，用于逐步展示计划正文。
- `item/completed` 的完整 `plan.text` 是最终内容，可能不同于之前的增量拼接结果，必须替换草稿。
- `turn/plan/updated` 是 `{step, status}` 步骤进度列表，不是 Plan 模式的计划文档。

## 项目内的映射

`backend/core/agent_engine/adapters/codex.py` 按消息类型和 ID 保存文本项，
按出现顺序合并说明与计划。追加文本发送 `output.delta`；最终文本修订发送
`output.snapshot`。只收到完成消息、没有增量的情况也会产生完整输出。

`execute_agent_completion` 将最终正文写入 Run 的 `result`，会话投影保存到
助手消息的 `content`。`agent.item` 同时保存消息类型、ID、阶段和最终正文，
前端生成中显示正文，完成后独立渲染“计划文档”；刷新时从会话历史读取。
计划与普通消息共用 `.chat-messages` 滚动区域，不新增文档级滚动容器。

## 回归覆盖

- 计划增量、最终修订、缺少增量、重复完成、多消息项、取消时的部分正文。
- 模拟 app-server 通知，经真实适配器、Run 执行和会话投影后，从历史接口读取计划。
- 前端从草稿切换到最终快照，并在任务完成后恢复已保存的正文。

已丢弃且未持久化的旧计划不会由本次修复自动补回。
