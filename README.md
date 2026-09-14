# Creation Agent Studio

面向组织的智能体、应用与工作流创作平台。项目只有一套执行实现：所有 Agent、Conversation、Application、Workflow 和 Media 任务都创建 `modules.execution.Run`，由统一 Coordinator、事件流和命令 API 驱动。

当前架构及取舍见 [ARCHITECTURE_ANALYSIS.md](ARCHITECTURE_ANALYSIS.md)。仓库不再维护 V1/V2 两套设计文档或兼容协议。

## 核心结构

- `backend/modules/catalog`：Agent、Skill、Application 的 Draft、不可变 Revision、Deployment。
- `backend/modules/execution`：Run、全局领取队列、Attempt、Lease、Event、Command、Artifact、幂等记录。
- `backend/apps`：Agent、Application、Conversation、Workflow、Enterprise 等产品域。
- `frontend/src/entities/run`：唯一 Run 事件投影。
- `frontend/src/features/run-stream`：Run 流连接与页面级状态编排。
- `frontend/src/api/generated.ts`：由后端 OpenAPI 契约机械生成的接口类型。
- `frontend/src/services/api.ts`：唯一 REST 客户端入口。
- `frontend/src/services/runStream.ts`：唯一流式事件客户端。

Workflow 使用唯一的 `workflow-dag` 执行器，支持显式依赖、条件分支、节点级重试和有界并行。等待子 Run 时根 Attempt 进入 `waiting_children` 并释放 Worker，由子 Run 终态事件重新入队。交互请求通过同一 durable checkpoint / `RunCommand` 机制暂停与恢复。

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

开发环境默认使用 SQLite。另开终端启动需要的执行 Worker：

```bash
cd backend
source .venv/bin/activate
python manage.py run_execution_coordinator --worker-pool agent
python manage.py run_execution_coordinator --worker-pool media
python manage.py run_execution_coordinator --worker-pool workflow
python manage.py run_execution_coordinator --worker-pool evaluation
```

前端：

```bash
cd frontend
npm ci
npm run generate:api
npm run dev
```

浏览器访问 `http://localhost:3030`。Vite 将 `/api` 代理到 `http://localhost:8080`；产品 API 的稳定入口统一为 `/api/v1`。

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

## Compose 部署

复制并配置 `backend/.env`，必须设置：

```dotenv
DATABASE_ENGINE=postgresql
DB_ADMIN_PASSWORD=change-admin-password
DB_NAME=creation_studio
DB_USER=creation_app
DB_PASSWORD=change-app-password
REDIS_ENABLED=True
```

然后执行：

```powershell
cd backend
docker compose up --build
```

Compose 先以一次性 `migrate` 服务完成迁移，再启动 Web、Agent Worker、Media Worker、Workflow Worker、Evaluation Worker、Scheduler、Maintenance、PostgreSQL 16 和 Redis 7.4。应用数据库账号由初始化脚本创建为 `NOSUPERUSER/NOBYPASSRLS`；PostgreSQL 和 Redis 不暴露宿主机端口。

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
