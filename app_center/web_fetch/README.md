# 网页爬取

应用 ID：`web-fetch`。一次提取一个公开 HTTP/HTTPS 网页或公众号文章，提供正文预览、Markdown/JSON、复制、下载、取消与私人历史。首版不支持登录、验证码、批量、递归、媒体文件下载或专门的社交站点 API。

借鉴 `baoyu-fetch` 的浏览器渲染、站点适配和本地正文转换流程；此应用独立实现，不复制或运行外部参考目录，不需要 Bun、模型或 Skill。依赖版本及许可证保留在 npm 包与锁文件中。

## 安装与启用

执行主机需要 Node.js 22.12+（建议 24 LTS）、项目 Python 虚拟环境和平台 media worker。Chromium 必须安装在运行 worker 的服务账号下。

Windows 仓库根目录：

```powershell
npm.cmd --prefix app_center/web_fetch/engine ci
node app_center/web_fetch/engine/node_modules/playwright/cli.js install chromium
backend\venv\Scripts\python.exe -X utf8 backend/manage.py validate_app_center
backend\venv\Scripts\python.exe -X utf8 backend/manage.py sync_app_center --package web-fetch
```

统一依赖安装器也支持 `--app web-fetch`（会同时安装共享前后端依赖，运行前按安装器要求停止使用虚拟环境的服务）：

```powershell
backend\venv\Scripts\python.exe -X utf8 deploy/install_dependencies.py --app web-fetch
```

Linux 使用项目 `backend/.venv/bin/python`。首次部署 Chromium 可运行 `node app_center/web_fetch/engine/node_modules/playwright/cli.js install --with-deps chromium` 安装系统库。容器镜像也必须在构建期间安装本包 npm 依赖、浏览器和系统库，并将 `PLAYWRIGHT_BROWSERS_PATH` 指向 worker 可读的浏览器目录；仅复制源码不足以运行抓取。

本包没有业务表或新迁移，复用 Run 和平台产物存储。首次增加清单后重启后端、media worker 和前端开发服务；生产环境构建并部署配套前端。应用按现有组织安装流程启用。

## 接口与存储

页面：`/applications/:applicationId/web-fetch`，保留 `entry=home/apps`、`standalone=1`、`embedded=1` 语义。`run` 查询参数用于恢复历史。

组织 API 前缀下：

- `POST applications/:application_id/web-fetch/runs`，请求 `{ "url": "https://…" }`，必需 `Idempotency-Key`，相同请求重放返回同一 Run；改变请求需新键。
- `GET applications/:application_id/web-fetch/runs?page=1`，本人历史，每页 20 条。
- `GET applications/:application_id/web-fetch/runs/:run_id`，Run 状态及产物。
- 事件流、取消和下载沿用平台 runtime API。下载必须同时满足当前用户权限及签名有效，前端通过平台 `content_path` 携带登录身份；不向外部存储发送认证头。

成功产物为 `article.md`（正文）和 `article.json`（`version: 1`，原始/最终地址、元信息、正文、媒体链接、提取方式、抓取时间及警告）。缺失元信息为 `null`；历史列表只返回摘要，不重复正文。跨组织、跨用户、未登录及应用停用时不能读取结果。

## 抓取与边界

- 无头 Playwright Chromium、独立上下文，不加载个人浏览器配置，不接受 Cookie/CDP 地址输入。
- 公众号优先识别 `#js_content`，通用页面依次使用本地 Defuddle、Readability、语义正文区域。关闭 Defuddle 异步外部抓取与第三方转换服务。
- DOMContentLoaded 超时 30 秒；网络空闲等待分别最多 4/2 秒，滚动最多 4 次；Python watchdog 限制引擎总时间 90 秒（任务平台另预留清理时间）。
- DOM 最大 5 MiB；代理最多 500 个经过认证的请求/隧道、40 MiB 下行传输（HTTPS 包含加密开销）。超限不会当作正常成功。
- 所有网页网络流量走任务专用认证代理。每个连接验证全部 DNS 地址，再直连已验证的数字 IP；HTTP、CONNECT、重定向和子资源均使用同一出口。拒绝非公网、混合 DNS 结果、云元数据、用户信息及非 80/443 端口。关闭 QUIC、非代理 WebRTC、Service Worker、WebSocket、弹窗及文件下载。
- 运行结束关闭浏览器与代理；取消或 90 秒超时由 Python 停止整个子进程树。Windows 使用隐藏进程及 `taskkill /T`，POSIX 使用独立进程组。
- 正文是来源网页数据，不是智能体指令。预览禁用原始 HTML、脚本和危险链接，图片显示可打开的原图链接，不自动加载第三方媒体。

## 验证

```powershell
npm.cmd --prefix app_center/web_fetch/engine test
backend\venv\Scripts\python.exe -X utf8 -m pytest app_center/web_fetch/backend/tests deploy/tests/test_install_dependencies.py -q
backend\venv\Scripts\python.exe -X utf8 -m pytest backend/modules/test_application_boundaries.py -q
npm.cmd --prefix frontend test -- app_center/web_fetch/frontend frontend/src/layouts/__tests__/webFetchLayout.test.ts
npm.cmd --prefix frontend run build
```

引擎测试使用固定 HTML、模拟浏览器和真实本机代理 socket，覆盖正文、公众号、回退、网络出口及 DNS 重绑定；不依赖外部站点。另可通过平台提交真实公开网页作人工验收。前端 jsdom 与 CSS 检查覆盖手机 HTTP 标识符兼容和页面滚动契约，不代表真机触摸或浏览器视觉验证。
