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

设备控制接口在凭证失效、设备已撤销或记录不存在时返回 `401`，并携带 `WWW-Authenticate: Device`。因此先在服务器删除设备、再在电脑解绑，或重试已经成功撤销的解绑请求，都能清理本地绑定。其他 `403`、服务器故障和网络错误仍会保留本地凭证供重试，同时关闭远程访问。

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
- 工作空间列表 `GET /projects/`、文件夹列表 `GET /apps/runtime-files/list/?path=...`；创建对话可提交 `project_id` 或 `working_directory`。
- Run 详情、子 Run、事件分页、快照、SSE，以及 answer、grant_permission、deny_permission、cancel 命令。
- 文件传输仅开放文末列出的独立接口；禁止复用附件和工作空间文件读写接口，禁止任意 URL、组织查询覆盖及其他命令。文件夹列表只返回目录名和路径，不读取文件内容。

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
| revoked | 服务器 → 电脑 | 绑定或账号被撤销，清理终端、未完成上传及下载任务，再关闭连接 |

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

新建普通对话可选择该电脑上的已有工作空间或系统目录，发送首条消息后固定目录；应用对话沿用应用工作目录。工作空间列表和创建校验均限定为本机授权用户及组织，系统目录继续遵守 `APPLICATION_RUNTIME_ALLOW_ALL_PATHS` 和 `APPLICATION_RUNTIME_ALLOWED_ROOTS`。电脑历史包含绑定工作空间的对话。

对话权限与设置页共用浏览器持久化偏好，修改后用于所有会话的后续消息。重新进入电脑时保留已保存的选择；完全控制需等待该电脑的审批策略校验成功，失败可重试，重连后自动重新校验。组织要求审批时使用默认权限，不覆盖已保存的偏好。

空闲对话每 5 秒检查一次状态，发现活动 Run 后复用事件投影订阅；离开页面只撤销订阅。设备离线时禁用发送并保留当前页面草稿。导航为“对话 → 对话列表 → 电脑列表”。附件和 Markdown 内嵌文件只显示名称或说明，不在手机直接加载电脑文件。

机器可读的 WebSocket 帧契约为 `contracts/remote-connector-v1.json`。对话列表传入 `?page=1` 时返回 `count/next/previous/results`，不传 `page` 保留原有数组响应。应用和智能体列表使用原有分页；手机只读取分页编号并通过当前电脑客户端加载下一页，不直接请求本机绝对链接。远程目录读取额外限制为授权组织及全局资源，即使授权用户是平台管理员也不会列出其他组织的资源。

## 远程终端

本机配置增加 `terminal_enabled`（默认 `false`）。只有本机管理员可修改；旧客户端 PUT 省略此字段时保留原值。`context/` 返回 `terminal: {supported, enabled, shell, platform, max_sessions}`。远程用户不能通过代理修改开关。终端使用运行本机服务的操作系统账号，不模拟 Django 用户的操作系统身份，也不自动提权。

浏览器通过 `/api/v1/remote/devices/{device_id}/proxy/remote-access/terminals/` 访问。下表的路径相对该前缀；它们是连接器分派的接口，不在本机 Django 请求中启动 PTY。

| 方法与路径 | 请求 | 返回 |
| --- | --- | --- |
| GET 根路径 | 无 | `{sessions: [{id, shell, created_at, exited, exit_code}]}` |
| POST 根路径 | `{cols, rows}` | 201，单个会话信息 |
| POST `{id}/input/` | `{client_id, sequence, data}` | `{sequence}` |
| POST `{id}/resize/` | `{cols, rows}` | `{resized: true}` |
| POST `{id}/close/` | `{}` | `{closed: true}`，重复关闭成功 |
| GET `{id}/stream/?after=0` | 输出序号 | SSE 输出与退出状态 |

所有 POST 必须携带 `Idempotency-Key`。会话 ID 和输入客户端 ID 为 32 位小写十六进制。尺寸范围为 2–500，单批输入不超过 16 KiB UTF-8。新建请求相同 key/参数返回原会话，更改参数返回 409，已关闭的创建请求返回 410，不能复活已关闭会话。输入按客户端从 1 递增；同序号、同内容重试只确认，不再次写入；冲突或跳号返回 409。不同批次即使内容相同也正常执行。输入失败结果不明时前端暂停输入，要求检查执行结果后重新连接。

SSE 的 `data` 为 JSON：`output` 携带 `sequence/data`，`truncated` 携带最近保留范围之前的 `sequence`，`ready` 表示回放完成可开始输入，`exit` 携带 `exit_code`。每 15 秒发送 SSE 注释心跳；输出继续使用现有 chunk/ack 背压。前端只在 `ready` 后发送输入，避免回放旧终端查询序列时生成新输入。

每电脑最多 8 个运行会话，另保留最多 8 个已退出会话；每会话保留最近 1 MiB 原始输出。慢订阅者不会阻塞 PTY 读取，超出保留范围时明确报告截断。会话不写数据库，不跨连接器重启保留。每会话最多 128 个输入客户端，连接器单次授权生命周期内最多记录 4096 个创建幂等键；达到上限返回 409。

关闭页面只取消输出订阅。网络掉线、请求取消和配置中的“重新连接”保留终端；关闭终端开关、远程访问、授权失效或本机 API 停止时，独立监测任务清理会话。服务器撤销绑定通过 `revoked` 或后续认证拒绝通知电脑；断网时不能立即获知服务器侧撤销。多页面输入由会话锁串行处理，尺寸采用最近一次有效调整。

运行 `backend\venv\Scripts\python.exe backend\scripts\test_remote_local.py --terminal` 可在临时数据库与真实双后端环境中验证终端启用、创建/输入幂等、PTY 输出、缩放、订阅退出、通道重连和关闭权限。该脚本不会操作日常开发数据库。

## 文件传输（v1 帧兼容扩展）

本机 `PUT /api/v1/remote-access/` 接受独立字段 `file_transfer_enabled`，默认关闭；仅本机管理员可以设置，旧客户端省略时保持原值。`context/` 增加 `files: {supported: true, enabled: boolean, max_file_size: 2147483648, chunk_size: 262144}`，缺少此能力字段的电脑应提示升级。文件操作不依赖终端开关，仍检查绑定账号、本地用户、组织成员和许可证；使用运行本机服务的操作系统账号读写，不会模拟或提升操作系统身份。

电脑工作区路径为 `/apps/my-computer/:deviceId/files`。下面路径相对 `/api/v1/remote/devices/{device_id}/proxy/remote-access/files/`。全部 POST 使用 JSON，必须提供显式 `Idempotency-Key`（1–160 字符）；传输和下载流 ID 为 32 位小写十六进制。服务器、连接器和本机认证共享具体路径及字段白名单，不开放原有运行目录接口。

| 方法与路径 | 请求 | 返回 |
| --- | --- | --- |
| GET `roots/` | 无 | `{roots: [{name, path}], home}`，OS 磁盘根与账号主目录 |
| POST `list/` | `{path, cursor}`，首页 cursor 为空字符串 | `{path, parent, entries, next_cursor}`，每页最多 100 项，实际路径、上级目录及不透明游标 |
| POST `uploads/` | `{path, name, size}`，path 是目标目录 | 传输对象；同 key 同参数返回原对象，冲突 409 |
| POST `uploads/{id}/chunk/` | `{offset, data, sha256}`，Base64 数据与原始字节 SHA-256 小写十六进制 | 传输对象，offset 是电脑已接收的字节数 |
| POST `uploads/{id}/complete/` | `{}` | 校验大小、同步磁盘并提交后的传输对象，包含实际文件名 |
| POST `downloads/` | `{path}`，普通文件绝对路径 | 下载任务对象；浏览器应使用下述专用创建入口取得 Cookie |
| GET `transfers/{id}/` | 无 | 传输对象 |
| GET `transfers/` | 无 | `{transfers: [...]}`，最多 4 个未完成任务，刷新网页后可找回取消入口 |
| POST `transfers/{id}/cancel/` | `{}` | 取消后的对象；清理未完成上传，已完成上传保留 |

目录项为 `{name, path, directory, size, modified_at}`；目录 size 为 null，修改时间是 Unix 秒。目录链接解析后的实际位置返回在列表顶层 path。仅列出目录与普通文件，隐藏本模块临时上传。拒绝设备、命名管道、Windows 设备路径、保留文件名及备用数据流。

传输对象为 `{id, direction, name, size, offset, state, path, etag, detail}`。direction 为 upload/download；state 为 ready/transferring/completed/cancelled/failed。下载 offset 为已发送给浏览器的去重字节数，不表示浏览器已保存到磁盘。源文件签名变化会使下载失败。每台电脑最多 2 个未完成上传和 2 个未完成下载，另外最多 2 个活动二进制下载流；超限返回 429，网页在本地排队。

上传数据块固定为 256 KiB，最后一块可以更小；空文件直接 complete。单文件最大 2 GiB。每块检查偏移、边界和 SHA-256；同偏移同内容重发只确认，不同内容或跳跃偏移返回 409，SHA 不匹配返回 400。重试使用原操作键，手动恢复先查询电脑确认偏移。目标目录内临时文件以独占方式创建；完成时使用不覆盖已有路径的提交操作，碰到同名自动尝试 `文件 (1).扩展名`。POSIX 使用硬链接提交，目标文件系统不支持硬链接时报告失败并保留原文件。中继保持原 1 MiB 正文限制；前端逐块读取 File，不持有整文件内存副本。

### 浏览器原生下载

已登录用户 `POST /api/v1/remote/devices/{device_id}/downloads/`，正文 `{path}`，携带 `Idempotency-Key`。返回下载任务及 `download_url`，并设置 `remote_file_download` 签名 Cookie：HttpOnly、SameSite=Strict、有效期 1 小时，Path 仅为该任务的 content 地址，Secure 跟随部署的 `JWT_REFRESH_COOKIE_SECURE`。下载链接没有 JWT、本机凭证或长期访问令牌；要求网页与 API 同源部署。

浏览器直接 GET/HEAD `/api/v1/remote/devices/{device_id}/downloads/{transfer_id}/content/`，通过 Cookie 鉴权，且每块重新检查设备归属及本机授权/文件访问权限。返回 `application/octet-stream`、安全的 `Content-Disposition`、`Content-Length`、`ETag`、`Accept-Ranges: bytes`。支持单个闭合、开放或尾部 Range；206 返回 Content-Range，非法或多区间范围返回 416。If-Range 与任务 ETag 不符时按完整请求处理；源文件与任务快照不一致则失败，不能拼接不同版本。响应禁缓存、禁代理缓冲，不将整文件读取为 Blob。

中继与电脑间仍使用有界 JSON/Base64 RPC，内部接口为：POST `downloads/{id}/open/` 与 `release/`，正文 `{stream_id}`；GET `downloads/{id}/read/?offset=0&length=262144&stream_id=…`，返回 `{data, offset, etag}`；POST `downloads/{id}/progress/`，正文 `{offset, length, stream_id}`，在 ASGI 消费当前二进制块之后确认进度。read 最多读取 256 KiB，响应继续以 32 KiB chunk/ack 转发。活动流租约 90 秒过期，读块/进度请求刷新或重新争取名额，防止崩溃的中继永久占用下载名额。

瞬时断线从当前未确认操作重试，单次最长等待 60 秒；超时结束响应，后续续传由浏览器 Range 请求完成，具体支持取决于浏览器。网页取消会撤销电脑任务和活动流，浏览器保存过程仍由浏览器管理。离开文件页不会撤销网页队列，刷新/关闭网页不保证上传恢复；退出账号会清空该账号在网页内的任务和文件引用。

任务、幂等记录与下载流只在单实例连接器内存中保存（最多 1024 条任务记录），不跨连接器重启恢复。未完成上传闲置 24 小时后清理；状态轮询不延长闲置期限。启动及定时扫描 `REMOTE_CONNECTOR_LOCK_PATH` 同目录下的 `remote-file-transfers` 清理日志，按文件标识核对并移除模块遗留的过期临时文件；日志不包含文件正文。关闭文件权限、远程访问、授权失效、确认解绑或停止连接器时清理未完成上传，保留已完成文件。服务器解绑在通知抵达或明确认证失败后清理；本机授权监测独立于中继重连。

双后端验证（Windows，项目虚拟环境）：

```powershell
backend\venv\Scripts\python.exe backend\scripts\test_remote_local.py --terminal --files --production-server
backend\venv\Scripts\python.exe backend\scripts\test_remote_local.py --terminal --files --production-server --redis-url redis://127.0.0.1:16389/0
```

第二条使用自行准备的临时 Redis。pytest 可设置 `REMOTE_TEST_REDIS_BINARY` 自动创建测试实例，或 `REMOTE_TEST_REDIS_URL` 指向专用空 Redis 实例；测试检查 Pub/Sub 没有持久化任何数据键。
