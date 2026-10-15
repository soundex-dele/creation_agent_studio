# Agent Studio 项目介绍

> 基于 2026 年 10 月 15 日的仓库源码、应用清单及配置整理。本文介绍项目定位与实现结构，不代表所有外部服务和应用能力均已在当前机器完成配置或运行验证。

## 1. 项目概述

Agent Studio 是一个集智能体对话、内容创作、知识管理、工作流和日常工具于一体的 AI 工作平台。用户可以直接使用应用中心里的场景应用，也可以围绕项目文件夹与 AI 持续协作，将多个应用组合成工作流，或通过自动化触发任务。

平台与应用的关系类似操作系统与应用程序：平台提供统一的身份权限、任务执行、模型调用、知识检索和文件产物能力，应用使用这些能力实现自己的业务。平台界面负责应用入口、导航和公共布局；应用包维护场景页面、业务规则、数据模型及运行逻辑，涵盖公众号与短视频创作、资料研究、会议整理、租房运营、学习辅助等领域。

这是模块化单体中的职责划分。平台与应用共享构建和发布流程，应用包集中在仓库根目录 `app_center/`，与平台前端、后端平级。

项目支持本地运行、服务器部署和桌面打包，并提供 Android / iOS 移动端外壳。当前配置默认启用单租户模式；需要组织隔离的部署可以显式启用多租户模式。

### 适用人群

| 人群 | 典型用途 |
| --- | --- |
| 内容创作者与运营人员 | 选题、文案、排版、配图、动画和视频制作，对标分析与品牌资料复用 |
| 个人与小团队 | AI 对话、在线文档、资料研究、会议整理、文件管理与待办记录 |
| 开发者与技术内容作者 | 围绕代码目录协作，从源码提炼选题并生成有依据的讲解文案 |
| 有私有部署需求的组织 | 统一管理智能体、应用、工作流、知识库、成员权限与使用额度 |

## 2. 核心能力

### 智能体与项目协作

平台提供智能体配置、持续会话、项目及工作目录管理。聊天请求会创建持久化任务，用户可以查看执行进度、历史输出及产物，并在任务需要补充信息或审批时继续交互。

默认智能体引擎为 Codex；项目也保留可选的 GraphFlow 适配能力。具体可用模型、工具和技能取决于执行主机上的安装及认证配置。

### 应用中心

应用以 `application.yaml` 声明名称、类别、界面和执行配置，通过校验、数据库迁移和同步命令接入平台。应用既可以使用平台通用表单和聊天界面，也可以拥有专用工作台和业务数据表。完成边界迁移的应用在清单中声明前端注册入口及后端扩展入口，由平台统一接入。

`app_center/` 收录数十个应用包，具体目录以源码清单为准；实际可见和可运行的应用还取决于同步、部署、权限及依赖配置。主要应用包括：

| 方向 | 代表应用 | 能力说明 |
| --- | --- | --- |
| 内容策划与写作 | 创作工具箱、公众号文章与选题应用、图文文案、短视频文案 | 从主题和资料生成选题、文章、逐页图文或口播文案 |
| 排版与图文交付 | 公众号排版引擎、Markdown 转 HTML、HTML 封面生成器、文章 HTML 配图、HTML 分页图文、HTML 批量转 PNG | 生成可编辑页面、公众号 HTML、分页图文及图片文件 |
| 图片与视频 | AI 绘图、动画制作、文案转剪映、创作大师 | 图片生成与参考图编辑、Remotion 动画、可编辑剪映草稿和媒体创作 |
| 品牌与内容研究 | 品牌资料库、案例库、抖音对标助手 | 管理品牌事实和范文，采集与分析对标作品，积累创作资料及脚本 |
| 文档与知识整理 | 在线文档、资料研究助手、会议与访谈助手 | 富文本编辑、成员共享、带出处的资料综合、录音转录与行动项整理 |
| 开发与提示词 | 仓库解读助手、提示词大师 | 基于源码生成选题及文案，通过交互澄清需求并生成、优化提示词 |
| 个人协作与文件 | 对话、随手记、我的网盘、我的电脑、微信助手 | 项目对话、想法待办、私人文件管理、远程访问和微信文本交互 |
| 垂直业务与生活 | 租房获客助手、学之有道、厨房助手 | 租房内容与客户跟进、学习辅助、菜谱与采购及食材管理 |
| 系统工具与游戏 | 磁盘清理大师、推箱子、口袋打捞队 | Windows 主机磁盘分析与确认清理，以及键盘和触屏游戏 |

### 工作流与自动化

工作流采用 DAG（有向无环图）编排，将应用组织为有依赖关系的步骤，支持条件分支、节点重试和有界并行。节点以独立子任务运行，父任务等待子任务时释放执行资源；需要用户输入时通过统一交互机制暂停和恢复。

自动化模块提供调度与 Webhook 触发能力，配合独立 scheduler 进程执行。任务记录仍沿用平台统一执行模型。

### 知识库与资料研究

组织知识库支持 PDF、DOCX、Markdown、TXT 和粘贴文本的提取、索引与有据问答。PostgreSQL 部署使用 pgvector / HNSW 与全文索引，SQLite 环境使用 sqlite-vec / FTS5；嵌入服务不可用时仍可进行词法检索。

资料研究助手提供个人研究项目，将选定资料保存为快照，生成研究报告、观点对照或写作资料包，并保留原文摘录和出处。它与组织知识库属于不同的产品入口。扫描版 PDF 需要先在外部完成 OCR。

### 权限与使用管理

平台具备账号、组织成员、角色、资源授权、审计和额度管理。多租户部署通过组织范围限制数据访问，PostgreSQL 部署还使用行级安全策略（RLS）。部分个人应用进一步按用户隔离业务资料，不能将“同一组织”理解为默认共享所有内容。

### 多端与远程访问

- **Web 端**：React 单页应用，承载主要产品界面和业务操作。
- **桌面端**：提供 Python 桌面启动器与打包脚本；创作大师另有独立的 Windows Qt 客户端。
- **移动端**：React Native WebView 外壳，连接用户填写的服务器网址，支持多窗口、下载、原生分享与安全凭据存储；网站与 API 仍由服务器提供。
- **我的电脑**：配对已授权的电脑，继续本机对话、使用远程终端和传输文件。终端及文件能力分别由电脑端启用，不提供远程桌面。

## 3. 技术架构

项目采用 **React 前端 + Django 模块化单体后端 + 独立执行进程**。架构分为应用层、平台公开接口和平台基础能力：应用表达业务需求，平台负责公共机制与执行保障。API 服务、任务协调器、自动化调度器和连接器可以作为不同进程运行，共享领域模型与持久化数据。

```mermaid
flowchart TB
    CLIENT[Web / 桌面入口 / 移动端 WebView] --> HOST[平台应用宿主：导航、鉴权、ApplicationShell]
    subgraph APPS[应用层：根目录 app_center]
        MANIFEST[application.yaml：界面、执行与扩展声明]
        APP_UI[应用前端：页面、组件、业务交互]
        APP_BACKEND[应用后端：API、数据模型、业务规则、runtime]
    end
    MANIFEST -. 注册 .-> HOST
    HOST --> APP_UI
    APP_UI --> FRONT_API[前端公开接口：@platform/*]
    FRONT_API --> HTTP[Django REST API / ASGI]
    HTTP --> APP_BACKEND
    APP_BACKEND --> BACK_API[后端公开接口：modules.platform_api]
    MANIFEST -. 声明 .-> EXT[平台扩展注册：访问策略、知识上下文、案例导航、调度]
    EXT -. 调用应用提供的钩子 .-> APP_BACKEND
    subgraph PLATFORM[平台基础能力]
        IDENTITY[身份、组织、资源权限与审计]
        CATALOG[Catalog：定义、修订与部署]
        RUN[Execution：统一 Run、事件、命令与租约]
        SERVICES[模型调用、知识检索、案例服务与文件产物]
    end
    BACK_API --> IDENTITY
    BACK_API --> RUN
    BACK_API --> SERVICES
    CATALOG --> RUN
    RUN --> EXT
    SERVICES --> EXT
    SCHEDULER[平台自动化调度器] --> RUN
    SCHEDULER --> EXT
    RUN --> WORKERS[Coordinator / 执行池 / 模型与媒体工具]
    PLATFORM --> DATA[(数据库、受控文件存储)]
    REDIS[(Redis：通知、缓存与心跳)] -. 唤醒与通知 .-> WORKERS
    RUN -. SSE 事件流 .-> FRONT_API
```

### 平台基础能力

| 能力 | 平台负责什么 | 应用负责什么 |
| --- | --- | --- |
| 界面宿主与前端公共能力 | 导航、鉴权、`ApplicationShell`、通用聊天/表单/任务渲染器、HTTP、任务事件及通用展示工具 | 声明路由和启动链接，实现业务页面、交互、样式及滚动容器 |
| 身份、组织与权限 | 账号、成员、资源授权、Tenancy 组织范围查询、租户上下文及数据库隔离辅助能力 | 说明业务资源的所有权与共享规则，通过扩展策略约束关联任务 |
| Catalog 定义管理 | 管理 Agent、Skill、Application 的草稿、不可变修订及部署，运行时使用已部署的定义版本 | 声明应用信息、界面入口、执行配置和依赖 |
| Execution 统一执行 | Run、执行尝试、队列、租约、幂等、事件、交互命令及取消/重试机制 | 提交业务输入、执行领域逻辑、处理业务结果与历史任务兼容 |
| 模型、知识与案例 | 复用模型调用与计费路径，提供知识索引/检索和案例服务 | 维护提示词、采集分析规则、资料归属及案例来源上下文 |
| 文件、产物与运行支撑 | 受控存储、产物记录与访问、审计观测、工作流和自动化调度机制 | 定义业务文件、成果格式及需要执行的业务步骤 |

### 应用包与依赖边界

一个应用包集中维护 `application.yaml`、`frontend/`、`backend/`、`runtime.py` 及所需资源和测试；具体目录按应用需要设置。厨房的菜谱、采购和烹饪规则，抖音的采集、对标分析和内容创作规则，都属于各自应用。

前端应用通过 `@platform/*` 使用公开能力，后端通过 `modules.platform_api` 使用身份、租户、执行、模型、知识库、案例和产物接口。公开接口复用平台原有实现，保留事务、计费、幂等和租约保护。当前部分身份、知识库及案例接口显式公开必要的 Django 模型，以维持原有外键和事务语义。

应用依赖自身代码和公开接口；跨应用业务协作使用明确的公开服务或平台导航。日期、错误展示、下载等通用工具由平台维护。平台核心通过扩展契约调用应用提供的逻辑，避免直接依赖具体应用的业务模块。

当前所有原有应用源码包已迁至根目录，**厨房助手和抖音对标已完成首批前后端归拢与公开接口接入**。其他应用仍保留兼容入口，部分页面和集成逻辑尚在平台目录中。依赖检查通过 `application_boundary_baseline.json` 冻结旧依赖，只允许随迁移减少；不能把目录搬迁等同于所有应用均已完成解耦。

### 声明注册与业务扩展

前端清单指向应用注册入口，入口导出 renderer key、原有路由、懒加载页面、启动链接和布局配置。Vite 与 Vitest 使用同一发现规则生成静态注册表，平台统一套用鉴权和 `ApplicationShell`。已有 React/Qt 变体继续由清单声明其目录。

后端清单声明扩展 provider，平台通过统一契约加载可选钩子：

| 扩展点 | 应用提供的业务信息 |
| --- | --- |
| 任务访问策略 `run_access` | 当前用户能否访问任务所属业务资源，包括历史任务的识别规则 |
| 知识上下文 `knowledge_context` | 创建知识索引任务时需要携带的业务上下文 |
| 案例导航 `case_navigation` / `case_targets` | 案例来源的回跳位置和当前用户可访问的目标 |
| 到期调度 `dispatch_scheduled` | 应用已有的到期业务处理，任务仍提交给统一执行引擎 |

这些入口来自随平台发布的受信任源码包，前后端统一构建和发布；当前不提供插件热安装或应用独立部署。

### 统一执行与权限保障

Agent、Conversation、Application、Workflow 和媒体执行都使用 `modules.execution.Run`。普通业务数据编辑仍由各应用 API 处理，并非每个操作都创建任务。

任务查询、事件流、命令及产物访问共用任务树权限策略，子任务沿相同组织的任务树检查根任务。持续事件流重新检查权限，受应用策略保护的产物通过需要再次鉴权的内容地址访问。适用的策略必须全部允许；策略加载或执行失败、关联资源失效时拒绝访问。应用在事务中写入执行结果时，通过平台 `active_run` 检查当前执行尝试和有效租约。

任务可以处于排队、运行、等待输入、等待子任务、成功、失败和取消等状态。数据库保存运行事实；Redis 用于通知、缓存及心跳，不是执行状态的最终来源。前端通过统一 Run 事件投影与 SSE 客户端处理增量输出、断线续接和历史恢复。

执行池分为 `agent`、`media`、`workflow`、`evaluation` 和 `knowledge`。SQLite 环境只运行一个 coordinator，可通过 `--worker-pool all` 轮询所有池；PostgreSQL 部署可按执行池拆分进程。

### 主要技术选型

| 层次 | 技术 |
| --- | --- |
| Web 前端 | React 18、TypeScript、Vite 7、React Router、Zustand |
| 界面与编辑 | Ant Design、Tailwind CSS、Tiptap、React Flow、xterm |
| 后端与 API | Python、Django 5.2、Django REST Framework、Daphne / ASGI、Channels |
| 数据与检索 | SQLite / PostgreSQL、Redis、pgvector、sqlite-vec、全文索引 |
| AI 与媒体 | Codex 适配器、可选 GraphFlow、Whisper、FFmpeg、Remotion、Playwright / Chromium |
| 移动端 | React Native、Android WebView、iOS WKWebView |
| 契约与测试 | OpenAPI、生成的 TypeScript 类型、Vitest、pytest、ESLint |
| 部署 | PowerShell / Shell 脚本、Docker Compose、桌面打包 |

## 4. 典型使用流程

### 内容创作

在品牌资料库准备账号定位、产品事实与写作样例，使用选题或对标应用确定方向，再由写作应用生成文章、图文或口播内容。用户审核后，可继续进行公众号排版、封面制作、分页图文、动画或剪映草稿制作。应用之间的交接方式取决于各自支持的入口，也可以由用户手动传递成果。

### 资料整理与办公

上传或导入文档，在资料研究助手中确定研究目标并选择资料，生成附带出处的成果，再导出为 Markdown 或保存为在线文档。录音可交给会议与访谈助手处理，经用户确认后将行动项保存为待办。

### 租房运营

维护房源和租客画像，生成平台文案与选题计划，手动发布后登记咨询、跟进和带看，最后记录成交及内容效果。应用提供内容建议与运营记录，发布、发送回复及效果录入仍由用户完成。

## 5. 仓库结构

```text
creation_agent_studio/
├── app_center/                # 应用包：业务源码、清单、资源与测试
│   ├── kitchen_assistant/     # 首批完成边界迁移的应用
│   │   ├── application.yaml   # 应用、前端入口与后端扩展声明
│   │   ├── frontend/          # 页面、组件、样式、客户端与前端测试
│   │   ├── backend/           # 业务 API、模型、迁移与后端测试
│   │   ├── runtime.py         # 使用平台执行能力的业务入口
│   │   └── extensions.py      # 向平台提供业务扩展钩子
│   ├── douyin_benchmark/      # 同样集中维护前后端业务与扩展
│   ├── creation_master/       # 保留独立工程结构的 Git 子模块
│   └── ...                    # 其余应用按依赖顺序迁移内部边界
├── frontend/                  # 平台 Web 界面、应用宿主与公共能力
│   ├── applicationPackages.ts # 从清单生成前端静态注册表
│   └── src/
│       ├── platform/          # @platform/* 公开接口
│       ├── router/            # 平台路由与声明式应用路由接入
│       ├── pages/             # 平台页面及尚未迁出的应用页面
│       ├── layouts/           # MainLayout / ApplicationShell 等公共布局
│       ├── entities/run/      # 统一任务事件投影
│       ├── features/run-stream/ # 实时任务状态编排
│       ├── services/          # API 与事件流客户端
│       └── api/generated.ts   # 自动生成的接口类型
├── backend/                   # 平台后端、公共能力与执行引擎
│   ├── backend/               # Django 配置、URL、ASGI 入口
│   ├── apps/                  # 智能体、会话、工作流、知识库与应用发现等平台域
│   ├── modules/
│   │   ├── platform_api/      # 面向应用的后端公开接口
│   │   ├── catalog/           # 定义、修订与部署
│   │   ├── execution/         # 唯一 Run 执行引擎
│   │   └── tenancy/           # 租户上下文与隔离能力
│   ├── core/                  # 模型调用、存储等公共能力的内部实现
│   ├── requirements/          # Python 依赖清单
│   ├── scripts/               # 校验、同步与运维脚本
│   ├── third_party/           # 第三方集成源码
│   ├── desktop_launcher.py    # 桌面启动入口
│   └── docker-compose.yml     # 容器服务编排
├── mobile/                    # Android / iOS 外壳
├── contracts/                 # API 与 Run 事件契约
├── teaching_data/             # 课程与答题卡数据子模块
├── deploy/                    # 部署配置与应用依赖映射
├── docs/                      # 部署、协议及专题文档
├── pytest.ini                 # 平台后端与根目录应用的统一测试配置
├── conftest.py                # 共享测试钩子与 fixtures
├── install-dependencies.ps1   # Windows 依赖安装
├── install-dependencies.sh    # Linux / macOS 依赖安装
├── deploy.ps1                 # Windows 本地启动
└── deploy.sh                  # Linux / macOS 本地启动
```

仓库包含创作大师、教学数据和抖音采集组件等 Git 子模块。首次获取源码应使用递归克隆，已有检出可执行 `git submodule update --init --recursive` 补齐锁定版本及嵌套依赖。

应用源码位置与运行数据位置分别管理。源码默认从根目录 `app_center/` 发现，也可通过 `APP_CENTER_ROOT` 显式配置；平台统一处理源码运行和桌面包的导入路径。目录迁移保持 Python 模块名、Django app label、表名及迁移历史不变，数据库、上传文件和工作目录继续使用原存储位置。

## 6. 本地运行与部署

### 基础环境

主项目要求 Python 3.11+（推荐 3.12）和 Node.js 20.19+ / 22.12+（推荐 24 LTS），并预先安装 Git。移动端及抖音采集组件有各自的运行环境要求；使用推荐版本后仍需按相应说明安装 SDK 或独立依赖。

以下 Windows 命令均从仓库根目录执行，后端 Python 使用项目虚拟环境 `backend\venv`。

### Windows 快速启动

首次安装依赖：

```powershell
powershell -ExecutionPolicy Bypass -File .\install-dependencies.ps1 -SystemDeps -WithCodex
```

安装脚本负责项目依赖及应用额外运行组件，不会代替模型登录、外部 Skill 安装和业务配置。更新已有环境时，应在相关服务停止后运行。

若需将全部内置应用同步到应用中心，安装完成后依次执行；每一步成功后再继续：

```powershell
.\backend\venv\Scripts\python.exe backend\manage.py validate_app_center
.\backend\venv\Scripts\python.exe backend\manage.py migrate --noinput
.\backend\venv\Scripts\python.exe backend\manage.py sync_app_center
```

启动本地开发服务：

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy.ps1
```

启动脚本执行迁移、检查并按需创建管理员，单独同步“学之有道”“我的电脑”“微信助手”，并按配置启动前端、后端、执行协调器、自动化调度器和连接器。它不会自动同步全部应用，因此全量应用初始化使用上面的同步命令。首次没有管理员时会进入创建流程。

默认前端地址为 `http://localhost:3030`，后端为 `http://localhost:8080`，产品 API 统一使用 `/api/v1`。开发前端将 API 请求代理至后端。保留启动终端，按 Ctrl+C 结束本次启动的服务。

Linux / macOS 提供对应的 `install-dependencies.sh` 与 `deploy.sh`；完整安装、配置及生产操作见 [部署指南](DEPLOYMENT.md)。

### 部署形态

- **本地开发**：SQLite、Django ASGI 开发服务、Vite 和单个执行协调器。
- **服务器部署**：Docker Compose 编排 PostgreSQL、Redis、ASGI Web、各执行池、调度器及维护服务，前端由静态服务提供。
- **桌面分发**：使用仓库内桌面打包脚本封装本地运行入口。
- **移动接入**：移动外壳连接已部署的网站；Android / iOS SDK 和打包环境需另行准备。

生产入口需支持 SSE，并为远程连接器提供 WebSocket 转发。具体反向代理、数据库、存储与认证配置以部署指南为准。

## 7. 配置与能力边界

| 能力 | 需要准备的条件或当前边界 |
| --- | --- |
| 智能体生成 | 执行引擎安装、认证、模型可用性和使用额度 |
| Skill 驱动的创作应用 | 完整外部 Skill 目录及其脚本依赖；配置 `CODEX_SKILLS_DIRECTORY`，应用清单不会自动内置这些技能 |
| 转录、截图和动画 | 按应用安装 FFmpeg、语音模型、Chromium / Playwright 或 Remotion 等组件 |
| 抖音对标 | 独立 DTK Python 环境与个人采集配置，实际可用性受平台接口和登录状态影响 |
| 文案转剪映 | 生成可编辑工程，配音需要可用 TTS；该应用本身不导出 MP4 |
| 资料提取 | 文字型 PDF、DOCX 等；扫描资料需外部 OCR |
| 远程访问 | 在线电脑、运行中的连接器、完成配对及启用相应权限 |
| 磁盘清理 | Windows 后端主机、平台管理员权限，以及预览后的明确确认 |

## 8. 开发与维护入口

应用开发与后续迁移以 [平台与应用包规范](APPLICATION_PACKAGES.md) 为主入口，厨房助手和抖音对标可作为代码示例。应用前端通过 `@platform/http`、`@platform/runtime` 等接口使用平台 HTTP 与任务能力；平台内部仍复用 `services/api.ts`、`services/runStream.ts` 等实现，接口类型由后端契约生成。后端业务通过 `modules.platform_api` 接入既有 Run、模型与数据服务。

新增应用应声明注册入口，避免在平台核心增加应用名称分支。后续迁移按依赖先后、同层按应用标识排序，每批归拢业务源码和测试、接入公开接口，再删除旧注册分支及对应依赖基线。通用聊天、表单与任务渲染器继续由平台维护。

常用检查命令如下，需先安装相应开发依赖：

```powershell
# 前端测试、静态检查与生产构建
npm.cmd --prefix frontend run test
npm.cmd --prefix frontend run lint
npm.cmd --prefix frontend run build

# 后端与应用测试：使用根目录配置，覆盖 app_center 和共享 fixtures
.\backend\venv\Scripts\python.exe -X utf8 -m pytest

# 平台与应用的依赖边界检查
.\backend\venv\Scripts\python.exe -X utf8 -m pytest backend/modules/test_application_boundaries.py
npm.cmd --prefix frontend run lint:applications

# 应用清单检查
.\backend\venv\Scripts\python.exe -X utf8 backend\manage.py validate_app_center
```

发布时使用匹配的前后端版本，校验清单并执行所需数据库迁移及应用同步。迁移验收需覆盖应用发现、启动路径、工作流、权限、事件流及布局约束；回退恢复配套代码与部署修订，保留用户数据。具体步骤见应用包规范。

本次文档更新核对了源码、清单和配置，未重新运行上述全量测试、启动服务或验证外部平台连接。移动布局和真实设备行为也不能由静态文档检查推断。

## 9. 延伸阅读

- [项目 README](../README.md)：安装、启动及整体说明。
- [平台与应用包规范](APPLICATION_PACKAGES.md)：公开能力、清单注册、扩展契约、依赖边界及后续迁移步骤。
- [架构分析](../ARCHITECTURE_ANALYSIS.md)：统一执行模型、版本管理与架构取舍；阅读时注意分析日期。
- [企业部署与运维](../ENTERPRISE.md)：组织权限、治理和生产运行。
- [部署指南](DEPLOYMENT.md)：容器、本地启动和远程访问配置。
- [应用中心说明](../app_center/README.md)：应用包规范和外部技能依赖。
- [移动端说明](../mobile/README.md)：Android / iOS 功能、环境及构建。
- [远程访问 API](REMOTE_ACCESS_API.md)：电脑配对、终端和文件传输协议。
- [成员 Token 配额](MEMBER_TOKEN_QUOTAS.md)：使用额度管理。
- [开发约定](../AGENTS.md)：虚拟环境、浏览器兼容和移动布局要求。
