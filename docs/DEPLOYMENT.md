# 服务器部署指南

已有服务器通过 `npm run dev` 运行、需要接入 Nginx 时，直接查看[非 Docker：Nginx 接入与正式部署](#非-dockernginx-接入与正式部署)。该章节同时覆盖保留开发服务和切换静态文件部署；下面编号 1–5 的章节适用于 Compose。

非容器部署请先在仓库根目录安装依赖，再执行数据库迁移和启动步骤：

```bash
# Linux / macOS
bash install-dependencies.sh --system-deps --with-codex
```

```powershell
# Windows PowerShell
powershell -ExecutionPolicy Bypass -File .\install-dependencies.ps1 -SystemDeps -WithCodex
```

前置条件、可选桌面端/移动端依赖和预演参数见根目录 [README](../README.md)。安装脚本会将依赖安装到后端虚拟环境及 npm 包目录，不会安装系统服务或修改 `.env`。下方 Compose 方案在镜像内部安装依赖。

默认包含全部仓库内应用的共享依赖、HTML 转 PNG 浏览器、动画制作 Remotion 引擎和无头浏览器，
以及抖音对标助手的 DTK 独立环境 `backend/.venv-dtk`。DTK 会校验固定版本 Git 子模块并执行
离线测试；主项目 Python 不兼容时通过 uv 准备 Python 3.13。采集 Cookie 仍需自行配置。
用 `--list-apps`（Windows `-ListApps`）查看应用清单；用 `--app animation-studio`
（Windows `-App animation-studio`）只补齐该应用的额外组件，共享依赖仍会安装。
外部 Skill 目录、模型登录和服务凭据会列为后续配置项；安装完成不等于这些服务已经联调。

## 1. 准备服务器

- 使用受支持的 Linux 系统，安装 Docker Engine 和 Docker Compose v2。
- 克隆仓库时使用 `--recurse-submodules`。所有启用的应用中心子模块都必须检出到主仓库记录的提交。
- Study With Method 应用依赖 `teaching_data` 子模块。部署前执行 `backend/.venv/bin/python backend/manage.py validate_teaching_data`；Windows 对应命令为 `backend\venv\Scripts\python.exe backend\manage.py validate_teaching_data`。数据集缺失或无效时，应用同步会主动失败。
- 尽量将 `backend/.env.example` 复制到仓库外受密钥管理保护的路径，通过 `BACKEND_ENV_FILE` 指定。
- 为 `SECRET_KEY`、`DB_ADMIN_PASSWORD`、`DB_PASSWORD` 和 `REDIS_PASSWORD` 分别生成独立随机值，不要复用模型供应商 API 密钥。

生产环境默认关闭注册。私有部署应保持关闭，通过 Django 管理后台或 SSO 配置账号。系统没有内置管理员密码，Django 只存储密码哈希。

## 2. 配置 DNS 和 TLS

Compose 仅将前端发布到 `127.0.0.1:3000`，不会在宿主机暴露 PostgreSQL、Redis 和 Django。请在宿主机安装反向代理，将公网 HTTPS 站点转发到该地址。[Caddy 配置示例](../deploy/Caddyfile.example)提供了最小配置。

将以下设置中的域名替换为最终 HTTPS 站点：

```dotenv
ALLOWED_HOSTS=studio.example.com
CORS_ALLOWED_ORIGINS=https://studio.example.com
REST_FRAMEWORK_NUM_PROXIES=2
JWT_REFRESH_COOKIE_SECURE=True
```

如果只有内置 Nginx 一层代理，将 `REST_FRAMEWORK_NUM_PROXIES` 设为 `1`。不要对外发布 8080、5432 或 6379 端口。

## 3. 启动并初始化

```bash
cd backend
BACKEND_ENV_FILE=/etc/agent-studio/backend.env docker compose up --build -d
BACKEND_ENV_FILE=/etc/agent-studio/backend.env docker compose exec web \
  python manage.py createsuperuser
```

`createsuperuser` 会提示输入初始管理员用户名和密码，此处输入的密码即登录密码。如需通过网页管理账号，设置 `DJANGO_ADMIN_ENABLED=True`，重启 `web` 服务后访问 `/admin/`。保持 `REGISTRATION_ENABLED=False`，通过 Django Admin 创建的用户仍可正常登录。忘记管理员密码时应重设密码，无法从旧哈希恢复原密码：

```bash
BACKEND_ENV_FILE=/etc/agent-studio/backend.env docker compose exec web \
  python manage.py changepassword ADMIN_USERNAME
```

使用初始管理员登录一次，确保单租户工作空间归属于预期所有者。通过 HTTPS 验证两个端点：

```bash
curl --fail https://studio.example.com/healthz/
curl --fail https://studio.example.com/readyz/
```

## 4. 备份与恢复

将以下内容作为一套完整恢复资料进行备份：

- 使用 `pg_dump --format=custom` 备份 PostgreSQL。
- 备份 `runtime_data` 数据卷；只有媒体和产物均已迁移至启用版本控制的对象存储时，才可省略。
- 将部署环境配置及密钥引用保存到密钥管理系统。
- 保存此次发布使用的准确镜像摘要和 Git 提交版本。

通过此 Compose 项目之外的调度器执行备份，加密后再复制到其他主机。必须在干净的预发布环境中恢复，并通过登录、媒体下载、知识检索及一次示例 Agent 执行后，才能认定备份有效。记录实测恢复点目标（RPO）和恢复时间目标（RTO）。

## 5. 发布检查

每次发布必须通过仓库 CI，从干净检出构建两个镜像，在恢复的生产数据库快照上执行迁移，并验证 `/readyz/`。不要将未经审核的 `docker compose up --build` 当作生产升级流程；应在 CI 中构建不可变镜像，并按镜像摘要部署。

曾提交到 Git 的供应商密钥必须在供应商侧撤销。仅从当前代码中删除密钥既不会使其失效，也不会从 Git 历史中移除。

## 非 Docker：Nginx 接入与正式部署

以下示例面向 Linux，假设 Nginx、前端和后端运行在同一台服务器，项目位于 `/opt/creation_agent_studio`，域名为 `studio.example.com`。替换为实际路径和域名。项目默认前端端口为 **3030**，后端为 **8080**；如果启动时覆盖了端口，需要同步修改代理地址。

两种方式共用后端代理路由：

| 方式 | 页面请求 | API / WebSocket | 适用场景 |
| --- | --- | --- | --- |
| 保留开发服务 | Nginx → Vite 3030 | Nginx → Django 8080 | 开发联调，保留热更新 |
| 正式部署 | Nginx → `frontend/dist` 静态文件 | Nginx → Daphne 8080 | 长期运行，不再启动 Vite |

仓库的 `frontend/nginx.conf` 是容器配置，其中 `web:8080`、`/usr/share/nginx/html` 和 `/data/...` 都是容器内地址，不能直接用于本节的宿主机部署。

### A. 保留 npm run dev，先接入 Nginx

1. 将域名解析到服务器 IP，安装 Nginx，放行入口端口 80（启用 HTTPS 时还需 443）。前后端仅需供本机 Nginx 访问，无需对公网开放 3030、8080。
2. 在 `frontend/vite.config.ts` 的现有 `server` 对象内增加 `allowedHosts: ['studio.example.com']`，保留原有 `port`、`fs`、`proxy`。不要用 `allowedHosts: true` 放开所有主机。
3. 在 `backend/.env` 的现有 `ALLOWED_HOSTS` 中合并 `studio.example.com`，例如 `ALLOWED_HOSTS=studio.example.com,localhost,127.0.0.1`，值中不包含协议和端口。重启后端使其生效。
4. 重启前端。手动启动时可在 `frontend/` 目录执行 `npm run dev -- --host 127.0.0.1 --port 3030 --strictPort`。这只启动前端；现有后端、执行 worker 和需要的连接器仍须运行。如果继续使用 `deploy.sh`，它会同时管理多项服务，注意避免重复启动和端口冲突，并通过防火墙限制开发端口的外部访问。

前端默认 API 基地址为 `/api/v1`，与网页同源，无需另设跨域地址。如果曾设置 `VITE_API_BASE_URL` 指向 `http://服务器IP:8080`，删除该覆盖或改为 `/api/v1`，然后重启 Vite；正式部署时则需重新构建。

创建 `/etc/nginx/conf.d/agent-studio.conf`，确保主配置在 `http {}` 中包含该目录。下面的 `map` 必须位于 `http` 上下文，不能放进 `server` 内：

```nginx
map $http_upgrade $studio_connection_upgrade {
    default upgrade;
    ''      close;
}

server {
    listen 80;
    server_name studio.example.com;
    server_tokens off;
    client_max_body_size 1024m;

    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Request-ID $request_id;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $studio_connection_upgrade;

    # AI/SSE 流式响应、长任务和 WebSocket。
    proxy_buffering off;
    proxy_request_buffering off;
    proxy_cache off;
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;

    # 远程文件使用分块上传，单请求保持 1 MiB 限制。
    location ^~ /api/v1/remote/ {
        client_max_body_size 1m;
        proxy_max_temp_file_size 0;
        gzip off;
        proxy_pass http://127.0.0.1:8080;
    }

    # proxy_pass 不带 URI，完整保留 /api/、/ws/ 等原始路径。
    location ~ ^/(api|ws|media|admin|static|healthz|readyz)(/|$) {
        proxy_pass http://127.0.0.1:8080;
    }

    # 包括 Vite 页面和 HMR WebSocket。
    location / {
        proxy_pass http://127.0.0.1:3030;
    }
}
```

检查配置成功后再重载；首次安装尚未运行 Nginx 时先启动服务：

```bash
sudo nginx -t
sudo systemctl enable --now nginx
sudo systemctl reload nginx
curl --fail http://studio.example.com/healthz/
```

此时访问 `http://studio.example.com`。这一方式仍是开发环境，添加 Nginx 不会自动把 Vite 或 Django 开发服务器切换为生产服务。若还需访问开发用的 `/swagger/`、`/redoc/` 或 `/swagger.json`，另行将这些路径代理到后端；上面的基础配置未包含 API 文档路由。

### B. 正式部署：静态前端 + Daphne + HTTPS

先完成依赖安装和域名配置，再按下述步骤准备生产后端、构建前端并切换 Nginx。保留现有数据库、媒体文件和 `SECRET_KEY`；不要用示例 `.env` 覆盖已有数据配置。

**后端配置和初始化**

以下命令从项目根目录执行，使用安装脚本默认创建的 `backend/.venv`；若服务器已有虚拟环境为 `backend/venv`，相应替换路径。

```bash
cd /opt/creation_agent_studio
backend/.venv/bin/python -m pip install -r backend/requirements/production.txt
```

在 `backend/.env` 合并以下 HTTPS 配置：

```dotenv
ALLOWED_HOSTS=studio.example.com,localhost,127.0.0.1
CORS_ALLOWED_ORIGINS=https://studio.example.com
REST_FRAMEWORK_NUM_PROXIES=1
SECURE_SSL_REDIRECT=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
JWT_REFRESH_COOKIE_SECURE=True
MEDIA_X_ACCEL_REDIRECT=False
MY_DRIVE_X_ACCEL_REDIRECT=False
```

这里假设只有一层 Nginx 代理，且 TLS 直接在这层终止；如前面还有负载均衡或 CDN，需重新确定可信代理链、协议头处理和 `REST_FRAMEWORK_NUM_PROXIES`。同源部署通常不需要额外 CSRF 信任域配置。

明确保留实际的 `DATABASE_ENGINE`、数据库路径/连接信息及 `REDIS_ENABLED`：开发设置未指定数据库时默认 SQLite，生产设置的默认值则是 PostgreSQL，不能依赖这两个默认值保持一致。生产设置要求 `SECRET_KEY` 至少 50 个字符；启用 Redis 时须配置 `REDIS_PASSWORD`。远程中继默认开启：无 Redis 时须显式设置 `REMOTE_RELAY_REDIS_URL=`、`REMOTE_RELAY_ALLOW_MEMORY=True`，并且只运行一个 Daphne 进程；不需要中继时可设置 `REMOTE_RELAY_ENABLED=False`。

```bash
cd /opt/creation_agent_studio/backend
export DJANGO_SETTINGS_MODULE=backend.settings.production
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py sync_app_center
.venv/bin/python manage.py collectstatic --noinput
.venv/bin/python manage.py check --deploy
# 仅首次安装且没有管理员时执行：
# .venv/bin/python manage.py createsuperuser
.venv/bin/python -m daphne -b 127.0.0.1 -p 8080 backend.asgi:application
```

逐条确认命令成功后再继续；先停止占用 8080 的旧后端。`manage.py` 和 `backend.asgi` 默认选择开发设置，所以必须在启动进程的环境中显式设置 `DJANGO_SETTINGS_MODULE=backend.settings.production`，仅在 `.env` 写 `DEBUG=False` 不足以切换。生产依赖包含 Sentry SDK，即使未配置 Sentry 上报也需要安装。

**构建前端并切换页面路由**

另开终端执行：

```bash
cd /opt/creation_agent_studio
npm --prefix frontend ci
npm --prefix frontend run build
```

构建成功后，在 A 节的 Nginx `server` 中删除原来转发到 3030 的 `location /`，替换为下列内容，保留其余后端代理配置。确保 Nginx 用户可以遍历父目录并读取 `frontend/dist`；不要把整个项目目录作为站点根目录。

```nginx
root /opt/creation_agent_studio/frontend/dist;
index index.html;

location / {
    try_files $uri $uri/ /index.html;
}

location /assets/ {
    try_files $uri =404;
    expires 1y;
    add_header Cache-Control "public, immutable";
}

location = /index.html {
    add_header Cache-Control "no-cache";
}
```

`try_files` 保证直接访问或刷新前端内部路由时仍能加载应用。切换并验证后可以停止 Vite，以后更新前端需重新构建发布；修改源码不会直接更新已部署页面。

**启用 HTTPS**

准备覆盖该域名的有效证书及续期机制。将上述应用 `server` 的 `listen 80;` 替换为以下监听和证书配置（路径按实际证书位置修改）：

```nginx
listen 443 ssl;
ssl_certificate /etc/letsencrypt/live/studio.example.com/fullchain.pem;
ssl_certificate_key /etc/letsencrypt/live/studio.example.com/privkey.pem;
ssl_protocols TLSv1.2 TLSv1.3;
```

在同一文件另加一个 HTTP 跳转块；若证书续期使用 HTTP-01 文件验证，按证书工具要求配置验证路径：

```nginx
server {
    listen 80;
    server_name studio.example.com;
    return 301 https://studio.example.com$request_uri;
}
```

保留应用块中的 `proxy_set_header X-Forwarded-Proto $scheme`，使后端识别 HTTPS，避免循环重定向。证书文件存在后执行 `sudo nginx -t`，成功再执行 `sudo systemctl reload nginx`。生产设置默认强制 HTTPS，因此不要把仅有 HTTP 的 A 节配置与这些生产设置组合后直接上线。

**静态资源、媒体及后台进程**

- `/static/` 继续代理到后端，由生产配置中的 WhiteNoise 提供 `collectstatic` 产物。前端的 `/assets/` 则由 Nginx 直接提供。
- 生产媒体 URL 为 `/api/v1/media/`，经后端鉴权。上面的 `*_X_ACCEL_REDIRECT=False` 让后端直接发送文件，无需配置 Nginx 文件别名。不要把媒体或私人网盘目录设为公开 `alias`。如启用 X-Accel 加速，须参考 `frontend/nginx.conf` 添加 `/_protected_media/` 和 `/_protected_drive/` 的 **internal** location，分别映射到实际的 `MEDIA_ROOT`、`MY_DRIVE_ROOT`，并赋予 Nginx 读取权限。
- AI 任务仍需执行 worker。在 `backend/` 中使用相同生产环境启动 `.venv/bin/python manage.py run_execution_coordinator --worker-pool all`。按已有业务需要另行保留 `run_remote_connector`、`run_wechat_connector`；Nginx 不会启动这些服务。纯中继部署不需要执行 worker。
- 用 systemd 等进程管理器托管 Daphne、worker 和所需连接器，为每个服务配置相同的工作目录、生产设置和必要的环境变量。不要在生产切换后重新运行 `deploy.sh`，它会再次启动开发前后端。

例如创建 `/etc/systemd/system/agent-studio-backend.service`，将 `User` 改为已有且拥有项目运行权限的服务账号（示例 `agentstudio` 需要事先创建），并确认它能读取 `backend/.env`、写入所需数据及日志目录：

```ini
[Unit]
Description=Agent Studio ASGI backend
After=network.target

[Service]
Type=simple
User=agentstudio
WorkingDirectory=/opt/creation_agent_studio/backend
Environment=DJANGO_SETTINGS_MODULE=backend.settings.production
ExecStart=/opt/creation_agent_studio/backend/.venv/bin/python -m daphne -b 127.0.0.1 -p 8080 backend.asgi:application
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

后端会读取项目的 `backend/.env`。若已有配置只存在于启动终端的环境变量中，需要迁入服务环境或该文件。停止前台测试用的 Daphne 后执行：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now agent-studio-backend
sudo systemctl status agent-studio-backend
```

worker 可使用独立 unit，保持相同的 `User`、工作目录和环境，将 `ExecStart` 替换为 `/opt/creation_agent_studio/backend/.venv/bin/python manage.py run_execution_coordinator --worker-pool all`。服务账号还须具备各应用实际需要的工具、模型登录和数据目录权限。

### C. 验证和常见问题

```bash
sudo nginx -t
curl --fail https://studio.example.com/healthz/
curl --fail https://studio.example.com/readyz/
```

上线时还需验证登录、刷新应用内部路由、一次 AI 流式任务，以及已启用的远程连接和文件上传下载。健康检查通过不代表这些业务流程均已验证。

| 现象 | 检查项 |
| --- | --- |
| 502 Bad Gateway | 3030/8080 服务是否运行、监听地址是否与 `proxy_pass` 一致；切换静态模式后页面不应再依赖 3030 |
| Vite 提示主机不允许 | `allowedHosts` 是否包含实际域名，修改后是否重启 Vite |
| Django 返回 400 / DisallowedHost | `ALLOWED_HOSTS` 是否包含请求域名，后端是否重启 |
| 页面能打开但 API 请求失败 | 浏览器是否仍请求旧的 `VITE_API_BASE_URL`，`/api/` 是否完整转发，前端是否重新构建 |
| AI 回复积攒到最后才显示 | Nginx 及上游代理/CDN 是否关闭响应缓冲和缓存 |
| 远程连接或热更新失败 | WebSocket 的 Upgrade/Connection 头、后端 ASGI 服务、HTTPS 对应的 `wss://` 连接 |
| HTTPS 循环跳转或登录 Cookie 异常 | TLS 终止位置、`X-Forwarded-Proto`、生产设置和 Secure Cookie 是否匹配 |
| 文件请求返回 413 | 是否命中预期 location；普通上传按业务调整上限，远程文件接口保持分块限制 |
| 页面刷新 404 / 资源返回 HTML | SPA `try_files`、站点根目录，以及 `/assets/` 是否存在且可读取 |

配置错误查看 `/var/log/nginx/error.log`；后端服务日志使用 `journalctl -u agent-studio-backend -n 100 --no-pager`。本节提供配置和验收步骤，实际证书、端口及业务连通性需在目标服务器上验证。

## Windows：一键启动本地环境

在仓库根目录使用 PowerShell。先安装依赖，并根据实际数据库和 Redis 环境配置 `backend/.env`，然后执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy.ps1
```

脚本使用项目虚拟环境 `backend\venv\Scripts\python.exe`，依次执行数据库迁移、首次管理员创建，以及 `study-with-method`、`my-computer`、`wechat-assistant` 应用同步；随后启动前端、Django 后端、执行 worker、远程连接器和微信连接器。已有管理员时跳过创建；否则交互式提示创建账号。无人值守启动时需同时设置 `DJANGO_SUPERUSER_USERNAME`、`DJANGO_SUPERUSER_PASSWORD` 和 `DJANGO_SUPERUSER_EMAIL`。

默认前端地址为 `http://localhost:3030`，后端端口为 `8080`。脚本兼容 Windows PowerShell 5.1 及 PowerShell 7，可通过以下环境变量配置：

| 环境变量 | 默认值 / 用途 |
| --- | --- |
| `BACKEND_HOST` | `0.0.0.0`，后端监听地址 |
| `BACKEND_PORT` | `8080`，后端端口 |
| `FRONTEND_PORT` | `3030`，前端端口；端口占用时启动失败 |
| `VITE_PROXY_TARGET` | `http://127.0.0.1:<BACKEND_PORT>`，前端代理目标 |
| `EXECUTION_WORKERS_ENABLED` | `True`；纯中继端设为 `False` |
| `REMOTE_ACCESS_HOST_ENABLED` | `True`；纯中继端设为 `False` |
| `REMOTE_CONNECTOR_LOCAL_URL` | `http://127.0.0.1:<BACKEND_PORT>`，连接器访问本机后端的地址 |

Django 配置继续读取环境变量和 `backend/.env`。上表中的启动选项请在启动终端通过 `$env:变量名 = '值'` 设置。设置示例：

```powershell
$env:BACKEND_PORT = '8082'
$env:FRONTEND_PORT = '3032'
powershell -ExecutionPolicy Bypass -File .\deploy.ps1
```

查看帮助或仅检查依赖、端口参数并打印启动计划（不修改数据库、不启动进程）：

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy.ps1 -Help
powershell -ExecutionPolicy Bypass -File .\deploy.ps1 -DryRun
```

服务在后台运行，不会弹出额外窗口。日志保存在每次启动独立的 `backend\logs\deploy-时间戳-进程号\` 目录，分别记录各服务的标准输出和错误输出。保留启动终端，按 Ctrl+C 会清理本次启动的服务及子进程；任一服务退出时，脚本报错并清理其他服务。请通过 Ctrl+C 停止，避免直接强制结束启动终端。后端使用 `--noreload`，修改后端代码后需要重启脚本；前端保留 Vite 热更新。

此脚本与 `deploy.sh` 一样用于本地开发和联调，使用 Django 开发服务器和 Vite，不会注册 Windows 服务或开机启动任务。生产部署使用上方 Compose 或下方 Daphne + Caddy 方案。

## 远程访问 / 我的电脑

### 文件传输

按 **中继 → 电脑端 → 前端** 顺序升级。两端执行数据库迁移，电脑端重启本机后端与单实例连接器，前端执行 `npm ci` 和 `npm run build`，同步 `my-computer` 应用包。迁移 `remote_access.0004` 增加默认关闭的 `file_transfer_enabled`；升级不会自动开放文件访问。最后由本机管理员在 **设置 → 远程访问 → 允许文件传输** 显式开启，无需开启远程终端。旧电脑缺少能力字段时，文件页显示升级提示。

文件页供桌面和手机浏览器浏览运行服务账号可访问的磁盘/目录，多选上传、单文件下载；上限 2 GiB，每台电脑最多 2 上传和 2 下载，额外任务在网页排队。目录是被控服务所在操作系统/容器看到的目录，实际权限由该账号及挂载决定。Windows 特殊设备路径/备用数据流、设备文件和管道被拒绝。上传临时文件放在目标目录，要求目录可写；同名不覆盖。POSIX 目标文件系统需支持硬链接以便安全提交。文件模块不新增 Python 平台依赖，桌面打包沿用 apps 子模块收集；前端锁文件加入用于 HTTP 局域网分块校验的 `@noble/hashes`。

浏览器与 API 必须同源，使下载入口使用作用域仅限具体文件地址、1 小时有效的签名 HttpOnly Cookie。HTTPS 部署保持 `JWT_REFRESH_COOKIE_SECURE=True`，受控 HTTP 部署按现有说明设为 False。下载链接没有登录令牌，保存由浏览器管理；网页的“已发送给浏览器”不代表已落盘。原生 Range 续传能力取决于浏览器。中继最多等待短暂断线 60 秒，超过后结束响应。

内置 Nginx 的 `/api/v1/remote/` 单独保持 **1 MiB** 请求限制，无需为 2 GiB 文件提高请求体上限。该 location 使用 `proxy_buffering off`、`proxy_request_buffering off`、`proxy_max_temp_file_size 0`、`proxy_cache off`、`gzip off` 和 3600 秒代理读写超时。自建反向代理/CDN 同样应直通 Content-Length、Content-Disposition、ETag、Accept-Ranges、Content-Range、Set-Cookie，关闭下载压缩、响应缓冲和缓存。中继及代理/APM 不记录文件正文或鉴权 Cookie，不将下载响应保存到临时文件。

切换工作区页签保留网页任务，刷新/关闭网页不保证上传恢复。连接器重启后旧任务失效；正常停止、关闭权限或授权撤销会清理未完成上传。强制退出的残留由目标目录临时文件及连接器锁目录旁 `remote-file-transfers` 日志进行标识核对，闲置 24 小时后清理；不要将这两个位置作为业务文件持久化来源。完成文件不受权限关闭影响。此版本不提供文件夹传输、预览、删除、移动或重命名，也不修改 Android 原生外壳。

实际双后端验证命令见 [文件传输 API](REMOTE_ACCESS_API.md#文件传输v1-帧兼容扩展)，支持 `--files --terminal` 同时验证内存中继、聊天和真实终端；`--redis-url` 可覆盖 Redis 中继。

### 远程终端

升级顺序：先升级中继服务器，再升级被控电脑，执行数据库迁移并重启本机后端与连接器，最后由本机管理员在 **设置 → 远程访问 → 允许远程终端** 开启。已有绑定默认不会自动获得终端权限。电脑卡片上的 **远程终端** 可进入多会话工作区；旧版电脑显示升级提示。

后端依赖已纳入 `requirements/base.txt`：Windows 使用 `pywinpty`/ConPTY（需支持 ConPTY 的 Windows），Linux/macOS 使用 `ptyprocess` 和 `psutil`。Windows 首选 `pwsh`，否则使用 Windows PowerShell；Linux/macOS 使用运行账号的默认 Shell。初始目录为该账号主目录。前端使用按需加载的 xterm 与 Fit 插件；无需新增端口或 SSH 服务。桌面包包含终端依赖并通过退出通知及 Windows Job Object 清理终端子进程。

Windows 更新命令（仓库根目录）：

```powershell
backend\venv\Scripts\python.exe -m pip install -r backend\requirements\base.txt
backend\venv\Scripts\python.exe backend\manage.py migrate
```

终端命令以本机服务的操作系统账号执行。退出网页或中继断网后程序继续运行；关闭终端、关闭远程终端权限、关闭远程访问或停止本机服务会结束会话。每电脑最多 8 个运行终端，输出仅保留最近 1 MiB，不跨连接器重启恢复。生产反向代理沿用现有 SSE 禁缓冲与 WebSocket 配置；中继、代理及 APM 不应记录终端正文。

更新时执行迁移、重新构建前端，并与其他应用一起同步 `my-computer` 应用。常规 Compose 初始化流程已执行迁移和所有应用的 `sync_app_center`。内置 Nginx 支持 `/ws/remote/connector/` 的 WebSocket 升级，并关闭 HTTP/SSE 代理缓冲。

服务器配置：

```dotenv
REMOTE_RELAY_ENABLED=True
REMOTE_ACCESS_HOST_ENABLED=False
# 默认使用常规 Redis 配置，只有需要覆盖时才设置：
# REMOTE_RELAY_REDIS_URL=redis://:password@redis:6379/0
```

使用 ASGI 入口 `backend.asgi:application`（容器内使用 Daphne）。WSGI 无法处理连接器 WebSocket。多个 ASGI 进程必须共享同一数据库和 Redis；单进程安装可按下文显式启用内存中继。Redis 中继仅使用 Pub/Sub，常规 Redis 持久化不会保留转发的消息体。基础设施日志和 APM 不应采集远程访问路由的消息体或鉴权请求头。此功能没有额外提供端到端加密：HTTP 对应 WS，HTTPS 对应 WSS。

在被控电脑上使用源码安装时，`./deploy.sh`（Windows 使用 `deploy.ps1`）会同时管理后端、执行 worker 和 `run_remote_connector`，默认将 `REMOTE_CONNECTOR_LOCAL_URL` 设为配置的后端端口，并同步 `my-computer`。连接器在设置中启用前保持空闲。也可使用项目虚拟环境单独启动：

```bash
# Linux / macOS
cd backend
REMOTE_ACCESS_HOST_ENABLED=True .venv/bin/python manage.py migrate
REMOTE_ACCESS_HOST_ENABLED=True .venv/bin/python manage.py run_remote_connector
```

```powershell
# Windows，在仓库根目录执行
$env:REMOTE_ACCESS_HOST_ENABLED = 'True'
$env:REMOTE_CONNECTOR_LOCAL_URL = 'http://127.0.0.1:8080'
.\backend\venv\Scripts\python.exe backend\manage.py migrate
.\backend\venv\Scripts\python.exe backend\manage.py run_remote_connector
```

单独启动的 Django API 也必须设置 `REMOTE_ACCESS_HOST_ENABLED=True`。`REMOTE_CONNECTOR_LOCAL_URL` 必须是回环地址上的 HTTP 源。打包后的桌面启动器会自动启用被控能力并管理连接器进程，其 API 地址为 `http://127.0.0.1:8765`。PyInstaller 已包含连接器和 WebSocket 依赖；打包前请安装更新后的 requirements。

1. 在电脑端打开 **设置 → 远程访问**，输入服务器根 URL 和电脑名称，明确选择本地用户与组织，保存并启用。
2. 生成配对码。在手机端登录服务器，打开 **我的电脑**，在 10 分钟内输入配对码。
3. 在电脑端确认显示的服务器账号。在手机端选择在线电脑，即可发起或继续会话。
4. 关闭访问会断开连接但保留绑定；解绑会撤销凭据。如果解绑时服务器不可达，本地会先禁用访问，网络恢复后还需重试撤销。

关闭浏览器不会停止连接器；停止本地后端、连接器或桌面应用会使电脑离线。系统不会安装操作系统服务、登录启动任务、网络唤醒或离线指令队列。文件传输从独立“文件”页操作，聊天附件沿用现有行为；不提供远程桌面。

协议和端点说明见 [REMOTE_ACCESS_API.md](REMOTE_ACCESS_API.md)。远程访问测试须使用后端虚拟环境。设置 `REMOTE_TEST_REDIS_BINARY=/path/to/redis-server` 可启用真实 Redis 跨进程测试；测试会创建隔离的临时本地 Redis 实例，并验证未写入任何数据键。

## 开发联调：同时启动两套前后端

在仓库根目录打开两个终端。可在同一台电脑运行，也可在两台均已检出仓库并安装依赖的电脑运行。两端都使用 HTTP，不依赖 Redis。脚本会初始化数据库、在需要时提示创建初始管理员，并同步“我的电脑”等应用。

### Linux / macOS

终端 1：中继服务器，前端 **3031**，后端 **8081**：

```bash
DJANGO_SETTINGS_MODULE=backend.settings.development \
DATABASE_ENGINE=sqlite REDIS_ENABLED=False REMOTE_RELAY_REDIS_URL= \
JWT_REFRESH_COOKIE_SECURE=False JWT_REFRESH_COOKIE_NAME=agent_studio_relay_refresh \
SQLITE_PATH="$PWD/backend/dev-relay.sqlite3" \
REMOTE_RELAY_ENABLED=True REMOTE_RELAY_ALLOW_MEMORY=True \
REMOTE_ACCESS_HOST_ENABLED=False EXECUTION_WORKERS_ENABLED=False \
BACKEND_PORT=8081 FRONTEND_PORT=3031 \
bash ./deploy.sh
```

终端 2：被控电脑，前端 **3030**，后端 **8080**：

```bash
DJANGO_SETTINGS_MODULE=backend.settings.development \
DATABASE_ENGINE=sqlite REDIS_ENABLED=False REMOTE_RELAY_REDIS_URL= \
JWT_REFRESH_COOKIE_SECURE=False \
SQLITE_PATH="$PWD/backend/dev-computer.sqlite3" \
REMOTE_ACCESS_HOST_ENABLED=True REMOTE_RELAY_ENABLED=False \
EXECUTION_WORKERS_ENABLED=True BACKEND_PORT=8080 FRONTEND_PORT=3030 \
bash ./deploy.sh
```

### Windows PowerShell

终端 1：中继服务器，前端 **3031**，后端 **8081**：

```powershell
$env:DJANGO_SETTINGS_MODULE = 'backend.settings.development'
$env:DATABASE_ENGINE = 'sqlite'
$env:REDIS_ENABLED = 'False'
$env:REMOTE_RELAY_REDIS_URL = ''
$env:JWT_REFRESH_COOKIE_SECURE = 'False'
$env:JWT_REFRESH_COOKIE_NAME = 'agent_studio_relay_refresh'
$env:SQLITE_PATH = Join-Path $PWD.Path 'backend\dev-relay.sqlite3'
$env:REMOTE_RELAY_ENABLED = 'True'
$env:REMOTE_RELAY_ALLOW_MEMORY = 'True'
$env:REMOTE_ACCESS_HOST_ENABLED = 'False'
$env:EXECUTION_WORKERS_ENABLED = 'False'
$env:BACKEND_PORT = '8081'
$env:FRONTEND_PORT = '3031'
powershell -ExecutionPolicy Bypass -File .\deploy.ps1
```

终端 2：被控电脑，前端 **3030**，后端 **8080**：

```powershell
$env:DJANGO_SETTINGS_MODULE = 'backend.settings.development'
$env:DATABASE_ENGINE = 'sqlite'
$env:REDIS_ENABLED = 'False'
$env:REMOTE_RELAY_REDIS_URL = ''
$env:JWT_REFRESH_COOKIE_SECURE = 'False'
$env:JWT_REFRESH_COOKIE_NAME = 'agent_studio_refresh'
$env:SQLITE_PATH = Join-Path $PWD.Path 'backend\dev-computer.sqlite3'
$env:REMOTE_ACCESS_HOST_ENABLED = 'True'
$env:REMOTE_RELAY_ENABLED = 'False'
$env:EXECUTION_WORKERS_ENABLED = 'True'
$env:BACKEND_PORT = '8080'
$env:FRONTEND_PORT = '3030'
powershell -ExecutionPolicy Bypass -File .\deploy.ps1
```

两端分别创建独立的数据库。中继端不启动执行 worker 和远程连接器；被控端同时启动二者。两个启动脚本仍会启动微信连接器，未配置时保持空闲。中继端使用独立的刷新 Cookie 名称，避免同一主机不同端口的登录相互覆盖。

如果需要使用已有本地数据，将 `SQLITE_PATH` 改为对应数据库的绝对路径。中继端和被控端不能共享数据库。使用绝对路径可保证管理命令和运行中的后端始终访问同一数据库，不受工作目录变化影响。若 `backend/.env` 已设置非空 `REMOTE_RELAY_REDIS_URL`，请一并清空，确保未启用 Redis 中继。

在被控电脑上打开 `http://localhost:3030`，配置 **设置 → 远程访问**。单机联调时服务器地址为 `http://127.0.0.1:3031`；双机联调时使用 `http://SERVER_IP:3031`，并按需配置防火墙和 `ALLOWED_HOSTS`。在另一个浏览器或手机上打开服务器地址，登录后在 **我的电脑** 中输入配对码，再回到电脑端确认账号。两套安装各自拥有独立账号。内存中继服务器必须保持单个 ASGI 服务进程。

脚本通过 `VITE_PROXY_TARGET` 将后端地址传给 Vite，`FRONTEND_PORT` 控制前端监听端口。端口冲突时启动失败，不会静默切换到其他端口。单独启动中继端前端时可执行：

```bash
VITE_PROXY_TARGET=http://127.0.0.1:8081 npm --prefix frontend run dev -- --host 0.0.0.0 --port 3031 --strictPort
```

```powershell
$env:VITE_PROXY_TARGET = 'http://127.0.0.1:8081'
npm.cmd --prefix frontend run dev -- --host 0.0.0.0 --port 3031 --strictPort
```

在任一启动终端按 Ctrl+C 可停止该端所管理的进程。启动前先停止占用相关端口的旧进程，或选择其他端口组合。

## 无 Redis 的独立 HTTP 中继服务器

此方案使用一个生产模式 Daphne 进程进行内存转发，由 Caddy 在 3000 端口提供前端静态文件并代理 HTTP/SSE/WebSocket。`DEBUG` 保持关闭。现有 Compose 栈包含 Redis，因此此方案不使用 Compose。HTTP 对应的连接器使用 `ws://`，流量不加密。

后端需要生产依赖，包括 Sentry SDK（生产设置即使关闭上报仍会导入该依赖）：

```bash
backend/.venv/bin/python -m pip install -r backend/requirements/production.txt
```

```powershell
.\backend\venv\Scripts\python.exe -m pip install -r backend\requirements\production.txt
```

新安装请先安装项目依赖和 Caddy，再将 `backend/.env.remote-http.example` 复制为 `backend/.env`。已有安装应将以下配置合并到原 `.env`，保留原数据库配置和持久化的 `SECRET_KEY`：

```dotenv
REDIS_ENABLED=False
REMOTE_RELAY_ENABLED=True
REMOTE_RELAY_REDIS_URL=
REMOTE_RELAY_ALLOW_MEMORY=True
REMOTE_ACCESS_HOST_ENABLED=False
SECURE_SSL_REDIRECT=False
SESSION_COOKIE_SECURE=False
CSRF_COOKIE_SECURE=False
JWT_REFRESH_COOKIE_SECURE=False
ALLOWED_HOSTS=YOUR_SERVER_IP,localhost,127.0.0.1
REST_FRAMEWORK_NUM_PROXIES=1
```

将 `YOUR_SERVER_IP` 替换为实际 IP 或主机名，不包含协议和端口。新安装模板使用 SQLite，已有 PostgreSQL 安装可以保留其数据库设置。新安装需要至少 50 个字符的密钥；使用项目虚拟环境生成，保存到 `.env`，并在重启后继续使用：

```bash
backend/.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(48))'
```

```powershell
.\backend\venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
```

### Linux / macOS 启动

从仓库根目录执行初始化，仅首次安装需要创建管理员：

```bash
cd backend
export DJANGO_SETTINGS_MODULE=backend.settings.production
.venv/bin/python manage.py migrate
.venv/bin/python manage.py sync_app_center
.venv/bin/python manage.py collectstatic --noinput
.venv/bin/python manage.py createsuperuser
```

保持生产设置环境变量，在 `backend/` 下启动后端：

```bash
.venv/bin/python -m daphne -b 127.0.0.1 -p 8080 backend.asgi:application
```

另开终端，在仓库根目录构建前端并启动 Caddy：

```bash
npm --prefix frontend run build
APP_FRONTEND_ROOT="$PWD/frontend/dist" caddy run --config deploy/Caddyfile.http.example --adapter caddyfile
```

### Windows PowerShell 启动

从仓库根目录进入后端目录，初始化并启动 Daphne。仅首次安装需要执行 `createsuperuser`：

```powershell
Set-Location backend
$env:DJANGO_SETTINGS_MODULE = 'backend.settings.production'
.\venv\Scripts\python.exe manage.py migrate
.\venv\Scripts\python.exe manage.py sync_app_center
.\venv\Scripts\python.exe manage.py collectstatic --noinput
.\venv\Scripts\python.exe manage.py createsuperuser
.\venv\Scripts\python.exe -m daphne -b 127.0.0.1 -p 8080 backend.asgi:application
```

确认每步成功后再执行下一步。另开 PowerShell 终端，在仓库根目录构建前端并启动 Caddy（需已安装且位于 PATH）：

```powershell
npm.cmd --prefix frontend run build
if ($LASTEXITCODE -ne 0) { throw '前端构建失败' }
$env:APP_FRONTEND_ROOT = (Join-Path $PWD.Path 'frontend\dist').Replace('\', '/')
caddy run --config deploy/Caddyfile.http.example --adapter caddyfile
```

访问 `http://YOUR_SERVER_IP:3000` 登录。Caddy 提供前端，并将 API、管理后台、静态资源、健康检查及 WebSocket 路由转发给 Daphne。配置示例关闭代理响应缓冲，确保 SSE 持续流式传输。若需终端退出后继续运行，应使用进程管理器，例如 Linux 的 systemd 或 Windows 服务管理工具。

此服务器必须运行**恰好一个** Daphne 进程/副本，HTTP 请求与连接器 WebSocket 必须到达同一进程。内存状态和限流信息不跨进程共享。如需多个 worker 或副本，请配置共享 Redis。只要 `REMOTE_RELAY_REDIS_URL` 非空就会选择 Redis，Redis 故障时不会自动回退到内存。

在被控电脑上照常使用 `bash ./deploy.sh`（Windows 使用 `powershell -ExecutionPolicy Bypass -File .\deploy.ps1`），设置 `REMOTE_ACCESS_HOST_ENABLED=True`、`REMOTE_RELAY_ENABLED=False` 和本地数据库配置；没有 Redis 时还需设置 `REDIS_ENABLED=False`。在 **设置 → 远程访问** 中填写 `http://YOUR_SERVER_IP:3000`，选择本地身份并生成配对码，在服务器的 **我的电脑** 页面输入后回到电脑端确认账号。本地启动器会管理连接器和执行 worker；纯中继服务器无需运行它们。

使用隔离的本地数据库验证无 Redis 的生产 HTTP 模式：

```bash
backend/.venv/bin/python backend/scripts/test_remote_local.py --production-server
```

```powershell
.\backend\venv\Scripts\python.exe backend\scripts\test_remote_local.py --production-server
```
