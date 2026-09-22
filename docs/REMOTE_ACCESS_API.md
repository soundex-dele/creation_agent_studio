# 远程访问接口与协议 v1

实现对应 `REMOTE_ACCESS_PLAN.md`。服务器只保存账号、配对和连接元数据；对话、Run、Command、幂等记录及文件仍由被控电脑保存。

## 本机配置

使用现有账号认证。本地管理员（平台 admin 或 superuser）可以修改配置；其他用户只能查询能力标识。`REMOTE_ACCESS_HOST_ENABLED=False` 时配置入口不显示，修改接口返回 404。

| 方法 | `/api/v1/remote-access/` 下的路径 | 请求与响应 |
| --- | --- | --- |
| GET | 空路径 | `host_enabled`、`manageable`；管理员还获得配置、用户/组织选项和连接状态，不返回凭证 |
| PUT | 空路径 | `server_url`（HTTP/HTTPS 根地址）、`computer_name`、`enabled`、`local_user_id`、`organization_id` |
| POST | `pair/` | 生成 8 位、10 分钟有效的单次配对码；旧的未完成配对会撤销 |
| POST | `pending/` | 查询申请绑定的 `account`、`account_id`、`confirmed` |
| POST | `confirm/` | `{ "account_id": 服务器账号ID }`，电脑管理员确认该账号 |
| POST | `reconnect/` | 更新配置修订号，连接进程重新建立连接 |
| POST | `unbind/` | 撤销服务器凭证、清除本机绑定并关闭连接 |
| GET | `context/` | 仅限本机连接凭证；返回已授权组织 ID 和电脑名称 |

配置默认关闭。关闭只断开通道，保留绑定；换服务器、授权用户或组织前必须解绑。配置持久化于 `LocalRemoteConfig`，凭证用本机 `SECRET_KEY` 派生的 Fernet 密钥加密。备份或迁移本地数据库时须一并保留原 `SECRET_KEY`。凭证不会进入浏览器存储。

连接进程每秒检查修订号、启用状态、本机后端健康及授权用户成员关系；启停和修改无需重启 Django。退出浏览器不影响连接。解绑遇到网络故障时先关闭本机访问，并保留凭证以供恢复网络后重试撤销。

## 服务器设备接口

| 方法 | `/api/v1/remote/` 下的路径 | 认证及说明 |
| --- | --- | --- |
| POST | `pairings/` | 无账号认证、10 次/小时/IP；电脑提交 `{code, token, name}`，返回 `{id, expires_in:600}` |
| POST | `claim/` | 已登录账号、10 次/分钟；`{code}` 单次认领，必须再经电脑确认 |
| GET | `connector/<device_id>/` | `Authorization: Device <token>`；电脑查询申请账号 |
| POST | `connector/<device_id>/` | 设备凭证；`{action:"confirm", account_id}` 或 `{action:"revoke"}` |
| GET | `devices/` | 已登录账号；仅返回自己绑定的设备、确认状态、在线状态和最后心跳时间 |
| DELETE | `devices/<device_id>/` | 设备所属账号撤销绑定 |
| GET/POST | `devices/<device_id>/proxy/<API相对路径>` | 所属账号、设备在线、白名单校验；直接返回本机状态码和分块正文 |

服务器只保存配对码与设备凭证的 SHA-256 摘要。配对过期、撤销或未确认的设备不能建立连接。每台电脑只归属于一个账号；同一账号可以绑定多台电脑。电脑本地凭证与服务器设备凭证分离。

请求示例：

```text
GET /api/v1/remote/devices/<device_id>/proxy/conversations/
POST /api/v1/remote/devices/<device_id>/proxy/conversations/
Idempotency-Key: conversation-<随机值>
Content-Type: application/json

{"title":"远程工作"}

GET /api/v1/remote/devices/<device_id>/proxy/organizations/<本机组织ID>/runs/<run_id>/stream?after=37
```

白名单的唯一实现为 `backend/apps/remote_access/protocol.py`，服务器、连接进程和本机认证均检查它：

- 对话列表、详情、composer options、新建对话和发送消息。
- 智能体、应用列表及数字 ID 读取端点。
- Run 详情、子 Run、事件分页、快照、SSE，以及 answer、grant_permission、deny_permission、cancel 命令。
- 禁止上传、附件下载、workspace 文件读取、系统目录操作、任意 URL、组织查询覆盖及其他命令。

本机认证还检查 loopback 来源、启用状态、授权用户/组织、活动成员关系和许可证，然后复用原 API 的业务权限。服务器认证失败仍返回 401；本机认证失败对手机返回 403，避免错误退出服务器账号。

新建对话和发消息要求 `Idempotency-Key`，Run 命令沿用正文 `idempotency_key`。新建对话使用本机现有 `IdempotencyRecord`，原子保存创建结果；同键同参数返回原对话，同键不同参数返回 409，记录保留策略与执行系统一致（24 小时到期）。手机暂时丢失响应时自动使用原键有限重试，仍失败后在当前连接上下文中保留原键供手动重试。服务器不暂存离线指令。

## WebSocket 与 Redis

电脑主动连接 `/ws/remote/connector/`，握手头为 `Authorization: Device <token>`、`X-Device-ID: <uuid>`。不接受浏览器 Origin 或 query string 凭证。

所有文本帧包含 `v:1`；请求及其响应还包含 `id`（服务器生成的 32 位随机请求标识）。

| 帧 type | 方向 | 内容 |
| --- | --- | --- |
| ready | 服务器 → 电脑 | 通道就绪 |
| hello | 电脑 → 服务器 | `name`，更新电脑显示名称 |
| request | 服务器 → 电脑 | `method`、`path`、`body`、`idempotency_key` |
| start | 电脑 → 服务器 | HTTP `status`、`content_type` |
| chunk | 电脑 → 服务器 | `body`，最多 32 KiB 原始字节的 Base64 |
| ack | 服务器 → 电脑 | 手机已消费上一个 chunk，可发送下一块 |
| end | 电脑 → 服务器 | 请求完成 |
| error | 双向内部转发 | 固定错误说明，不包含业务正文或原始异常 |
| cancel | 服务器 → 电脑 | 结束指定 HTTP 订阅；不会创建停止任务命令 |
| ping / pong | 电脑 → 服务器 / 返回 | 20 秒心跳，60 秒无响应离线 |

每个连接最多 32 个并行请求，每个请求最多 1 MiB 正文；每次仅允许一个未确认响应块。慢客户端会在超时后断开订阅，任务继续在本机执行。重连采用带抖动的退避，最多 30 秒；配置变化可提前结束等待。

使用 Redis 时通过 `SUBSCRIBE/PUBLISH` 转发；每条连接有独立 session，每个请求有独立响应通道。订阅确认后才发布请求。不会写 Redis key/list/stream，也不经过任务队列，因此跨 ASGI 进程可转发且离线不积压。

没有 Redis 时，生产环境可显式设置 `REDIS_ENABLED=False`、`REMOTE_RELAY_REDIS_URL=`（空值）、`REMOTE_RELAY_ALLOW_MEMORY=True`，使用单 ASGI 进程内存转发，保持 `DEBUG=False`。HTTP 和 WebSocket 必须进入同一进程，不能启动多个 worker 或服务器副本；该模式也使用进程内限流计数。进程重启后电脑会重新连接，进行中的请求需要重试，不保存离线指令。Redis URL 非空时优先使用 Redis，不会在 Redis 故障时自动降级。两种传输均未配置时，生产启动检查拒绝启用 relay。

HTTP 部署设置 `SECURE_SSL_REDIRECT=False` 和 `JWT_REFRESH_COOKIE_SECURE=False`；会话与 CSRF Cookie 默认跟随跳转设置，HSTS 同时关闭。默认配置仍使用 HTTPS。完整启动方式见 [无 Redis 的 HTTP 服务器部署](DEPLOYMENT.md#standalone-http-relay-without-redis)。

正文不写服务器数据库、请求日志或异常采集；远程路径排除 OpenTelemetry 和 Sentry 事件采集。反向代理及外部 APM 也应保持不采集请求/响应正文、Authorization 头和 WebSocket 帧。

## 本地双后端联调（无需 Redis）

在仓库根目录运行：

```bash
backend/.venv/bin/python backend/scripts/test_remote_local.py
```

Windows 使用 `backend\venv\Scripts\python.exe backend\scripts\test_remote_local.py`。

脚本启动三个独立进程：

- `http://127.0.0.1:18080`：模拟服务器，单 ASGI 进程使用内存转发。
- `http://127.0.0.1:18081`：模拟被控电脑，提供本机业务 API。
- `run_remote_connector`：主动连接服务器，并将请求转给被控电脑后端。

两端分别创建临时 SQLite 数据库、随机账号密码、独立密钥和工作目录，不使用日常开发数据库。脚本通过真实 HTTP/WebSocket 检查配对、电脑确认、历史读取、创建对话、幂等重试、路径限制、SSE、离线拒绝及重连，并确认服务器没有保存业务记录。SSE 使用预置 Run 事件，不调用模型，也不验证模型执行流程。

默认检查完成后停止三个测试进程，保留临时目录中的数据库和日志。需要继续手动调用 API 时运行：

```bash
backend/.venv/bin/python backend/scripts/test_remote_local.py --keep-running
```

账号密码和设备 ID 写入输出目录的 `access.json`；用对应端的 `/api/v1/auth/login/` 获取访问令牌。按 Ctrl+C 停止测试进程。端口冲突时通过 `--server-port 19080 --client-port 19081` 指定其他端口。每次运行都创建全新的测试环境，并且仅监听 loopback。

加上 `--production-server` 可使用生产配置启动服务器端，以 `DEBUG=False`、HTTP 和内存转发完成同样的联调，还会验证 HTTP 登录 Cookie 和刷新令牌接口：

```bash
backend/.venv/bin/python backend/scripts/test_remote_local.py --production-server
```

## 前端连接上下文

每台电脑创建独立的 API 客户端与 conversation store；不修改全局组织、服务器客户端或服务器对话 store。电脑对话不写浏览器持久化 store。Run 流、事件补页和历史压缩快照始终经过同一设备代理，快照中的本机绝对地址会转换成对应设备的快照端点。

空闲对话每 5 秒检查一次状态，发现活动 Run 后复用事件投影订阅；离开页面只撤销订阅。设备离线时禁用发送并保留当前页面草稿。导航为“对话 → 对话列表 → 电脑列表”。附件和 Markdown 内嵌文件只显示名称或说明，不在手机直接加载电脑文件。

机器可读的 WebSocket 帧契约为 `contracts/remote-connector-v1.json`。对话列表传入 `?page=1` 时返回 `count/next/previous/results`，不传 `page` 保留原有数组响应。应用和智能体列表使用原有分页；手机只读取分页编号并通过当前电脑客户端加载下一页，不直接请求本机绝对链接。远程目录读取额外限制为授权组织及全局资源，即使授权用户是平台管理员也不会列出其他组织的资源。
