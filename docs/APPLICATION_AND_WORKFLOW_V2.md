# Application、Agent、Skill 与 Workflow V2 模型

状态：提案（Proposed）

更新时间：2026-09-11

迁移前提：允许破坏性重构；本文定义 V2 目标模型，不兼容当前表结构

## 1. 核心原则

1. 稳定对象保存身份，Draft 保存编辑状态，Revision 保存不可变的可执行快照。
2. 任何 Run 只能引用 Revision，不能直接读取可变 Draft 或“最新对象”。
3. Deployment 是环境到 Revision 的原子指针；回滚只切换指针。
4. Application、Agent、Skill 与 Workflow 的引用均在发布时解析到具体 Revision。
5. Conversation 可跟随 Deployment，但每个 Turn 固定其实际 Revision snapshot。
6. WorkflowRevision 是不可变 DAG，Step 固定 ApplicationRevision。
7. V2 从空数据库建立，不保留旧 migration 链或旧对象 ID 的兼容语义。

## 2. 通用发布模型

```text
StableObject
├── Draft                         可变；同一对象每个编辑分支最多一个
├── Revision 1                    不可变
├── Revision 2                    不可变
└── Deployment
    ├── development -> Revision 2
    ├── staging     -> Revision 2
    └── production  -> Revision 1
```

所有 Revision 共有：

- `id: UUID`
- `organization_id`
- `object_id`
- `revision_no`，对象内单调递增
- `schema_version`
- `content_hash`，对规范化内容计算 SHA-256
- `created_by`, `created_at`
- `release_notes`

可变的可用性元数据单独保存在 `RevisionLifecycle`，包含
`availability: active | deprecated`。它不属于执行内容，也不参与 `content_hash`。

发布事务：

1. 锁定稳定对象和 Draft；
2. 校验 schema、引用、权限、循环依赖和租户一致性；
3. 将所有依赖解析为具体 Revision ID；
4. 规范化内容并计算 hash；
5. 创建 Revision 及只读子记录；
6. 写审计事件；
7. 可选地原子更新某环境 Deployment。

发布后禁止更新或删除 Revision 内容。`RevisionLifecycle.deprecated` 只影响新部署，不影响历史 Run。

## 3. Agent

### 3.1 数据模型

```text
Agent
├── AgentDraft
├── AgentRevision
│   ├── AgentRevisionSkill ──> SkillRevision
│   ├── AgentRevisionKnowledge ──> KnowledgeIndexRevision
│   └── AgentRevisionTool
└── AgentDeployment ──> AgentRevision
```

`Agent` 保存：名称、slug、所有者、分类、可见性和生命周期状态。

`AgentDraft`/`AgentRevision` 内容包括：

- system prompt 和 prompt 参数 schema；
- adapter key、模型选择规则和生成参数；
- 工具及其权限、网络和文件访问策略；
- 精确的 SkillRevision、KnowledgeIndexRevision 引用；
- 护栏、最大轮次、超时和费用上限；
- checkpoint capability：`none | turn_boundary | interactive`；
- 输出 schema 和 UI 展示元数据。

只有 `checkpoint_capability=interactive` 的 AgentRevision 可以在执行时请求用户输入。
发布校验必须实际执行 checkpoint round-trip contract test，而不能只相信配置声明。

### 3.2 Deployment 与 Turn

AgentDeployment 唯一键为 `(agent_id, environment)`，包含：

- `revision_id`
- `version`，每次指针或 override 变化时递增
- `previous_revision_id`
- `config_override`，只允许覆盖白名单运行参数，不能改变工具/Skill/Policy 边界
- `updated_by`, `updated_at`

Conversation 可以保存默认 `agent_deployment_id`。创建 Turn 时解析 Deployment，并将以下内容
固化到 Run `definition_snapshot`：

- AgentRevision ID/hash；
- 所有 SkillRevision 和 KnowledgeIndexRevision ID/hash；
- 实际 provider/model 参数；
- PolicyRevision/QuotaPolicyRevision；
- adapter binary/protocol version。

编辑 Agent 或切换 Deployment 不改变已经创建的 Turn 和 Run。

## 4. Skill

```text
Skill
├── SkillDraft
└── SkillRevision
```

SkillRevision 保存：

- `source_type: inline | git | artifact | builtin`
- `source_uri` 和不可变 source commit/digest；
- `artifact_key`、`content_hash`、`manifest`；
- 输入/输出 schema、所需工具和权限声明；
- 兼容的 Agent adapter/protocol 版本。

同步外部 Skill 时，同 slug 不覆盖历史内容，而是更新 Draft；显式发布后生成新 Revision。
若源是 Git，必须固定 commit SHA；若源是 artifact，必须固定内容 digest。

## 5. Application

### 5.1 数据模型

```text
Application
├── ApplicationDraft
├── ApplicationRevision
│   ├── ApplicationRevisionAgent ──> AgentRevision
│   ├── ApplicationRevisionSkill ──> SkillRevision
│   └── GuidedPromptRevision
│       └── GuidedQuestionRevision
│           └── GuidedOptionRevision
└── ApplicationDeployment ──> ApplicationRevision
```

Application 保存身份和市场元数据：名称、slug、图标、分类、所有者、可见性。

ApplicationRevision 保存完整运行契约：

- `kind: chat | task | custom`
- `renderer_key` 与 `renderer_schema_version`
- `executor_key` 与 `executor_protocol_version`
- `input_schema`, `output_schema`, `default_config`
- 固定 AgentRevision/SkillRevision 绑定和角色
- Guided Prompt 问题树
- 超时、重试、artifact、费用和权限策略

`renderer_key` 和 `executor_key` 必须来自部署时注册表；Revision 同时固定协议版本。删除实现前，
必须确认没有受保留策略保护的 Revision/Run 依赖该版本。

### 5.2 一个应用一个界面

前端 `ApplicationRuntime` 根据 `(renderer_key, renderer_schema_version)` 选择 renderer。
同一 ApplicationRevision 无论从应用页还是 Workflow Step 打开，都使用同一 renderer；Workflow
只额外注入只读的 `project_id`、`workflow_run_id`、`step_run_id` 和上游 artifact 上下文。

renderer 不能直接调用通用 API client 修改任意资源，只能使用 ApplicationRuntime 提供的：

- `startRun(input, idempotencyKey)`
- `subscribeRun(runId)`
- `sendCommand(runId, command)`
- `listArtifacts(runId)`
- `openProjectAsset(assetId)`

这样自定义界面不能绕过租户、Run 和权限边界。

### 5.3 Guided Prompt

Guided Prompt 是 ApplicationRevision 的不可变子树。问题支持：

- `text`, `single_select`, `multi_select`, `number`, `file`, `project_asset`
- 条件显示表达式；
- 必填、默认值和校验规则；
- 选项到结构化 input 字段的映射。

组装提示词不再使用独立的可变 slug 接口。客户端提交结构化答案到：

```text
POST /api/v2/organizations/{org}/application-revisions/{revision}/compose-input
```

服务端按该 Revision 的 schema 生成可审计的结构化 Run input；返回结果本身不启动 Run。

## 6. Workflow

### 6.1 数据模型

```text
Workflow
├── WorkflowDraft
└── WorkflowRevision
    ├── WorkflowStepRevision ──> ApplicationRevision
    └── WorkflowEdgeRevision

WorkflowDeployment ──> WorkflowRevision
WorkflowRun ──> WorkflowRevision
└── WorkflowStepRun ──> WorkflowStepRevision
    └── Run
```

WorkflowRevision 保存不可变 DAG。Step 包含：

- 固定 ApplicationRevision；
- 输入映射表达式；
- 超时和重试策略；
- 条件执行表达式；
- `failure_policy: fail_fast | continue | compensate`；
- 可选补偿 Step。

Edge 表达显式数据或控制依赖。发布时必须验证无环、所有引用同租户、输入映射满足下游
input schema、输出可序列化且补偿引用有效。

### 6.2 执行语义

1. 创建 WorkflowRun 时固定 WorkflowRevision 和顶层 input。
2. 编排器为依赖满足的 Step 创建一个 StepRun 和子 Run。
3. Step 输出通过结构化 output 或 RunArtifact 传递，不共享可变内存或工作目录。
4. 编排器消费 transactional outbox，并在锁定 WorkflowRun 后幂等推进 DAG。
5. `(workflow_run_id, step_revision_id, execution_index)` 唯一，防止重复投递创建重复 StepRun。
6. 重试创建新的 RunAttempt，不创建新的 StepRun；显式循环通过新的 `execution_index` 表达。

工作流中应用升级不会影响已发布 WorkflowRevision。要采用新 ApplicationRevision，必须更新 Draft、
重新验证并发布新的 WorkflowRevision。

## 7. Conversation

```text
Conversation
├── Turn ──> Run
│   ├── user Message
│   └── assistant/tool Messages
└── ConversationSkillPreference ──> SkillDeployment（仅作为下一 Turn 默认值）
```

- Conversation 保存标题、项目、默认 Agent/Application Deployment 和 UI 偏好。
- Turn 是一次不可变用户请求，固定实际 Agent/Application/Skill Revision snapshot。
- Message 追加写；流式 delta 只存在 RunEvent，完成后合并为最终 assistant Message。
- 切换 Conversation 默认 Agent/Skill 只影响下一 Turn。
- 重试 Turn 复用原 definition snapshot；“使用最新版重试”是创建新 Turn 的显式操作。
- 删除 Conversation 采用 tombstone + retention job，不同步删除仍受审计策略保护的 Run。

## 8. Template 与 Project

V2 不再保留独立的可执行 Template 概念：

- 纯内容模板作为 `ProjectBlueprint`/`ProjectBlueprintRevision`，归 `workspace` 所有；
- 可运行模板建模为 ApplicationRevision；
- 多步骤模板建模为 WorkflowRevision；
- marketplace 只引用这些稳定对象，不复制定义。

应用 ProjectBlueprint 时固定 BlueprintRevision，并创建 Project 与初始 Asset。Blueprint 后续发布
不会修改已创建 Project。

## 9. 标识符与 API 规则

写接口使用稳定对象 ID 进行编辑/发布，运行接口最终解析并返回 Revision ID：

- `agent_id`, `agent_revision_id`, `agent_deployment_id`
- `application_id`, `application_revision_id`, `application_deployment_id`
- `skill_id`, `skill_revision_id`
- `workflow_id`, `workflow_revision_id`, `workflow_deployment_id`

禁止使用 slug 作为数据库关系或 Run 的唯一执行标识。slug 只用于路由展示和检索，且作用域为
organization。

Application 控制面当前提供：

```text
GET|POST applications
GET      applications/{application}
GET|PUT  applications/{application}/draft
GET|POST applications/{application}/revisions
GET      applications/{application}/revisions/{revision}
GET      applications/{application}/deployments
GET|PUT  applications/{application}/deployments/{environment}
POST     applications/{application}/deployments/{environment}/rollback
```

`PUT draft` 是完整内容替换而不是 JSON merge patch；请求必须带 `expected_version`。首次创建
Deployment 使用 `expected_version: 0`，以后每次切换或回滚都比较当前版本。相同 Draft 内容再次
发布返回既有 Revision，不产生新的 revision number。生产环境的切换和回滚要求 Admin 或 Owner。

所有绑定必须同时满足：

- organization 相同；
- Revision 已发布且未损坏；
- schema/protocol 兼容；
- 调用者具有引用和执行权限。

## 10. 数据库约束

- 所有核心 model、field、unique/check constraint 和 migration 必须同时支持 SQLite 3.35+
  与 PostgreSQL；数据库专属优化不得进入 domain/application 层。
- Revision 表的 `(object_id, revision_no)` 和 `(object_id, content_hash)` 唯一。
- 数据库触发器拒绝 Revision 可执行字段及其子表的 UPDATE/DELETE；可用性仅能通过
  `RevisionLifecycle` 修改。PostgreSQL 和 SQLite 分别提供等价 trigger，retention 清理使用
  独立受控入口。
- Deployment 更新使用行锁和乐观 `version`，同时保存 previous revision。
- 所有租户表 `organization_id NOT NULL`，关键关系使用包含 organization 的复合约束。
- Draft 可以覆盖更新，但发布事务必须比较 `draft.version`，防止丢失并发编辑。
- JSON 配置在 application 层使用版本化 Pydantic schema 校验；数据库保存 `schema_version`。

## 11. 破坏性重建

- 删除当前 Application、Agent、Skill、Template 和 Workflow 的旧迁移语义。
- V2 使用新的 app labels、表名和可在 SQLite/PostgreSQL 上运行的 initial migration。
- 默认不迁移旧对象、绑定、Conversation 或 WorkflowRun。
- 内置 Agent、Application、Skill 和 Blueprint 通过确定性 seed 创建，seed 内容带固定 hash。
- 如需保留文件，只导入 object storage manifest 并重新创建 Asset；不复用客户端提交的绝对路径。
- 回滚只能整体恢复 V1 代码和数据库备份，V2 Revision 不回写 V1。

## 12. 验收标准

- 发布后的 Revision 和绑定无法被普通应用角色修改或删除。
- 修改 Draft 不改变任何已创建 Run 的 definition snapshot。
- Deployment 切换后，新 Run 使用新 Revision，旧 Run 和重试仍使用旧 Revision。
- Skill 外部源变化只更新 Draft，不静默改变 AgentRevision。
- Agent 只有通过 checkpoint round-trip 测试才能发布为 interactive。
- Workflow 发布能拒绝环、跨租户引用和不兼容输入映射。
- 编排器重复消费同一 outbox event 不会创建重复 StepRun。
- 同一 ApplicationRevision 在独立页面和 Workflow 中使用相同 renderer/protocol。
- Conversation 切换默认能力只影响下一 Turn。
- 空 SQLite 文件和空 PostgreSQL database 均可通过 initial migration 和 seed 确定性重建
  全部内置 Revision。
