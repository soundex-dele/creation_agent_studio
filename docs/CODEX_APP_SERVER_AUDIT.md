# 对话应用 app-server 适配状态

核对与修复日期：2026-09-27。依据：[官方 App Server 文档](https://developers.openai.com/codex/app-server/)及本机 `codex-cli 0.142.5` 导出的实验性 JSON Schema。下表描述当前工作区的实现；验证使用模拟协议、自动化测试和静态检查，未调用真实模型逐项验收。

## 本次已修复

| 能力 | 当前实现 |
| --- | --- |
| Plan 文档 | 接收 `item/plan/delta`，按 ID 聚合；`item/completed` 替换草稿。保存原始 item 类型和 `agentMessage.phase`，完成后独立展示计划文档。步骤进度与计划正文分开展示。 |
| 原请求提问和审批 | 等待用户时保留 app-server 进程、当前 attempt 和 lease；Run 命令经工作进程控制队列回复原 JSON-RPC ID，继续原 turn。支持多问题、秘密字段、实际提供的审批决策及规则对象。 |
| 失效与取消 | 消费 `serverRequest/resolved`；已失效请求不能再次授权。等待时续租，取消或超时终止工作进程，worker 丢失不自动重放授权。旧版本保存的审批不能批准新请求，需要重新发起。 |
| 细粒度权限 | 接入 `item/permissions/requestApproval`，显示申请内容，可按 turn/session 授予或拒绝；不能通过客户端扩大申请范围。网络审批展示服务端提供的目标信息。 |
| MCP 交互 | 接入 `mcpServer/elicitation/request`，支持常用 JSON Schema 表单、手动打开 URL、接受/拒绝/取消。服务端校验字段，禁止外部 schema 引用。表单答案不复制到聊天正文。 |
| 动态工具协议 | 新 thread 可通过适配器参数注册 `dynamicTools`；`item/tool/call` 调用注入的 `tool_handlers`，按协议返回结果。未注册工具明确失败。产品级工具注册管理界面仍未提供。 |
| 运行中补充指令 | 输入框增加“补充指令”，经持久化 `steer` 命令调用当前 thread 的 `turn/steer`，包含 `expectedTurnId`；保留停止操作。 |
| 步骤、工具输出和差异 | 展示 `turn/plan/updated`、命令输出增量、终端交互、MCP 进度、`patchUpdated`、`turn/diff/updated`。 |
| 告警及结构化错误 | 显示 warning/configWarning/error、模型路由等通知，保存最终错误详情。聊天隐藏 MCP 启动状态及模型元数据回退提示。 |
| 摘要与状态 | 只接入协议可公开的 reasoning summary，保留 review、上下文压缩、子 Agent 活动。实时 token 用量仍保存，但不在聊天中展示。原始推理内容不进入展示事件。 |
| 历史恢复 | `agent.*` 事件纳入 Run 快照及会话消息元数据，刷新与事件回放可以恢复展示信息。 |

## 实现位置

- `backend/core/agent_engine/adapters/codex.py`：JSON-RPC 原请求生命周期、turn 控制和事件桥接。
- `backend/core/agent_engine/adapters/codex_interactions.py`：请求展示数据、回复翻译和校验。
- `backend/modules/execution/application/live.py`、`commands.py`、`runtime/child.py`、`infrastructure/coordinator.py`：保留 lease 的交互等待和双向控制队列。
- `backend/modules/execution/application/agent_activity.py`、`event_retention.py`、`projections.py`：结构化事件、快照与历史投影。
- `frontend/src/components/Chat/AgentActivityPanel.tsx`、`McpRequestForm.tsx`、`MessageList.tsx`、`MessageInput.tsx`：聊天展示和交互入口。

## 仍属于后续扩展的能力

| 能力 | 当前边界 |
| --- | --- |
| Codex 原生历史补采和分支 | 使用项目自己的会话/Run 历史，未对接 thread/read、原生分页导入、fork、原生归档同步。已丢弃且从未保存的旧计划不能自动恢复。 |
| 模型与模式动态发现 | 仍使用项目模型配置，未对接 model/list、provider capabilities、collaborationMode/list。 |
| Codex 账号和额度管理 | 依赖运行环境的 Codex 配置/认证；未提供 account 登录、退出、额度、外部 token 刷新。实时 token 用量不等于账号额度。 |
| Skills/MCP/Apps 管理 | 保留现有 Skill 输入和 MCP 执行；未提供 Codex 技能目录同步、MCP OAuth/重载、connector 管理。 |
| 原生 Review/Goal/Hooks | 能展示已产生的 review/压缩 item，但未新增 review/start、goal 管理、主动压缩及 hook 生命周期控制。 |
| 聊天图片结果归档 | 普通聊天仍未将 Codex 生成图片的 savedPath 转为附件；AI 绘图应用已有独立归档实现。 |
| 高级输入与输出 | 未增加聊天 outputSchema、语音、原生终端/文件服务等独立产品入口。 |
| 动态工具与复杂表单 | dynamicTools 目前是适配器注入能力；复杂 JSON Schema 联合类型和引用不提供通用编辑器。URL 认证由用户在工具页面完成。 |
| 插件市场 | 未接入开发中的 plugin 管理方法。 |

本机 schema 的 121 种客户端请求、11 种服务端请求、68 种通知包含实验与兼容接口，不以未调用的接口数量衡量功能完成度。在线文档的 collabToolCall、thread/items/list 与本机 collabAgentToolCall、thread/turns/items/list 存在版本差异，部署时应使用匹配版本。

## 部署与验证

新增 `execution.0008_run_command_steer` 迁移。更新后执行项目虚拟环境中的 `python manage.py migrate`，并重启后端和 execution worker；新交互依赖更新后的双向 worker 协议。迁移不自动恢复旧进程或旧待审批请求。

回归覆盖原 ID 回复、拒绝扩大权限、过期请求、取消/超时、worker 丢失、运行中补充指令、MCP 类型校验、Plan 修订、结构化活动及会话持久化。前端通过类型检查、交互测试和 CSS 滚动契约检查。聊天仍由 `.chat-messages` 持有滚动；未使用应用内浏览器，也未宣称真机滚动已经验收。
