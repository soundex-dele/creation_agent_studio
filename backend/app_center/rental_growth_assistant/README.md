# 租房获客助手

个人私有的租房运营应用，覆盖房源、画像、内容、咨询、带看、运营日历和成交复盘。支持小红书图文、抖音／视频号口播和朋友圈文案。发布、发送回复和效果录入由用户手动完成；不接入外部账号、不上传照片、不推送通知。

## 安装与运行

从仓库根目录使用项目虚拟环境（Windows 对应 `backend\venv\Scripts\python.exe`）：

```sh
backend/.venv/bin/python backend/manage.py validate_app_center
backend/.venv/bin/python backend/manage.py migrate rental_growth --noinput
backend/.venv/bin/python backend/manage.py sync_app_center --package rental-growth-assistant
npm run build --prefix frontend
```

重启 Web、执行 coordinator 和 media worker，使新 Django 应用及执行器注册生效。模型使用平台已有系统引擎及登录状态，通过 `core.llm.application.generate_json` 执行，沿用额度与真实用量统计。无需单独配置图片理解模型或平台账号。数据库迁移只新增本应用表，PostgreSQL 启用组织 RLS；用户私有隔离由查询层强制执行。

入口：`/applications/{applicationId}/rental-growth-assistant`，支持 `entry=home`、`entry=apps`、`standalone=1` 和 `embedded=1`。应用中心安装后提供入口。

## 日常流程

1. 新增房源；可先保存不完整草稿，推广前补齐名称、城市、片区、租金、出租方式、户型。照片清单每行“名称 | 备注”，同类照片可重复。
2. 首次打开时自动添加 8 类常用租客画像：预算优先独居、通勤优先、情侣整租、养宠、朋友合租、家庭居住、居家办公、短期过渡。可在创作中直接选择，或在「房源 → 目标租客画像」编辑、归档、新增以及点击「用这个画像创作」。预填生活需求与关注点，预算、区域、户型和日期保持未知，按实际业务完善。画像用于内容角度，不代表真实客户确认的需求。必要条件“电梯”“可养宠”使用标准房源字段；其他条件按名称匹配房源自定义条件。未知条件不会被视作满足。
3. 选择房源、画像、平台生成文案，或生成七天选题后点击“采用七天计划”。计划进入内容库与日历，每天一个选题；生成前可以修改日期和角度。
4. 生成时自动展开实时消息，显示真实任务阶段和逐步生成的文案；可收起、回放历史消息，断线自动续接，刷新可恢复。阅读上方内容时不会强制滚动，点击“回到最新消息”继续跟随。文案可编辑、保存新版本、复制正文／口播／排版、导出 Markdown。相同平台继续创作保留同一内容的版本历史；转换平台保存独立内容。复制不会标记发布，发布记录绑定实际使用的版本。
5. 手动登记咨询及主要来源作品。粘贴咨询可提取需求草稿，审核后保存；不会自动写入客户。重复联系方式只提示，不合并。回复建议不会自动发送。
6. 创建跟进或预约带看，支持改期、取消、未到场及反馈。跟进标记完成并填下次日期时，生成下一条待办。客户阶段手动控制，完成带看不会自动成交。
7. 登记成交日期与房源，可同时标记房源已出租。在已发布作品中录入累计效果，通过复盘查看咨询、带看及成交归因。

## 数据与统计口径

- 房源、画像、客户、跟进、带看、内容和发布记录使用独立模型；类型化序列化器校验扩展字段。引用必须属于同组织、应用和当前用户，组织管理员也不能读取他人的业务资料。
- 更新携带 `revision`；并发版本不一致返回 409，不覆盖他人或其他标签页的修改。记录支持归档和恢复，不提供级联删除。
- 文案版本不可变，保存时冻结房源资料及内容元数据。房源变化、出租、暂停或归档会提示核对；存在变化的旧版本不能新登记发布，需要先审核并保存新版本。
- 已发布作品的版本与发布状态固定，重新发布需新增记录；更新房源不改写已发布内容和归因。
- 客户有一个主要来源作品。按首次咨询日期选取客户批次，截至查询时计算带看及成交；同一客户多次完成带看只计一位。成交日期和房源必须一起填写，成交不能早于首次咨询。
- 未归因客户单列。按房源分组可能重叠，不可以相加；画像及平台来自发布版本的快照。未知指标用 null，0 是有效记录；平台互动为手动录入的最近累计值，不随客户批次日期变为增量。
- 默认时区 Asia/Shanghai；日期计划按该时区显示，预约时间以 UTC 保存。无定时推送，仅应用内到期与逾期提示。
- AI 输入冻结，任务创建使用请求键去重。同键不同输入返回 409，失败后可手动重试；取消或权限失效不保存迟到结果。文案任务不读取客户联系方式。需求提取与回复只包含需求字段及用户主动粘贴的咨询文本。
- 实时消息复用持久化 Run SSE，支持增量、替换快照、事件去重和压缩历史恢复。只转发模型公开输出，不转发内部推理、工具参数或诊断；Run 详情、事件、快照与流都校验本人及应用权限，长连接每批复查权限。生成中的文本未经校验，最终结果仍需通过结构及引用校验后保存。
- 照片引用校验为“房源 UUID:清单序号”；无照片时生成待拍清单，不能声称已分析实拍图。提示词约束与结构检查不等同事实核验，生成内容仍应对照房源确认。

## 接口

组织前缀为 `/api/v1/organizations/{organization_id}/applications/{application_id}/rental-growth-assistant`；单租户支持现有无组织前缀别名。

- `GET/POST /properties|personas|leads|followups|viewings|contents|publications`
- `PUT /personas/built-ins`：空对象请求，按组织、应用和当前用户幂等初始化内置画像；返回新增数量 `created`。稳定 ID 避免重复，保留已编辑和已归档记录。前端在读取画像前自动调用，现有账号同样生效，不需要新增迁移。
- `GET/PATCH /{resource}/{uuid}`：通用外壳为 `title/status/archived/revision/data`；跟进／带看增加 `lead_id`，发布增加 `version_id`。PATCH 中 `data` 按字段合并，数组整体替换。分页每页 50 条，可查询 `page/search/status/archived=all|true`。
- `GET /leads/{uuid}/matches`：符合、未知、冲突三组，包含逐项理由。
- `GET/POST /contents/{uuid}/versions`；`GET /versions/{uuid}/download`。
- `GET/POST /publications/{uuid}/metrics`：保留指标观察历史。
- `GET/PUT /settings`；`GET /overview/dashboard|calendar|reports`，日历与报表支持 `start/end` 日期筛选。
- `GET/POST /ai/tasks`；`GET /ai/tasks/{uuid}`；`POST .../cancel`；`POST .../apply`（采用七天计划，幂等）。任务类型 `topics/copy/extract/reply/review`，创建要求 `request_key`；返回 `run_id/organization_id` 供现有 `/runs/{run_id}/stream` 实时订阅。

## 验证

```sh
backend/.venv/bin/python -m pytest -c backend/pytest.ini backend/app_center/rental_growth_assistant/backend/tests -q
npm run test --prefix frontend -- src/pages/Apps/__tests__/rentalGrowth.test.tsx src/pages/Apps/__tests__/rentalGenerationMessages.test.tsx src/layouts/__tests__/rentalLayout.test.ts src/lib/__tests__/applicationCatalog.test.ts
cd frontend
./node_modules/.bin/eslint src/pages/Apps/RentalGrowthPage.tsx src/pages/Apps/rental/*.tsx src/pages/Apps/rental/config.ts src/services/rentalGrowth.ts src/pages/Apps/__tests__/rentalGrowth.test.tsx src/pages/Apps/__tests__/rentalGenerationMessages.test.tsx src/layouts/__tests__/rentalLayout.test.ts
npm run build
```

测试覆盖完整归因链、版本快照、房源匹配、重复带看去重、客户草稿、权限、请求去重、取消与失败、照片引用、日期时区及所有栏目操作。模型结果在自动化测试中模拟，不代表已完成真实模型联调。

页面通过 `ApplicationShell fullBleed` 接入，根使用 `app-scroll-page`。CSS 与 jsdom 回归覆盖手机宽度、767/768 边界、桌面、短横屏、弹窗和入口契约；这些是自动化／静态检查，不代表浏览器或真实设备视觉验证。遵守仓库不使用 Codex 内置浏览器的规定。

### 1.0.1 升级

本次增加实时生成消息，没有新增数据库迁移。同步应用包后重启 Web、coordinator 和 media worker，发布新的前端构建。旧任务仍可打开，升级前未记录的模型增量无法补回。断线时保留已收到的消息，轮询继续恢复最终任务状态。

### 1.0.2 升级

增加 8 类内置租客画像与创作入口，不需要新增数据库迁移。发布前后端并重启 Web 后，用户再次打开应用即可获得自己的画像副本。初始化不会覆盖已有编辑、恢复已归档画像或合并同名自定义画像。自动化测试覆盖初始化去重、编辑与归档保留、权限隔离、生成任务快照和前端选择流程。
