# Agent Studio

## Bundled submodules

Creation Master is mounted as the complete
`backend/app_center/creation_master` Git submodule. Clone all application source,
including Creation Master's own nested dependencies, with:

```bash
git clone --recurse-submodules <repository-url>
```

For an existing checkout, run `git submodule update --init --recursive`.
Its Qt client remains a standalone desktop process. Its React source stays in
the submodule and is compiled directly into the main frontend bundle.

面向组织的通用智能体、应用与工作流平台。平台层提供统一的编排、执行与治理能力；具体场景能力由应用和智能体承载。项目只有一套执行实现：所有 Agent、Conversation、Application、Workflow 和 Media 任务都创建 `modules.execution.Run`，由统一 Coordinator、事件流和命令 API 驱动。

当前架构及取舍见 [ARCHITECTURE_ANALYSIS.md](ARCHITECTURE_ANALYSIS.md)。仓库不再维护 V1/V2 两套设计文档或兼容协议。

## 核心结构

- `backend/modules/catalog`：Agent、Skill、Application 的 Draft、不可变 Revision、Deployment。
- `backend/modules/execution`：Run、全局领取队列、Attempt、Lease、Event、Command、Artifact、幂等记录。
- `backend/apps`：Agent、Application、Conversation、Workflow、Enterprise 等产品域。
- `backend/apps/knowledge`：组织知识库、文档提取、原生混合索引和有据问答。
- `frontend/src/entities/run`：唯一 Run 事件投影。
- `frontend/src/features/run-stream`：Run 流连接与页面级状态编排。
- `frontend/src/api/generated.ts`：由后端 OpenAPI 契约机械生成的接口类型。
- `frontend/src/services/api.ts`：唯一 REST 客户端入口。
- `frontend/src/services/runStream.ts`：唯一流式事件客户端。

Workflow 使用唯一的 `workflow-dag` 执行器，支持显式依赖、条件分支、节点级重试和有界并行。等待子 Run 时根 Attempt 进入 `waiting_children` 并释放 Worker，由子 Run 终态事件重新入队。交互请求通过同一 durable checkpoint / `RunCommand` 机制暂停与恢复。

知识库索引与问答使用 `knowledge` 执行池。PostgreSQL 部署使用 pgvector/HNSW 与全文索引，SQLite 桌面版使用 sqlite-vec/FTS5；嵌入供应商不可用时仍可进行词法检索。支持 PDF、DOCX、Markdown、TXT 和粘贴文本，扫描版 PDF 需要在外部完成 OCR。

## 本地启动

要求 Python 3.11+、Node.js 20.19+（推荐 Node.js 22）。生产形态另需 Docker、PostgreSQL 和 Redis。

后端：

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip wheel
python -m pip install -r requirements/development.txt
python manage.py migrate
python manage.py runserver 0.0.0.0:8080
```

Windows 使用 `.venv\Scripts\Activate.ps1` 激活虚拟环境。开发环境不复制
`.env.example` 时默认使用 SQLite；该示例文件默认配置 PostgreSQL，供部署时按实际环境修改后使用。
项目已通过 Daphne 将 `runserver` 注册为 ASGI 服务，以支持 Run 的异步 SSE
事件流；不要改用同步 WSGI 服务器承载 `/api/v1/runs/.../stream`。

开发环境默认使用 SQLite。SQLite 只允许一个 coordinator 进程；使用 `all`
在同一进程内轮询所有执行池：

```bash
cd backend
source .venv/bin/activate
python manage.py run_execution_coordinator --worker-pool all
```

也可以把 `all` 替换为 `agent`、`media`、`workflow`、`evaluation` 或 `knowledge`，只启动
一个执行池。PostgreSQL 环境仍可按执行池分别启动多个 coordinator 进程。

前端：

```bash
cd frontend
npm ci
npm run generate:api
npm run dev
```

浏览器访问 `http://localhost:3030`。Vite 将 `/api` 代理到 `http://localhost:8080`；产品 API 的稳定入口统一为 `/api/v1`。

## Android / iOS 移动端外壳

`mobile` 目录提供 React Native WebView 外壳，Android 和 iOS 共用同一套
TypeScript 代码，并直接加载已部署的 HTTPS 网页。它包含同源 Cookie 会话、
导航白名单、离线/错误恢复、原生分享桥接和自定义深链接。

首次运行前请在 `mobile/src/appConfig.ts` 配置正式网页域名，完整的构建、签名
和联调说明见 [mobile/README.md](mobile/README.md)。Android 可在 Windows 上构建；
iOS 最终构建和签名必须在安装 Xcode 的 macOS 上完成。

## 认证地址

页面路由是：

- `/auth/login`
- `/auth/register`

REST API 统一使用版本化前缀 `/api/v1`：

- `POST /api/v1/auth/login/`
- `POST /api/v1/auth/register/`
- `POST /api/v1/auth/token/refresh/`
- `POST /api/v1/auth/logout/`

登录和注册响应只返回短期 access token；refresh token 仅保存在 `HttpOnly`、`SameSite=Strict` Cookie 中并在刷新时轮换，不会写入 JSON 或浏览器存储。直接向 `http://localhost:3030/auth/register/` 发送 POST 会命中前端开发服务器，不是后端 API；正确地址是 `http://localhost:3030/api/v1/auth/register/`。

## 单企业私有部署

系统默认启用单企业模式；企业服务器可在 `backend/.env` 中覆盖企业信息：

```dotenv
SINGLE_TENANT_MODE=True
SINGLE_TENANT_ORGANIZATION_SLUG=enterprise
SINGLE_TENANT_ORGANIZATION_NAME=Enterprise Workspace
SINGLE_TENANT_DEFAULT_ROLE=viewer
```

首个用户会初始化并拥有默认企业，后续用户自动以默认角色加入。前端隐藏企业选择器，服务端忽略客户端提交的组织头，并提供 `/api/v1/runs`、`/api/v1/applications/...` 等无组织 ID 别名。数据库仍保留 `organization_id`，用于权限、审计、配额与行级安全。多租户部署必须显式设置 `SINGLE_TENANT_MODE=False`。

已有数据的部署应将 `SINGLE_TENANT_ORGANIZATION_ID` 设置为需要保留的现有组织 UUID；不要只修改 slug，否则系统会创建新的默认企业，原组织数据不会自动迁移。

## Durable Run API

组织级执行接口统一位于 `/api/v1/organizations/{organization_id}/`：

- `POST agents/{agent_id}/runs`
- `POST applications/{application_id}/runs`
- `GET runs`
- `GET runs/{run_id}`
- `GET runs/{run_id}/events`
- `GET runs/{run_id}/stream`
- `GET runs/{run_id}/snapshot`
- `POST runs/{run_id}/commands`
- `GET runs/{run_id}/attempts`
- `GET runs/{run_id}/artifacts`

创建 Run（包括 Agent execute、Conversation send_message 和 Workflow start
薄入口）和提交命令都必须携带幂等键。运行事件是可重放事实，前端通过
sequence 游标恢复，不维护第二套运行状态。

## 自动化

顶部“自动化”模块支持按指定时区执行单次或五段 Cron 计划，也可以生成带
Bearer 密钥的 Webhook。自动化只能运行 Production 应用或自动工作流，每次
触发都会创建一条可审计的 Invocation，并关联到统一 Durable Run。Webhook
密钥只在创建或轮换时显示一次；同一个外部 `Idempotency-Key` 可安全重放。

调度器仍使用已有启动命令：

```powershell
cd backend
venv\Scripts\python.exe manage.py run_automation_scheduler
```

## Compose 部署

复制并配置 `backend/.env`，必须设置：

```dotenv
DATABASE_ENGINE=postgresql
DB_ADMIN_PASSWORD=change-admin-password
DB_NAME=agent_studio
DB_USER=agent_studio
DB_PASSWORD=change-app-password
REDIS_ENABLED=True
REDIS_PASSWORD=change-redis-password
REGISTRATION_ENABLED=False
```

然后执行：

```powershell
cd backend
docker compose up --build
```

Compose 只把前端绑定到宿主机 `127.0.0.1:3000`，不会直接暴露 Django、
PostgreSQL 或 Redis。公网部署必须在宿主机配置 HTTPS 反向代理；完整的首个管理员
初始化、备份恢复和发布门禁见 [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)。正式环境
默认关闭自主注册，可用 `docker compose exec web python manage.py createsuperuser`
创建首个管理员。

Compose 先以一次性 `migrate` 服务完成迁移，再启动 Web、Agent Worker、Media Worker、Workflow Worker、Evaluation Worker、Scheduler、Maintenance、PostgreSQL 16 和 Redis 7.4。应用数据库账号由初始化脚本创建为 `NOSUPERUSER/NOBYPASSRLS`；PostgreSQL 和 Redis 不暴露宿主机端口。

## Windows 桌面打包（不包含 Creation Master）

主工程可以用 PyInstaller 构建为自包含的 Windows 目录发行版。该构建使用
SQLite 和本地事件轮询，包含 React 前端、Django/Daphne、执行协调器及其他
App Center 应用，但明确排除 `app_center/creation_master`：

```powershell
cd backend
python -m pip install -r requirements/desktop.txt
python build_desktop.py
```

产物为 `backend/dist/AgentStudio/AgentStudio.exe`。如果 FFmpeg
不在 `PATH`，构建前可将 `FFMPEG_DIR` 指向同时包含 `ffmpeg.exe` 和
`ffprobe.exe` 的目录。用户数据库、媒体和工作区保存在
`%LOCALAPPDATA%/AgentStudio`，不会写入安装目录。
应用启动后驻留在 Windows 系统托盘。双击托盘图标或选择“打开 Agent
Studio”可重新打开页面；选择“退出应用”会同时关闭 Web 服务、执行
协调器和自动化调度器。

### 桌面离线许可证

桌面版可在构建时切换为离线许可证登录。启用后，账号密码登录、注册和企业
SSO 入口会被许可证页面替代，注册 API 也会拒绝请求。生成签名密钥：

```powershell
cd backend
python tools/license_generator.py generate-keys `
  --private-key license-private.key `
  --public-key license-public.key
```

使用许可证专用构建脚本读取公钥并打包。这些发行设置会嵌入程序，最终用户
不能通过修改旁路配置重新开放注册。私钥不得放入仓库或桌面安装包：

```powershell
python build_licensed_desktop.py
```

公钥不在默认的 `backend/license-public.key` 时，可显式指定：

```powershell
python build_licensed_desktop.py `
  --public-key D:\keys\agent-studio-public.key `
  --product-id agent-studio
```

脚本只读取公钥，不读取私钥。用户将登录页显示的机器码发给授权方后，可签发
永久许可证：

```powershell
python tools/license_generator.py issue `
  --private-key license-private.key `
  --machine-code "AS-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX" `
  --customer "客户名称" `
  --license-type perpetual `
  --output customer.license
```

试用许可证必须提供截止日期：

```powershell
python tools/license_generator.py issue `
  --private-key license-private.key `
  --machine-code "AS-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX" `
  --customer "客户名称" `
  --license-type trial `
  --expires-at 2026-09-30 `
  --output customer-trial.license
```

用户导入的许可证保存在 `%LOCALAPPDATA%/AgentStudio/license.lic`。换电脑后
机器码会改变，必须重新签发。纯离线模式以本机时间判断到期，无法彻底防止
高级用户通过系统快照或程序破解绕过试用限制。

Artifact 默认写入共享 `runtime_data:/data`，也可用 `ARTIFACT_STORAGE_BACKEND=s3` 切换到 AWS S3 或 MinIO；下载接口会返回对应后端的短期签名访问。Maintenance 默认每小时执行 Retention、对象删除和 RunEvent 压缩；可用 `EXECUTION_WORKER_MAX_CHILDREN` 调整每个 Worker 的子进程并发数。配置 OTLP Collector 后可启用 HTTP、Run 创建和 Attempt 生命周期追踪。

如果数据库 volume 是旧版本创建的，需要在尚未承载数据的前提下重建 volume，使新的账号与 RLS 初始化生效。

## 验证

```powershell
cd backend
python manage.py check
python manage.py makemigrations --check --dry-run
pytest -q

cd ../frontend
npm run generate:api
npm run lint
npm test
npm run build
```

## 破坏性升级说明

项目尚未上线，本轮统一不提供旧协议兼容层。旧 `AgentExecution`、Conversation 进程内 Session、`WorkflowRun`/`WorkflowStepRun`、旧 SSE/Agent Protocol、旧 Application Runner 和文件系统 Runtime Skill API 均已删除。迁移前若存在试验数据，应按需导出后重建开发数据库。
