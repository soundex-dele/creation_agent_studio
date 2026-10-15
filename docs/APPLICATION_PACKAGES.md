# 平台与应用包

应用源码统一位于仓库根目录 `app_center/`，与平台 `backend/`、`frontend/` 平级。
这是受信任应用的模块化单体，前后端统一构建；不是运行时加载任意第三方代码的插件系统。

## 所有权

每个包保留 `application.yaml`、后端、迁移、资源和执行入口。全部专用页面应用的页面、组件、样式、服务、类型和测试已归入各自的 `frontend/`。使用通用聊天的应用继续由清单选择平台聊天渲染器。

应用专属逻辑留在包内。通用聊天、表单、任务渲染器及界面壳由平台维护。
前端通过 `@platform/*` 使用公开能力，包内代码用相对导入或自身的 `@applications/<package>/frontend/*`。
后端通过 `modules.platform_api` 使用身份、租户、模型、执行、知识库和案例能力。
现阶段身份、知识库和案例接口显式公开必要的 Django 模型，保留原有事务与外键语义；执行状态和租约操作由平台封装。

不要把另一个应用的工具函数当作公共库。通用工具先移入平台；应用间业务协作用 `app_center.<package>.public`、`@applications/<package>/frontend/public/*` 中显式公开的服务和导航。公开接口保留原有权限检查、事务、序列化和版本校验语义；模型和查询接口不替调用者执行额外鉴权。

## 注册新应用

创建 Python-safe 的包目录和现有格式的清单。专用 React 页面增加：

```yaml
spec:
  frontends:
    - id: web
      type: react
      directory: frontend
      entrypoint: frontend/index.ts
      renderer_key: example
      platforms: [web]
  backend:
    extensions: app_center.example.extensions.provider
```

前端入口默认导出 `ApplicationFrontendModule`，包含 `rendererKey`、`routes` 和 `launch`。
路由声明页面懒加载组件及 `fullBleed`；平台添加鉴权、加载提示和 `ApplicationShell`。
少数旧入口可声明 `shell: 'main'` 与 `hideSidebar`，或 `shell: 'none'`，保留原有布局包装；默认仍为 `ApplicationShell`。任务应用可提供懒加载 `taskView`，复用平台任务控制器而自行维护表单和结果视图（例如 HTML 转 PNG，保留 `/applications/:applicationId/run`）。
入口只引用页面的动态导入，避免在平台首页加载整个应用。
`entry=home/apps`、`standalone` 和 `embedded` 的语义保持不变，应用继续负责正确的滚动容器。

Vite 和 Vitest 使用同一清单发现插件生成静态注册表。增加或删除清单后重新启动开发服务。
不在平台路由或启动链接表增加应用名称分支。保留旧 React/Qt 变体时，目录继续由清单指定。

后端入口导出 `ApplicationContributions`。可选钩子包括：

| 钩子 | 契约 |
| --- | --- |
| `run_access(user, root_run)` | 不负责该任务返回 `None`；负责则返回 `True/False`。所有适用策略都必须允许。 |
| `knowledge_context(document)` | 在创建索引任务时附加业务上下文，不在创建之后修改 Run 输入。重复键报错。 |
| `case_navigation(case, user)` | 返回应用来源导航；不负责该来源返回 `None`。 |
| `case_targets(source, user, organization_id)` | 返回可访问的目标应用；不负责该来源返回 `None`。 |
| `dispatch_scheduled()` | 执行本应用已有的到期调度逻辑；不得自行建立另一套任务引擎。 |
| `conversation_access(conversation, user)` | 检查应用关联对话的权限；拒绝或加载失败必须中止访问。 |
| `conversation_queryset(queryset)` | 限制通用聊天历史可见范围，例如排除文档专用会话。 |
| `prepare_conversation_message(conversation, user, message, context)` | 在原事务中校验业务版本并准备消息上下文。 |
| `brand_reference_fields` / `validate_brand_reference` / `resolve_brand_snapshot` / `compose_brand_snapshot` | 品牌应用提供字段契约、引用校验、权限校验和快照组合；平台要求恰好一个提供者，缺失或重复时报错。 |

访问钩子加载或执行失败时拒绝任务访问。子任务沿相同组织的任务树解析根任务。
API 与持续事件流共用该策略；受应用策略保护的产物使用需要再次鉴权的内容地址。
模型生成与任务提交复用现有计费、幂等和执行路径。需要在事务内写入任务结果时，使用平台 `active_run` 检查当前 attempt 和租约。

## 启动、测试和发布

源码运行时，平台自动暴露根目录应用包的 Python 导入路径。
`APP_CENTER_ROOT` 可指定包含完整 `app_center` Python 包的替代目录，源代码中的相对配置以仓库根目录为基准；桌面包由启动器指定打包资源目录。
后端虚拟环境仍在 `backend/venv`（Windows）或 `backend/.venv`（Linux/macOS）。

Windows 根目录示例：

```powershell
backend\venv\Scripts\python.exe -X utf8 backend/manage.py validate_app_center
backend\venv\Scripts\python.exe -X utf8 backend/manage.py makemigrations --check --dry-run
backend\venv\Scripts\python.exe -X utf8 -m pytest backend/modules/test_application_boundaries.py
backend\venv\Scripts\python.exe -X utf8 -m pytest app_center backend/apps/applications backend/apps/conversations backend/modules/execution/tests/test_execution_api.py backend/modules/execution/tests/test_builtin_runtime.py
npm.cmd --prefix frontend run lint:applications
npm.cmd --prefix frontend test
npm.cmd --prefix frontend run build
```

根目录 pytest 配置和共享钩子覆盖后端与所有应用包；前端测试同样包含包内目录。桌面与 Docker 构建使用同一份根目录应用源码。
Creation Master 保持 Git 子模块；它的前端和转写适配器迁移也位于子模块工作区。发布这些改动时，先提交子模块，再更新主仓库引用；其他环境使用 `git submodule update --init --recursive` 同步匹配的版本。

发布时停止旧服务、部署匹配的前后端代码，校验清单，按原流程执行迁移及应用同步，再启动 Web、Scheduler 和 Worker。
移动目录不更改 Django app label、表名、应用 ID、URL 或数据存储位置。若设置过旧源码绝对路径，应更新 `APP_CENTER_ROOT`、Playwright 等路径配置。
回退时恢复配套代码与应用部署修订，保留数据库及用户文件。

## 迁移状态

当前 37 个清单应用均受应用边界检查约束，25 个专用前端入口（含 HTML 转 PNG 任务视图）由清单发现。其余应用复用通用聊天，不需要重复创建页面。
平台路由和启动表已移除应用名称分支；后端任务访问、文档对话和品牌引用通过应用贡献注册。公共图片校验、媒体范围流、仓库内容读取和聊天 Skill 配置由平台维护；批量转写执行适配器归入使用它的 Creation Master 包。
`backend/modules/application_boundary_baseline.json` 的后端反向依赖已清空，前端只保留 `chat` 与 `generic-task`。边界测试自动覆盖所有清单包，禁止重新引入平台内部或其他应用内部导入。
目录和清单校验、jsdom 与 CSS 检查不等于真机或浏览器视觉验证。
