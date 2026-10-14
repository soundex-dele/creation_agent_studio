# 项目宣传助手

`project-promotion` 是个人私有工作区：案例素材 → 选题 → 各渠道文案版本 → 人工发布 → 反馈复盘。
账号之间隔离，组织管理员不能读取其他用户的记录、生成结果或 Run 事件。

## 使用流程

1. 填写项目绝对路径，让 AI 探索源码和文档并生成案例；也可新建案例或粘贴开发记录。支持记录截图、视频、网盘与资料的 HTTP(S) 链接和说明，链接不会自动抓取。
2. 补齐目标读者、问题、方案、已实现能力与证据，然后确认案例。演示案例与真实客户案例分开，未来扩展另列。
3. 手动或 AI 策划选题，编辑确认后分别准备公众号、小红书、抖音、朋友圈任务。
4. 生成结果先进入生成记录，加入草稿后才成为可编辑版本。保存新版本不会覆盖旧版本，确认一个版本后再登记发布时间和链接。
5. 手动登记各作品最新累计指标和匿名咨询问题；未知数据留空，未知来源不关联作品。复盘采用每条作品观察日期最新的记录，不把多次累计数相加，不推断来源或跨平台排名。

品牌资料沿用品牌资料库的私有选择器、权限校验和来源快照，仅带入明确选择的产品与范文。
所有 AI 生成调用统一 Run 与系统模型引擎，失败不改变已保存记录。模型结果仍需人工核实，提示约束与来源快照不构成自动事实核验。
模型服务繁忙时会在同一任务内自动重试两次，等待期间仍可取消；不会切换模型或重复创建案例。
繁忙、认证、额度、超时、JSON 格式与案例字段/证据校验错误分别提示，任务保留错误分类供排查。

## 从项目路径生成案例

在素材库填写**后端和执行 worker 所在机器**上的项目绝对路径，可补充探索方向并选择品牌资料。
当前支持有提交记录的 Git 工作区，读取时包含未提交修改与未忽略的新文件。服务运行环境的 PATH 需要包含 Git。
普通用户只能读取自己的工作区；平台管理员遵循系统已有路径策略，不因本应用扩大读取范围。

复用源码讲解应用的只读快照与自主探索器：AI 可以列目录、搜索、阅读源码片段并自行结束探索；
不执行项目代码。Git 忽略文件、凭据文件、依赖目录、二进制、符号链接等按现有读取器规则排除，沿用其文件数量和文本容量限制。
源码和文档片段会传入系统配置的模型。生成记录展示当前阶段，探索期间可以取消；失败或取消不修改已有案例。

结果为 1–6 条不同场景的待审核演示案例，每条保留文件路径、行号、当时原文、文件 SHA256、基准提交与探索覆盖范围。
“加入可编辑草稿”一次保存整组案例，重复点击不会重复创建。只读来源快照在后续编辑或项目文件变化后仍保留。
仅有文档、测试或类型声明的引用不能填写已实现能力；仍需人工检查源码是否真实支持表述，并补充演示产出。
静态阅读不证明功能已部署、实测有效或收益成立，不会伪造截图、客户评价或效果数字。

## 与已有创作应用交接

版本编辑器可以把固定版本带入用户可运行的图文、短视频、公众号写作或公众号排版应用。
目标表单草稿保存在服务器，用户核对参数后使用原应用的 Skill 和对话流程。创建的会话与交接记录关联。
从交接记录选择已成功完成的助手回复回存为新版本；不会更换已确认发布版本。普通创作回复回存到正文，用户可拆分到逐页文案或脚本字段。
排版回复包含 HTML 正文或 HTML 代码块时支持回存；仅提供文件链接时，在版本编辑器粘贴实际 HTML 内容。
HTML 仅作为文本编辑和下载，应用不直接渲染。创作应用的 Skill 与执行环境需按各自文档配置。

## 接口与数据

前缀：`/api/v1/organizations/{organization_id}/applications/{application_id}/project-promotion`。
单租户沿用平台提供的无组织前缀别名。

- `GET/POST /cases|topics|channels|feedback`；`GET/PATCH /{resource}/{uuid}`。列表每页 50 条，用 `page` 分页；PATCH 必须带当前 `revision`，冲突返回 409。归档可恢复。
- `GET/POST /channels/{uuid}/versions`；`POST .../versions/{version_id}/confirm`；`GET .../versions/{version_id}/download?format=md|html`。版本只增不改，确认和发布校验来源版本。
- `GET /report`。按案例、渠道返回总数、有效样本数和缺失状态，不自动排名。
- `GET/POST /ai/tasks`；`GET /ai/tasks/{uuid}`；`POST /ai/tasks/{uuid}/apply|cancel`。提交包含最长 160 字符的 `request_key`，同键同载荷返回原任务，同键不同载荷返回 409。应用草稿操作幂等。项目探索使用 `kind=project`、`project_path` 和可选 `instruction`，返回 `stage` 进度；案例的 `source_snapshot` 只读。
- `GET /integrations`；`GET/POST /handoffs`；`GET/PATCH /handoffs/{uuid}`；`GET/POST /handoffs/{uuid}/results`。回存只接受本人、同组织、关联目标会话中的成功助手回复。

新增表为 Case、Topic、Channel、Version、Feedback、AITask、Workspace、Handoff，全部组织隔离，PostgreSQL 增加 RLS。
没有导入旧应用数据，也不预填未经验证的案例或收益数字。

## 安装与验证

从仓库根目录使用项目虚拟环境：

```powershell
backend\venv\Scripts\python.exe backend\manage.py validate_app_center
backend\venv\Scripts\python.exe backend\manage.py migrate project_promotion --noinput
backend\venv\Scripts\python.exe backend\manage.py sync_app_center --package project-promotion
```

重启后端与执行 worker 以载入应用；前端更新后在应用中心打开「项目宣传助手」。

后端测试：在 backend 目录执行 `venv\Scripts\python.exe -m pytest app_center/project_promotion/backend/tests -q`。
前端测试覆盖 `projectPromotion.test.tsx`、`promotionLayout.test.ts`，以及共用交接草稿的 `repoHandoff.test.tsx`。
类型检查、lint、生产构建与静态 CSS 检查不代表真实浏览器或手机视觉验收。
