# 提示词大师

`prompt-master` 是私有的提示词生成与优化应用。支持写作、编程、学习、办公、绘图、视频和通用场景；绘图与视频仅输出跨平台自然语言提示词，不实际生成媒体。

## 使用

输入主题或原提示词，首轮回答 3～5 个动态问题；需求已充分时直接生成。最多补问一轮、3 个问题，用户也可直接按推荐生成。结果包括标准版、精简版、采用的假设、具体体检建议、改进说明和硬约束摘录。模型输出摘录必须出现在对应正文中；这能校验返回结构，不能证明模型没有遗漏未识别的约束或实际效果。

每个编辑、生成或体检结果保存为独立版本。输入变化后问题重置，已有结果标为过期；对旧版本体检不会消除其与当前需求的差异。模型任务使用输入快照与会话 revision 校验，取消、已终止任务及过期响应均不会覆盖会话。

历史支持分页搜索、场景过滤、收藏、改名、删除及复制新会话。按组织、应用、用户隔离，管理员也不能通过本应用 API 读取其他人的会话。删除隐藏会话并取消活跃任务，保留数据库记录。未提交编辑在页面保留，离开编辑时提示；已保存会话及运行中的任务刷新后可恢复。

## 接入

前端路由：`/applications/:applicationId/prompt-master`。租户 API 前缀后使用 `applications/{application_id}/prompt-master/`：

- `GET catalog`：12 个内置模板与场景。
- `GET/POST sessions`：历史列表与新建；列表参数 `search/scene/favorite/page`。
- `GET/PATCH/DELETE sessions/{id}`：详情、修改及删除。修改必须携带 revision；删除使用 `?revision=N`。版本不符返回 409。
- `POST sessions/{id}/copy`：复制输入为新任务，不复制生成记录。
- `GET/POST sessions/{id}/versions`：分页版本与保存手动编辑；保存携带 revision、version_id、standard、concise。
- `POST sessions/{id}/tasks`：kind 为 analyze/generate/optimize/check，携带 revision、request_key；可附 instruction、version_id。
- `GET sessions/{id}/tasks/{task_id}`、`POST .../cancel`：任务状态及取消。

动态问题支持 text/single_choice/multi_choice 和自由文本替代。answers 中 null 表示采用推荐；遗漏或空回答也按推荐处理，生成结果必须披露采用的假设。两轮上限由后端强制执行，问题及输出由 DRF 校验。结果和用户输入始终以文本显示，不作为 HTML 执行。

模型调用复用组织默认文本生成模型（可由有效配置 answer_provider/answer_model 覆盖）、额度校验、UsageRecord 和平台 Run。需要运行 media 或 all 执行器。不额外安装依赖，不调用外部图像/视频服务，不自动重试付费请求。体检是模型建议，不提供效果分数，也不代表已试运行。

## 本地注册

在仓库根目录用项目虚拟环境执行：

```powershell
backend\venv\Scripts\python.exe backend\manage.py validate_app_center
backend\venv\Scripts\python.exe backend\manage.py migrate prompt_master --noinput
backend\venv\Scripts\python.exe backend\manage.py sync_app_center --package prompt-master
```

重启原有后端及执行器以载入新 Django 应用。应用只有新增表及 PostgreSQL 组织级 RLS，不修改已有应用数据。回退时停用应用、回退代码并保留新表和历史。

## 自动化验证

在 backend 运行 `venv\Scripts\python.exe -m pytest app_center/prompt_master/backend/tests -q`。
在 frontend 运行 `npx vitest run src/pages/Apps/__tests__/promptMaster.test.tsx src/layouts/__tests__/mobileScrolling.test.ts src/lib/__tests__/applicationCatalog.test.ts src/lib/__tests__/applicationPresentation.test.ts`，并运行相关 ESLint 和 `npm run build`。

后端测试使用模拟模型响应，覆盖七类场景、冲突、两轮上限、版本、权限、取消、过期任务、幂等、额度及模型失败。前端覆盖问答、模板、编辑体检、历史、刷新恢复及复制错误。布局测试检查 fullBleed 下的 app-scroll-page、各断点高度和安全区，不使用 Codex 内置浏览器，也不能替代真机滚动或真实模型效果验证。
