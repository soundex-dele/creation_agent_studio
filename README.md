# Creation Agent Studio · 创作智能体工作台

> 一个 AI 驱动的内容/视频创作平台：用智能体（Agent）+ 创作模板（Template）把「文案、脚本、排版、配乐、直播话术、数据分析」等创作流程串联起来，并通过对话（Conversation）与 LLM 实时协作。

> V2 前后端架构重设计见 [docs/ARCHITECTURE_V2.md](docs/ARCHITECTURE_V2.md)。该方案采用模块化单体、不可变 Revision 与统一 Run Event 协议，支持 SQLite 单机模式和 PostgreSQL 集群模式，并按破坏性重建方式整体切换。
>
> “一个应用一个界面”、聊天应用问题库、Agent/Skill 引用和多应用工作流设计见 [docs/APPLICATION_AND_WORKFLOW_V2.md](docs/APPLICATION_AND_WORKFLOW_V2.md)。

前后端分离架构：

- **后端** [backend/](backend/)：Django 5 + Django REST Framework，PostgreSQL + Redis，JWT 鉴权，集成 DeepSeek LLM，提供 SSE 流式对话。
- **前端** [frontend/](frontend/)：React 18 + TypeScript + Vite，Tailwind CSS + Ant Design，Zustand 状态管理，支持 SSE 流式聊天。

---

## 目录

- [功能特性](#功能特性)
- [技术栈](#技术栈)
- [项目结构](#项目结构)
- [数据模型](#数据模型)
- [快速开始](#快速开始)
- [环境变量](#环境变量)
- [API 概览](#api-概览)
- [LLM 集成与流式对话](#llm-集成与流式对话)
- [LangChain ReAct 示例](#langchain-react-示例)
- [前端路由与页面](#前端路由与页面)
- [测试](#测试)
- [开发约定与路线图](#开发约定与路线图)

---

## 功能特性

- 🤖 **智能体市场**：按分类（文案创作、视频制作、视觉设计、音频配乐、数据分析、直播运营）组织创作智能体，每个智能体携带独立的 system prompt，可一键执行并记录执行结果。
- 📋 **创作模板库**：短视频、直播、品牌宣传、图文等结构化模板，支持版本管理与「应用为项目」。
- 💬 **对话式创作**：基于 DeepSeek 的多轮对话，支持 **SSE 流式输出**（边生成边显示），自动保存历史。
- 🧩 **项目工作区**：以模板创建项目、管理项目素材（视频/音频/图片/文本）。
- 🛒 **市场互动**：模板评分、评论（含回复）、用户收藏，以及趋势 / 推荐 / 搜索。
- 🔐 **账号体系**：JWT（SimpleJWT，带刷新令牌轮换与黑名单）、四种角色（管理员 / 专业用户 / 创作者 / 查看者）、个人 API Key 生成。
- 📚 **开箱即用的 API 文档**：Swagger UI + ReDoc（由 drf-yasg 自动生成）。

---

## 技术栈

### 后端 ([backend/](backend/))

| 领域 | 选型 |
| --- | --- |
| Web 框架 | Django 5.0.1 |
| REST API | Django REST Framework 3.14 |
| 鉴权 | djangorestframework-simplejwt、dj-rest-auth、django-allauth |
| 数据库 | SQLite（Local Profile）/ PostgreSQL 14（Cluster Profile） |
| 缓存 | Redis 7（django-redis） |
| API 文档 | drf-yasg（Swagger / ReDoc） |
| 过滤 | django-filter、DRF Search/Ordering |
| 配置 | python-decouple（`.env`） |
| 部署 | Whitenoise、Gunicorn、Sentry（production） |
| LLM | DeepSeek via `core/agent_engine/AgentEngine`（`core/llm/factory.build_agent_engine` 装配） |

### 前端 ([frontend/](frontend/))

| 领域 | 选型 |
| --- | --- |
| 框架 | React 18 + TypeScript |
| 构建 | Vite 5 |
| UI | Ant Design 5、Tailwind CSS 3 |
| 路由 | react-router-dom 6 |
| 状态 | Zustand |
| 请求 | axios（封装拦截器） |
| 流式 | 自实现 SSE 客户端 [services/sseClient.ts](frontend/src/services/sseClient.ts) |
| Markdown 渲染 | react-markdown |

---

## 项目结构

```
creation_agent_studio/
├── backend/                      # Django 后端
│   ├── apps/                     # 业务应用（每个应用自带 models/views/serializers/urls/migrations）
│   │   ├── users/                # 用户、JWT 鉴权、角色、API Key
│   │   ├── agents/               # 智能体分类 / 智能体 / 执行记录
│   │   ├── templates/            # 模板分类 / 模板 / 模板版本
│   │   ├── conversations/        # 对话 / 消息 / SSE 流式聊天
│   │   ├── projects/             # 创作项目 / 项目素材
│   │   └── marketplace/          # 评分 / 评论 / 收藏 / 趋势推荐
│   ├── backend/settings/         # 分环境配置：base / development / production
│   ├── core/                     # 横切关注点
│   │   ├── llm/                  # build_agent_engine() 装配工厂 + PromptManager
│   │   ├── middleware.py         # 请求日志中间件
│   │   ├── decorators.py / exceptions.py / permissions.py
│   ├── examples/langchain_react/ # LangChain ReAct Agent 示例
│   ├── docker-compose.yml        # PostgreSQL + Redis
│   ├── requirements/             # base / development / production 依赖
│   └── manage.py
└── frontend/                     # React + Vite 前端
    └── src/
        ├── pages/                # Home / Auth / Agents / Templates / Workspace
        ├── components/           # Chat / Agents / Templates / Sidebar / Header / Modal / Theme ...
        ├── services/             # axios 封装、api、authService、sseClient
        ├── stores/               # Zustand stores（auth / project 等）
        ├── router/               # 路由表 + 鉴权守卫（ProtectedRoute / PublicRoute）
        ├── layouts/              # MainLayout / AuthLayout
        ├── types/  styles/  ...
```

---

## 数据模型

核心模型之间的关系：

```
User ──┬──< Agent >── AgentCategory          （智能体：分类 + system_prompt）
       ├──< AgentExecution >── Agent          （智能体执行记录）
       ├──< Conversation >── Agent            （对话会话）
       │      └──< Message >                  （user / assistant / system）
       ├──< Template >── TemplateCategory     （创作模板）
       │      ├──< TemplateVersion >          （版本管理）
       │      └──< Project >                  （应用模板创建项目）
       │              └──< ProjectAsset >     （视频/音频/图片/文本）
       ├──< TemplateReview >                  （评分 1-5）
       ├──< TemplateComment >                 （评论 + 嵌套回复）
       └──< UserFavorite >                    （收藏）
```

更多细节见各应用的 [models.py](backend/apps/agents/models.py)。自定义用户模型 `AUTH_USER_MODEL = 'users.User'`，包含 `role`、`avatar`、`bio`、`api_key` 等扩展字段。

---

## 快速开始

### 前置要求

- Python 3.10+、Node.js 18+
- （可选）Docker，用于一键拉起 PostgreSQL + Redis

### 1. 启动基础设施（PostgreSQL + Redis）

```bash
cd backend
docker compose up -d          # 启动 postgres:14 与 redis:7
```

> 💡 不想用 Docker？SQLite 是正式支持的 Local Profile，可跳过数据库与 Redis。复制 `.env.example` 后将 `DATABASE_ENGINE=sqlite`、`REDIS_ENABLED=False`。

### 2. 启动后端

```bash
cd backend
python -m venv venv
source venv/Scripts/activate     # Windows (Git Bash)；PowerShell 用 venv\Scripts\Activate.ps1

pip install -r requirements/development.txt

cp .env.example .env             # 按需修改（见「环境变量」）
# 至少填入 DEEPSEEK_API_KEY，否则对话接口会调用失败

python manage.py migrate
python manage.py seed_mock_data  # 灌入演示数据（分类/智能体/模板/示例对话）
python manage.py runserver 0.0.0.0:8080
```

SQLite Local 的执行平面在另一个终端启动。Coordinator 会取得数据库旁的独占锁，并将服务端注册的 Adapter 放入受控子进程；未在 `EXECUTION_CHILD_ADAPTERS` 注册的 `executor_key` 不会被领取：

```bash
cd backend
python manage.py run_execution_coordinator --worker-pool media
```

后端默认监听 **8080** 端口（与前端 Vite 代理一致）。打开 `http://localhost:8080/swagger/` 查看 API 文档。

演示账号由 `seed_mock_data` 创建。请通过 `DEMO_USER_PASSWORD` 设置密码；
未设置时命令会生成并在终端显示一次高强度随机密码：

| 用户名 | 角色 |
| --- | --- |
| `creator` | 创作者 |
| `designer` | 专业用户 |
| `admin` | 管理员 |

### 3. 启动前端

```bash
cd frontend
npm install
npm run dev
```

前端开发服务监听 **3000** 端口，`/api` 请求会被 Vite 代理到 `http://localhost:8080`（见 [vite.config.ts](frontend/vite.config.ts)）。打开 `http://localhost:3000` 即可使用。

---

## 环境变量

### 后端 `backend/.env`

```ini
SECRET_KEY=replace-with-at-least-50-random-characters
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

# 数据库 Profile；Local 使用 sqlite，Cluster 使用 postgresql
DATABASE_ENGINE=sqlite
SQLITE_PATH=./db.sqlite3
SQLITE_BUSY_TIMEOUT_SECONDS=5
SQLITE_BUSY_TIMEOUT_MS=5000
SQLITE_SYNCHRONOUS=FULL

# PostgreSQL Cluster（DATABASE_ENGINE=postgresql 时使用）
DB_NAME=creation_studio
DB_USER=postgres
DB_PASSWORD=postgres
DB_HOST=localhost
DB_PORT=5432

# 演示数据密码；留空时 seed_mock_data 自动生成随机值
DEMO_USER_PASSWORD=

# Redis；SQLite Local 可设为 False，事件流仍会从数据库补拉
REDIS_ENABLED=False
REDIS_HOST=localhost
REDIS_PORT=6379

# 跨域（前端地址）
CORS_ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000

# LLM
DEEPSEEK_API_KEY=你的-deepseek-key
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1

# GraphFlow Agent Engine（默认按当前工作区的兄弟仓库布局自动解析）
GRAPHFLOW_SDK_PATH=E:/webrtc/GraphFlow/sdk/python
GRAPHFLOW_WORKFLOW_PATH=E:/webrtc/GraphFlow/engine/agent_engine/examples/agent_workflow.json
GRAPHFLOW_PROVIDER=openai
GRAPHFLOW_MODEL=deepseek-chat
GRAPHFLOW_ENABLE_STREAMING=True
GRAPHFLOW_SKILLS_DIRECTORY=C:/Users/dele/.graphflow/skills
# 未设置时分别复用 DEEPSEEK_API_KEY / DEEPSEEK_BASE_URL
# GRAPHFLOW_API_KEY=
# GRAPHFLOW_BASE_URL=https://api.deepseek.com/v1

# Agent adapter：graphflow 或 codex
AGENT_ENGINE_ADAPTER=codex

# 默认直接启动已安装 Codex CLI 的 app-server，无需 Codex 源码或 Python SDK
CODEX_TRANSPORT=app-server
# 仅 CODEX_TRANSPORT=python-sdk 或查找源码编译产物时使用
CODEX_REPOSITORY_PATH=D:/workspace/codex
CODEX_SDK_PATH=D:/workspace/codex/sdk/python/src
# 可选；优先自动查找源码构建产物，再回退到 PATH 中的 codex
# CODEX_BINARY=D:/workspace/codex/codex-rs/target/release/codex.exe
CODEX_MODEL=
CODEX_SANDBOX=workspace-write
CODEX_APPROVAL_MODE=deny_all
CODEX_REQUEST_TIMEOUT_SECONDS=30
CODEX_SKILLS_DIRECTORY=C:/Users/dele/.codex/skills

# Agent 托管工作目录根路径；应用和工作流会在此自动创建隔离目录
AGENT_WORKSPACE_ROOT=D:/agent-workspaces
# 对话中“选择系统目录”允许浏览的根路径，多个路径用英文逗号分隔
APP_RUNNER_ALLOWED_ROOTS=D:/workspace,D:/media
```

### 前端 `frontend/.env.development`

```ini
VITE_API_BASE_URL=/api        # 走 Vite 代理；生产构建时改为后端真实地址
```

---

## API 概览

所有接口前缀 `/api/`，除标注外均需 `Authorization: Bearer <JWT>`。完整交互文档见 `/swagger/` 与 `/redoc/`。

### V2 Catalog 与 Execution `/api/v2/organizations/{organization_id}/`

- `GET|POST applications` — 游标分页查询应用或原子创建 Application + Draft。
- `GET|PUT applications/{application_id}/draft` — 读取或按 `expected_version` 覆盖更新 Draft。
- `GET|POST applications/{application_id}/revisions` — 查询 Revision 或按 Draft 版本发布；相同内容发布幂等。
- `GET applications/{application_id}/runtime?environment=production` — 解析 Deployment 并返回固定 Revision 运行描述。
- `GET|PUT applications/{application_id}/deployments/{environment}` — 查询、创建或按版本切换 Deployment。
- `POST applications/{application_id}/deployments/{environment}/rollback` — 原子交换当前和上一 Revision。
- `POST applications/{application_id}/runs` — 从指定环境的 Deployment 创建固定 Revision 的 Run；必须提供 `Idempotency-Key`。
- `GET runs/{run_id}` — 查询 Run 当前投影。
- `GET runs/{run_id}/events?after={sequence}&limit=100` — 按 sequence 断点重放事件。
- `GET runs/{run_id}/stream` — 可恢复 SSE；支持 `Last-Event-ID`。
- `GET runs/{run_id}/attempts`、`GET runs/{run_id}/artifacts` — 查询执行尝试和产物。
- `GET runs/{run_id}/artifacts/{artifact_id}/access` — 获取短期 Artifact 访问 URL；列表不返回 object key。
- `GET runs/{run_id}/snapshot` — 读取事件压缩后的客户端恢复投影。
- `POST runs/{run_id}/commands` — 提交 `cancel | answer | grant_permission | deny_permission` 持久化命令。

Catalog 写操作要求 Developer；生产 Deployment 的切换与回滚要求 Admin。Draft 和 Deployment
都采用乐观版本，冲突返回 `409`。Draft 可暂存不完整内容，但发布时必须通过 Application
definition schema v1 校验。

终态 Run 的历史事件可通过以下命令按保留期分批压缩。客户端使用过旧 cursor 时收到
`410 event_history_compacted`，应加载响应中的 snapshot URL 后从 `resume_after` 续流：

```powershell
.\venv\Scripts\python.exe manage.py compact_run_events --before-days 30 --batch-size 500
```

PostgreSQL migration 会为全部 V2 租户表启用 RLS。生产环境应使用不具备 `BYPASSRLS` 的 API
数据库角色；跨租户领取 Run 的 Cluster Worker 使用独立且具备 `BYPASSRLS` 的受控角色。

前端通用 V2 运行台位于 `/v2/applications/{application_id}/run`。它只通过
`ApplicationRuntimeProvider` 暴露的 start/subscribe/command/artifact 能力运行应用，支持 SSE
断线重连、缺口补拉和事件压缩 snapshot 恢复；不会调用旧 App Runner 或转录实现。

### 认证 `/api/auth/`

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/auth/register/` | 注册（返回 user + JWT） |
| POST | `/auth/login/` | 登录（返回 user + JWT） |
| POST | `/auth/logout/` | 登出（拉黑 refresh token） |
| POST | `/auth/token/refresh/` | 刷新 access token |
| GET/PUT | `/auth/me/` | 获取 / 更新当前用户 |
| PUT | `/auth/me/change-password/` | 修改密码 |
| POST | `/auth/me/generate-api-key/` | 生成 API Key |

### 智能体 `/api/agents/`（公开只读）

- `GET /agents/categories/`、`GET /agents/categories/{id}/`
- `GET /agents/`（支持按分类过滤、搜索、排序）、`GET /agents/{id}/`
- `POST /agents/{id}/execute/` — 执行智能体（需登录），记录到 `AgentExecution`
- `GET /agents/my_executions/` — 当前用户的执行历史

### 模板 `/api/templates/`（需登录）

- 分类、CRUD、`POST /{id}/create_version/`（新建版本）、`POST /{id}/apply/`（应用为项目）
- `GET /templates/my_templates/`、`GET /templates/popular/`

### 对话 `/api/conversations/`（需登录）

- `GET /`（列表，支持 `?search=`）、`POST /`（新建）、`GET /{id}/`（详情含消息）
- `POST /{id}/send_message/` — 非流式发送
- **`POST /{id}/stream/`** — SSE 流式聊天（见下节）
- `POST /{id}/resume/` — 回答中途提问，或向支持 steering 的 agent 追加输入
- `POST /{id}/cancel-turn/` — 取消正在运行的 agent turn
- `DELETE /{id}/clear/`、`DELETE /{id}/delete_conversation/`

### 项目 `/api/projects/`（需登录）

- CRUD、`GET /projects/recent/`、`POST|DELETE /{id}/assets/`（项目素材）

### 市场 `/api/marketplace/`（需登录）

- `reviews/`、`comments/`、`favorites/` 各自的 CRUD
- `GET /market/trending/`、`GET /market/recommended/`、`GET /market/search/`

---

## Agent 适配器与流式对话

后端通过统一的 `AgentAdapter` 接口支持不同 agent 实现。内置 `graphflow` 和 `codex` 两个适配器，同步执行、长会话、SSE 事件、工具调用、取消和 steering 都先归一化再交给业务层：

- [`core/agent_engine/adapters/base.py`](backend/core/agent_engine/adapters/base.py) — 稳定的适配器、事件和操作状态契约
- [`core/agent_engine/adapters/registry.py`](backend/core/agent_engine/adapters/registry.py) — 可扩展的适配器注册表
- [`core/agent_engine/adapters/graphflow.py`](backend/core/agent_engine/adapters/graphflow.py) — 原有 GraphFlow `Manager + Event` 实现
- [`core/agent_engine/adapters/codex.py`](backend/core/agent_engine/adapters/codex.py) — 默认直接启动已安装 Codex CLI 的 app-server；可选兼容本地 Python SDK
- [`core/agent_engine/runtime.py`](backend/core/agent_engine/runtime.py) — 与具体实现无关的长生命周期会话注册表
- [`core/agent_engine/engine.py`](backend/core/agent_engine/engine.py) — 非流式调用的统一门面

全局通过 `AGENT_ENGINE_ADAPTER` 选择默认实现；单个 Agent 可在 `model_config` 中覆盖：

```json
{
  "adapter": "codex",
  "model": ""
}
```

Codex 适配器默认通过 stdio 直接启动 `codex app-server`，不依赖 Codex 源码仓库或 Python SDK。它优先使用源码构建产物或 Windows Codex App 自带的 `codex.exe`，再回退到 `PATH` 中的 `codex`；设置 `CODEX_TRANSPORT=python-sdk` 可切回旧 SDK 路径。适配器复用本机 Codex 登录状态，默认只授予工作区写权限。

要接入新的实现，继承 `AgentAdapter` 并在 Django 启动阶段调用 `register_agent_adapter("name", Factory)`；业务 API 无需改动。

**流式对话流程**（`POST /api/conversations/{id}/stream/`）：

1. 保存用户消息；
2. 按 Agent 配置创建或复用对应 adapter session，并提交 turn；
3. SSE 依次下发 `progress / question / permission / tool_start / tool_end / completed / failed / cancelled`；
4. `question`/`permission` 时连接保持打开，前端通过 `resume/` 调用 adapter 的恢复/steering 能力；
5. `completed` 后把最终回复及 token usage 落库并发送 `event: done`。

前端由 [services/sseClient.ts](frontend/src/services/sseClient.ts) 消费完整事件帧，在 [components/Chat](frontend/src/components/Chat) 中渲染实时进度、工具状态、问题/权限卡片及取消操作。

> 会话注册表是进程内状态；生产环境使用多个 Django worker 时，需要保证同一对话的 `stream/resume/cancel` 命中同一 worker，或把注册表迁移到独立的 Agent Engine 服务。

---

## LangChain ReAct 示例

[backend/examples/langchain_react/](backend/examples/langchain_react) 提供了一个独立的 ReAct（Reasoning + Acting）Agent 示例，演示「天气查询 / 计算 / 知识库搜索」等自定义工具的编排，并给出了与 C++ `ReActExecutor` / `ToolManager` / `PromptManager` 的概念对照。详见其 [README](backend/examples/langchain_react/README.md)。

---

## 前端路由与页面

| 路径 | 页面 | 说明 |
| --- | --- | --- |
| `/` | Home | 对话主界面（`ChatContainer`，支持 `?conversation=` 直接打开） |
| `/auth/login`、`/auth/register` | Auth | 公开路由，已登录会自动跳转 |
| `/agents`、`/agents/:id` | Agents | 智能体列表与详情 |
| `/templates`、`/templates/:id` | Templates | 模板列表与详情 |
| `/workspace`、`/workspace/:id` | Workspace | 项目工作区（左侧工具栏 + 画布 + 右侧属性面板） |

路由由 [router/index.tsx](frontend/src/router/index.tsx) 定义，登录态通过 [router/guards.tsx](frontend/src/router/guards.tsx) 中的 `ProtectedRoute` / `PublicRoute` 守卫。设计稿见仓库根目录的 `design-mockup.html` 与 `admin-mockup.html`。

---

## 测试

后端各应用在 `tests/` 子目录下提供了针对性测试，可用 Django 测试运行器执行：

```bash
cd backend
python manage.py test            # 运行全部
python manage.py test apps.conversations.tests.test_stream   # 运行单个
```

覆盖范围包括：对话搜索、流式接口、智能体/模板过滤器等。

---

## 开发约定与路线图

### 常用脚本

```bash
# 前端
npm run dev       # 开发服务器
npm run build     # tsc + vite build
npm run lint      # ESLint（0 warning 级别）
npm run preview   # 预览构建产物

# 后端
python manage.py makemigrations <app>
python manage.py migrate
python manage.py seed_mock_data
python manage.py createsuperuser     # 访问 /admin/
```

### 待完善（TODO）

- [ ] **Workspace 画布**：[WorkspacePage.tsx](frontend/src/pages/Workspace/WorkspacePage.tsx) 的工具栏 / 画布 / 属性面板目前为占位，待实现可视化编辑。
- [ ] 生产化 `SECRET_KEY`、API Key 外置（当前 `base.py` 提供了默认值，仅用于开发）。
- [ ] 对话历史窗口（当前固定最近 10 条）可配置化。

### 提交与协作

- 后端代码与文档注释以中文为主，新增内容请保持一致。
- 数据表名通过 `db_table` 显式声明（如 `agents`、`conversations`），迁移时请注意。
- 日志统一走 Django `LOGGING`（root level `INFO`，development 为 `DEBUG`）。

---

## License

MIT

---

## 批量转录 app（websocket 实时进度）

批量转录是可选功能。后端启动不依赖 `creation_core`；只有执行批量转录任务时才会按需导入该包。未安装时该任务会返回清晰的功能不可用错误，其余功能可正常使用。

后端需以 ASGI (daphne) 启动以同时承载 HTTP 与 websocket（单机部署）：

```bash
cd backend
# 确保 Redis 已起：docker compose up -d redis
./venv/Scripts/python.exe manage.py migrate
./venv/Scripts/python.exe manage.py seed_batch_transcribe   # 种入应用卡片
./venv/Scripts/python.exe -m daphne -b 127.0.0.1 -p 8080 backend.asgi:application
```

前端：

```bash
cd frontend
npm install && npm run dev    # :3030，/api 与 /ws 代理到 :8080
```

手动 E2E 检查清单（需本机有 Redis + ffmpeg + whisper 依赖）：
1. 浏览器打开 http://localhost:3030/apps ，登录后点「批量转录」卡片进入运行页。
2. 输入服务器视频文件夹路径（如 `D:\videos`），点「扫描」确认找到视频。
3. 选 Whisper 模型与语言，点「开始转录」。
4. 观察：进度条按文件推进、结果表格逐行填充、日志实时滚动；`<folder>/transcripts/` 下生成 `.txt`/`.srt`。
5. 同一 job URL 在第二个标签页打开 → 两个标签页同步收到实时事件（重连回放 snapshot）。
6. 运行中点「停止」→ 任务在文件之间优雅停止，状态变为 `stopped`。
