# 社区聊天

本站登录用户共享一个公共大厅，可以跨组织私聊、创建群聊和发送图片/文件。
应用中心入口和 `/community-chat` 直达入口访问同一空间。与 AI 对话的会话、消息及网盘文件相互独立。

## 使用规则

- 私聊无需好友审批；同一对用户始终复用同一私聊。
- 群主可邀请/移除成员、改名、转让群主和解散群聊；其他成员可以退出。
- 新成员能看全部历史。退群、被移除或解散后，旧附件链接也重新检查权限。
- 消息最多 10000 字、9 个附件，单文件与附件合计最多 100 MiB；空文件不支持。
- 本人消息两分钟内可以撤回，正文清空、附件不可访问，保留撤回占位。
- 文件选择、拖拽与粘贴图片均可使用。上传失败可重试；已成功上传的附件不重复传输。
- 页面内切换会话保留正在发送和失败的消息；刷新页面不保留本地未发送草稿。
- 历史长期保存在数据库中；首版不提供好友、搜索、引用、@、语音视频或端到端加密。

## 安装与部署

在仓库根目录执行（Windows）：

```powershell
backend\venv\Scripts\python.exe backend/manage.py migrate community_chat
backend\venv\Scripts\python.exe backend/manage.py sync_app_center --package community-chat
backend\venv\Scripts\python.exe backend/manage.py check
```

前端在 `frontend` 目录运行 `npm.cmd run build`，使用现有应用部署方式发布，重启后端以加载新增 Django 应用和 WebSocket 路由。

配置项：

| 配置 | 默认与要求 |
| --- | --- |
| `COMMUNITY_CHAT_ROOT` | `backend/community-chat-data`；持久化私有目录，不能置于 MEDIA_ROOT 或反向代理的静态目录中 |
| `COMMUNITY_CHAT_ALLOWED_ORIGINS` | 现有 CORS 来源、非通配 ALLOWED_HOSTS、本地 3030；生产建议显式填写逗号分隔的完整网页 origin，手机 LAN 访问需加入实际来源 |
| `COMMUNITY_CHAT_WORKERS` | 使用 WEB_CONCURRENCY，默认 1；必须与实际 ASGI 工作进程数一致 |
| `REDIS_ENABLED` | 多进程必须启用；沿用现有 REDIS_HOST / PORT / PASSWORD 配置 |

`manage.py check` 拒绝多进程使用内存 channel layer、私有目录置于公开媒体目录、WebSocket 来源使用 `*`。
单进程可使用默认内存 channel layer。SQLite 开发配置可运行；多进程生产部署沿用项目的 PostgreSQL + Redis 配置。

反向代理需转发 `/api/v1/community-chat/` 和 `/ws/community-chat/`，后者须支持 WebSocket Upgrade。Vite 及现有 Caddy `/ws/*` 代理已覆盖路由。
上传限制按 **101 MiB 请求体** 配置以容纳 multipart 头，服务端仍校验文件本身为 100 MiB。Nginx 对上传 location 设置 `client_max_body_size 101m`、适合网络环境的请求读取超时；不要把上传限制放大为全站无限制。
文件和数据库都需纳入备份，临时上传目录也需要足够磁盘空间。日志中不要记录 WebSocket 帧、请求正文或文件下载 URL 的 token 参数。

## 清理与排障

通过部署环境现有定时任务每天执行：

```powershell
backend\venv\Scripts\python.exe backend/manage.py cleanup_community_chat
```

该命令删除超过 24 小时未绑定消息的上传、撤回消息的附件、遗留的无数据库记录文件及过期连接票据；不删除正常消息附件。
撤回后的文件即使尚未物理清理也已不可读取。群解散的数据保留，但应用接口不再允许访问。

连接状态显示在会话列表。连接失败时每 5 秒通过 HTTP 补齐数据，连接正常时每 30 秒校准一次，重新连接及页面恢复可见时立即同步。
消息带有会话版本，撤回与新消息通过 `after_revision` 一起补齐，重复或乱序消息按 ID/版本合并。
服务端记录连接拒绝、消息分发失败、上传失败及发送耗时，不记录消息正文。可结合平台现有请求状态码监控 403、429、5xx 和磁盘容量。

## 接口

所有接口位于 `/api/v1/community-chat/`，除签名文件读取外均使用平台现有登录认证。

| 路径 | 方法与用途 |
| --- | --- |
| `users/?q=...` | GET 当前用户与最多 50 个匹配用户的公开资料 |
| `rooms/` | GET 会话及未读；POST 创建私聊或群聊 |
| `rooms/{id}/` | GET 群详情；PATCH rename/add/remove/leave/transfer/close |
| `rooms/{id}/messages/` | GET 最新 50 条、before 历史分页或 after_revision 增量；POST 幂等发送 |
| `rooms/{id}/messages/{message_id}/withdraw/` | POST 撤回 |
| `rooms/{id}/read/` | POST 单调递增的已读消息 ID |
| `rooms/{id}/uploads/` | POST 单文件 multipart 上传，返回待绑定附件 |
| `attachments/{id}/access/` | POST 获取 120 秒签名的预览或下载 URL |
| `content/?token=...` | GET 文件流，重新检查用户状态、成员权限及撤回状态 |
| `ticket/` | POST 获取 30 秒、单次使用的 WebSocket 票据 |

WebSocket 路由 `/ws/community-chat/`：连接后 5 秒内发送 `{ "ticket": "…" }`，收到 `ready` 后开始接收 `changed` 通知及 `ping` 心跳。通知只含会话 ID、版本和事件 ID，正文经 HTTP 权限检查后读取。票据不放在连接 URL 中。
发送体为 `{text, attachments: UUID[], request_key: string}`；请求键最多 160 字符，同一作者/会话/请求键唯一。同键不同内容返回 409，同键重试返回原消息。

## 验证

在仓库根目录执行后端测试：

```powershell
backend\venv\Scripts\python.exe -m pytest app_center/community_chat/backend/tests -q
backend\venv\Scripts\python.exe -m pytest app_center/community_chat/backend/tests/test_realtime.py::test_100_connections_fanout -q -s
```

前端在 `frontend` 执行：

```powershell
npx.cmd vitest run app_center/community_chat/frontend frontend/src/layouts/__tests__/communityChatLayout.test.ts
npx.cmd eslint "../app_center/community_chat/frontend/**/*.{ts,tsx}" --config .eslintrc.cjs --resolve-plugins-relative-to . --max-warnings 0
npm.cmd run build
```

2026-10-16 初次检查环境：Windows、Python 3.13.7、Django 5.2.17、Node 24.13.0、SQLite 测试数据库及内存 channel layer。
100 个进程内 ASGI 连接全部收到广播，实测中位数 56.3ms、P95 98.3ms、最大 103.4ms。该测试覆盖连接及通知分发，不包含真实网络、浏览器或 100 位用户同时上传大文件的压测。
前端验证包含中文输入法、网络失败重试、上传失败、UUID 兼容模拟与 CSS 滚动契约。没有执行浏览器视觉验收或手机真机触摸验证。
