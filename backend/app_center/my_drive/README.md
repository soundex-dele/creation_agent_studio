# 我的网盘

私人文件管理应用。按组织、账号和应用隔离文件，组织管理员也不能浏览其他成员的网盘。
包含文件夹、搜索/类型筛选/分页、重命名、移动、批量删除、回收站、大文件续传及原生媒体预览。

## 部署

Windows 仓库根目录使用项目虚拟环境执行：

```powershell
backend\venv\Scripts\python.exe backend/manage.py validate_app_center
backend\venv\Scripts\python.exe backend/manage.py migrate --noinput
backend\venv\Scripts\python.exe backend/manage.py sync_app_center --package my-drive
backend\venv\Scripts\python.exe backend/manage.py maintain_my_drive --loop
```

最后一条是持续运行的维护进程；也可以由系统调度器每分钟运行一次不带 `--loop` 的命令。
Docker Compose 已包含该进程，重建 web、frontend 和维护服务后生效。

| 设置 | 默认值 | 说明 |
| --- | --- | --- |
| `MY_DRIVE_ROOT` | `backend/my-drive-data`，Docker `/data/my-drive` | 私有文件目录，不要放在公开媒体/静态资源目录 |
| `MY_DRIVE_MAX_FILE_BYTES` | 21474836480 | 单文件 20 GiB |
| `MY_DRIVE_QUOTA_BYTES` | 107374182400 | 每组织每用户 100 GiB，包含回收站和上传预留 |
| `MY_DRIVE_UPLOAD_TTL_DAYS` | 7 | 未完成上传的无活动保留天数 |
| `MY_DRIVE_ACCESS_TTL_SECONDS` | 3600 | 原生媒体临时访问凭据有效期；页面自动刷新 |
| `MY_DRIVE_X_ACCEL_REDIRECT` | false，Docker true | Nginx 内部文件发送 |

Nginx `/_protected_drive/` 必须保持 `internal`，其 alias 必须与 web 的网盘根目录一致。
备份必须同时包含数据库及整个网盘根目录（包括 `.part`），建议暂停写入后制作一致性快照。
恢复后保持目录权限可读写。生产使用 PostgreSQL 行锁；SQLite 只用于本机开发和常规测试。
维护失败会记录日志并保留待清理记录和容量，下次运行继续重试。监控维护进程、磁盘空间和 507 错误。

## 使用与限制

- 从应用中心打开“我的网盘”。上传使用 8 MiB 分片，最多同时传输三个文件。
- 校验依赖 Web Crypto，非 localhost 的部署须使用 HTTPS。暂停、断网或刷新不丢失已确认分片。
- 刷新后在传输列表选择原文件：名称、大小、修改时间及已上传部分 SHA-256 必须匹配。校验只读取分片大小的内存。
- 离开页面会暂停传输；回来后选择原文件继续。服务器进度是唯一可信进度，不在浏览器持久化文件内容。
- 回收站不自动清空。永久删除/取消上传先标记，维护进程清理磁盘成功后才释放空间，通常一分钟内完成。
- 预览支持常见位图、浏览器能解码的音视频及前 1 MiB 纯文本；不转码，不执行 HTML/SVG，不提供 Office/PDF 在线阅读。
- 原生下载和媒体使用短期签名链接，持有链接者在有效期内可访问，勿转发。每次读取仍检查原所有者、组织成员资格、应用权限和文件状态；移入回收站后立即拒绝新请求。
- 支持单区间 Range 及 HEAD；多区间请求返回 416。文件夹下载打包、目录整体上传、外链分享、AI 联动不在首版范围内。

## API

路径前缀：`/api/v1/organizations/{organization_id}/applications/{application_id}/my-drive`。
单租户模式也提供不含 `organizations/{organization_id}` 的对应路径。

- `GET /`：`scope=files|trash`、`parent`、`search`（全盘）、`type`、`sort`、`page`；返回分页条目、目录面包屑和容量。
- `POST /`：创建目录；`POST /actions`：`action`、`ids` 及可选 `name`/`parent`。
- `GET/POST /uploads`：分页任务列表/创建会话。
- `GET/DELETE /uploads/{id}`：确认进度和分片摘要/取消。
- `PUT /uploads/{id}/chunk`：原始二进制，携带 `X-Chunk-Offset`、`X-Chunk-SHA256`。
- `POST /uploads/{id}/complete`：幂等完成，返回文件 ID。
- `POST /entries/{id}/access`：`mode=preview|download`，返回短期 token。
- `GET/HEAD /content?token=…`：验证后流式返回文件，不暴露磁盘路径。

## 验证

后端：`backend\venv\Scripts\python.exe -m pytest backend/app_center/my_drive/backend/tests`。
前端在 `frontend` 执行相关 Vitest、`npm run lint`、`npm run build`。
大文件测试使用稀疏文件验证超过 2 GiB 的偏移及有界流式读取，避免向磁盘实际写入数 GiB 测试数据。
