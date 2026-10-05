# 厨房助手 2.0

入口：应用中心 → 厨房助手，路由 `/applications/{id}/kitchen-assistant`。
个人管理家庭餐食，覆盖选菜、三餐菜单、采购入库、备菜、计时制作和历史复用。
所有状态、历史和 AI 任务按组织、应用、所有者隔离；组织管理员不能读取其他用户的厨房内容。

## 使用流程

1. **我的厨房 → 家庭偏好**：默认人数、避免/不喜欢食材、辣度、厨具、单道菜用时上限。
2. **菜谱**：保留原三道菜；从精选库选择导入 30 道原创家常参考菜谱（早餐 6、荤菜 8、蔬菜 6、汤 4、主食 6）。收藏、标签、餐次/难度/时间筛选、按人数预览、复制及手动编辑。
3. **菜单**：七天三餐，每餐人数与计划菜数独立；可锁定、跳过、复制、换一道或换一餐。规则生成先预览，不放宽硬约束；候选不足及周内重复明确提示。
4. **采购**：本餐与日期范围各自勾选，可手动补充或复制清单。按餐次日期顺序分配库存，同一批库存不重复抵扣；兼容千克/克、升/毫升，不推算个/把/勺的重量。确认实际数量与到期日后新增独立批次。
5. **制作**：独立内容视图、大字模式、备菜勾选、步骤总览、多个菜/多个步骤计时。开始时保存菜谱和人数快照；完成时预览逐批扣减，保存记录、扣减和清理进度同事务提交。
6. **下厨记录**：每页 20 条，可按菜名和日期搜索，评分、心得、查看当时快照、再做一次。原菜谱已删除时可确认从快照恢复；旧记录不伪造快照。

编辑草稿保存在本机 localStorage，键包含用户、应用 API 路径和菜谱 ID；草稿不是离线操作队列。库存支持位置、名称/分类、临期及零库存筛选。
页面根节点沿用 `app-scroll-page`，兼容 full-bleed、embedded、standalone 和不同入口下的滚动容器。

## AI

三个入口：文字导入菜谱、按条件安排七天菜单、菜谱/制作中的烹饪问答与追问。

- 使用平台 `media` 执行器、系统 AI 引擎、成员额度检查、平台任务配额与用量记录。
- 直接使用系统 `AGENT_ENGINE_ADAPTER` 及其默认模型，无需组织提供方；旧的 `answer_provider` / `answer_model` 不再参与应用生成路由。
- AI 结果是独立私有任务，刷新后可恢复最近 50 个任务；任务详情可单独查询。生成不会直接修改菜谱、菜单、库存或制作状态。
- 菜谱不确定的份数、用量、单位、时间保留空值并标记待补充；服务端生成食材/步骤 ID，用户在编辑器核对后通过正常校验保存。
- AI 菜单仅引用已有菜谱，校验日期、人数、食材偏好、厨具、辣度和餐次；应用时再次使用最新状态验证，保留锁定/跳过安排。失败须重新生成或调整偏好。
- 每个任务最多一次模型调用，不自动重试付费请求；创建请求可用同一 requestKey 安全重试。取消后的迟到结果丢弃。失败保留输入，用户可手动新建任务重试。
- 模型不可用不影响手动操作与规则排菜单。任务持续等待时，检查 media coordinator 是否运行。

## API 与版本

前缀 `/api/v1/organizations/{organization_id}/applications/{application_id}/kitchen-assistant`：

- `GET /state` → `{revision, recordCount, data}`，最近 20 条历史附在 `data.records`。
- `PATCH /state` → `{schemaVersion:2, revision, operationId, changes, appendRecords, aiTaskId?}`。仅提交变化字段；历史最多追加一条。应用 AI 菜单时传 aiTaskId，服务端使用已验证任务结果，并重新验证当前条件。
- `PUT /state` 保留完整提交接口，data 必须携带 schemaVersion:2；历史仅补充，绝不删除分页窗口以外的记录。
- `GET /records?page=1&search=菜名&start=YYYY-MM-DD&end=YYYY-MM-DD`，起止日期包含当天，依据服务端时区。
- `PATCH /records/{id}` → `{revision,rating?,tasteNotes?}`；`DELETE /records/{id}?revision=N`。
- `GET /catalog` → 30 道可选精选菜谱，不自动覆盖用户菜谱。
- `POST /ai/tasks` → `{kind:recipe|menu|question,instruction,revision,requestKey,recipeId?,parentId?,startDate?}`；成功返回 202，幂等重放返回 200。
- `GET /ai/tasks` → 最近 50 个私有任务；`GET /ai/tasks/{id}` 查询单个；`POST /ai/tasks/{id}/cancel` 取消。

菜单保持 `date/lunch/dinner` 菜谱 ID 数组，增加 `breakfast` 与 `settings`：每个餐次包含 `servings/locked/skipped/count`。
制作保留 `timers`（绝对截止毫秒）与 `pausedTimers`（剩余秒数），新计时器以独立 ID 索引，`timerMeta` 关联 recipeId/stepId。旧菜谱 ID 计时器仍可继续使用。

revision + operationId 避免重复采购、重复扣减和重复记账；409 后由用户选择重新应用或放弃，失败操作待处理时不接受新写入。AI 请求另有 requestKey/请求指纹防止键复用。

## 迁移与启动

从仓库根目录执行，macOS/Linux 使用项目虚拟环境；Windows 替换为 `backend\venv\Scripts\python.exe`：

```sh
backend/.venv/bin/python backend/manage.py migrate kitchen_assistant --noinput
backend/.venv/bin/python backend/manage.py sync_app_center --package kitchen-assistant
backend/.venv/bin/python backend/manage.py validate_app_center
```

重启后端及现有执行器进程，使新模型、路由与运行入口生效。若尚未运行任务执行器，在单独终端启动：

```sh
backend/.venv/bin/python backend/manage.py run_execution_coordinator --worker-pool media
```

`0004` 保留并搬迁全部旧历史；`0005` 新建私有 AI 任务表与组织 RLS；`0006` 回填历史菜名检索字段，兼容 SQLite/PostgreSQL 中文搜索，不更改历史正文。旧状态读取时补齐三餐、偏好、人数和制作快照，保留原截止时间。可能覆盖新版结构的旧客户端写入返回 409 与 `schema_upgrade_required`，提示刷新升级。

无需新增第三方依赖；仍限制 1–8 人、500 道菜谱、500 个库存批次，每道菜最多 100 个食材/步骤。
声音/通知依赖页面运行，关闭页面、冻结标签页或系统挂起时不保证准时提醒。同一标签页刷新后按已记录截止时间去重；其他标签页有独立提醒状态。
没有家庭共享、营养分析、金额统计、图片/网页识别或后台推送。

## 验证

```sh
backend/.venv/bin/python -m pytest backend/app_center/kitchen_assistant/backend/tests -q
cd frontend
npx vitest run src/pages/Apps/__tests__/kitchenDomain.test.ts src/pages/Apps/__tests__/kitchenAssistant.test.tsx src/pages/Apps/__tests__/kitchenTimerAlerts.test.tsx src/lib/__tests__/applicationCatalog.test.ts src/layouts/__tests__/mobileScrolling.test.ts
npx eslint src/services/kitchenAssistant.ts src/pages/Apps/KitchenAssistantPage.tsx src/pages/Apps/kitchen/ --max-warnings 0
npm run build
```

验证覆盖领域计算、DOM 操作、权限、数据兼容、真实平台任务提交、模拟模型异常与取消、历史迁移、CSS 滚动契约和生产构建。模型测试使用模拟响应，不代表真实服务质量验证；布局检查不等于真机触摸或视觉验收。不使用 Codex 应用内浏览器。
