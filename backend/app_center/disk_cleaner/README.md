# 磁盘清理大师

面向平台管理员的 Windows 后端主机磁盘分析与清理工具。从应用中心打开，手机浏览器操作的也是后端主机，不是手机或访问者自己的电脑。

## 安装与运行

在仓库根目录执行，使用项目虚拟环境：

```powershell
backend\venv\Scripts\python.exe backend/manage.py validate_app_center
backend\venv\Scripts\python.exe backend/manage.py migrate --noinput
backend\venv\Scripts\python.exe backend/manage.py sync_app_center --package disk-cleaner
backend\venv\Scripts\python.exe backend/manage.py run_disk_cleaner_worker
```

worker 必须使用与 Web 后端相同的 Windows 主机、运行账号、设置和数据库。桌面启动器自动启动并关闭该进程，PyInstaller 已包含对应模块。命令的 `--once` 参数最多处理一个排队任务，可用于诊断。非 Windows 环境显示暂不支持；不提供 Docker 宿主机挂载或跨机清理。

Windows MachineGuid 绑定任务主机；ProgramData/AgentStudio/locks 下的操作系统文件锁保证同机只有一个清理 worker。运行账号需有创建/访问此锁文件的权限。服务无心跳超过 30 秒时页面显示未连接；新任务保持排队，不会由其他主机处理。worker 退出后重新启动，旧运行任务变为中断，删除结果未知的文件不会自动重试。

SQLite 心跳使用直接更新；清理提交在读取确认信息前取得写入锁。数据库暂时繁忙时 API 返回可重试错误，worker 会重连并将中断任务标记为已停止，不重新执行文件删除。

## 使用

1. 查看主机和固定磁盘容量，选择空间分析、大文件清理或临时缓存。
2. 整盘扫描只分析；清理大文件必须明确选择非盘符根目录，默认门槛 100 MiB。
3. 缓存只扫描后端运行账号的临时目录、Windows/Temp 中超过 7 天未修改的普通文件。
4. 扫描结束后逐项选择，最多 1000 项。预览显示完整分页清单、目标主机、目录、数量与大小。
5. 再次确认才会永久删除，不进入回收站。预览凭据 10 分钟有效，排队至过期也不会执行。
6. 结果保留已删除、已跳过、失败和未知状态及原因。停止操作不撤销已经删除的文件。

扫描以文件元数据为依据，不读取内容；单次最多遍历 500000 条目，达到限制会显式说明结果不完整。分页每页 50 条，目录浏览单层最多检查 10000 项并标记截断；超大目录可直接输入完整路径。扫描遇到不可访问目录继续处理并记录跳过数。占用大小是可访问文件的逻辑大小，不能等同于磁盘物理占用；清理分别报告成功删除的逻辑大小及磁盘可用空间变化。

## 文件边界与权限

- 每个 API 检查平台管理员身份（`role=admin` 或 superuser）、当前组织及应用访问权。任务、结果、预览按组织、应用、操作者、主机隔离；执行时再次校验权限。
- 不跟随 symlink、junction、reparse point；不删除多硬链接文件，不支持 UNC、设备路径、ADS、可移动盘。仅对预览选中的普通文件设置删除状态，不递归删除目录。
- 保护 Windows、Program Files、ProgramData、系统卷数据、应用代码、SQLite 数据库所在目录、网盘、媒体、知识资料、任务产物和工作区。Windows/Temp 只有专属缓存模式可例外；其他保护规则仍有效。
- 可用环境变量 `DISK_CLEANER_PROTECTED_ROOTS` 添加保护目录，格式为 JSON 数组，例如 `["D:/Important","E:/Database"]`。外部数据库数据目录应在此配置。
- 删除前持有祖先目录句柄阻止目录替换，校验文件最终路径、卷及文件 ID、大小、修改时间和链接数，再对同一文件句柄执行删除。文件变化、不可访问、被占用等情况显示原因并跳过或失败，不提升 Windows 权限。
- 逐项写入删除中状态后才操作文件；进程崩溃留下的未知结果不会被当作成功，也不会自动重试。重复提交同一确认凭据返回同一个清理任务。

## API

组织模式前缀 `/api/v1/organizations/{organization_id}/applications/{application_id}/disk-cleaner`；单租户模式提供对应的 `/api/v1/applications/{application_id}/disk-cleaner`。

- `GET /host`：主机、平台支持、worker 心跳、磁盘容量和临时目录。
- `GET /directories?path=…`：受保护边界内的单层目录浏览。
- `GET/POST /tasks`：最近任务分页/创建扫描，输入 `request_key`、`mode=analysis|large|cache`、`root`、可选 `minimum_bytes`。
- `GET/POST /tasks/{id}`：查询状态/请求取消。
- `GET /tasks/{id}/entries?page=…&sort=…&parent=…`：扫描或清理结果。分析模式支持按 `parent` 下钻。
- `POST /previews`：`scan_id`、`entry_ids`，返回签名 token、到期时间和汇总；`GET /previews/{id}?page=…` 查看清单。
- `POST /cleanups`：`request_key`、`token`，只接受已预览的条目，不接受任意删除路径。

## 验证

```powershell
backend\venv\Scripts\python.exe -m pytest backend/app_center/disk_cleaner/backend/tests
```

前端目录执行对应的 `diskCleaner.test.tsx`、`diskCleanerLayout.test.ts`、应用目录及移动滚动回归、ESLint 和 `npm run build`。文件操作测试只使用测试临时目录；Windows 测试包括实际句柄删除、占用、junction、硬链接、文件变化、权限、分页、主机隔离、取消和中断。

手机 HTTP 兼容性使用模拟的缺失/抛错 Web Crypto 环境验证。CSS 检查与 jsdom 不能证明真实浏览器布局、触摸滚动或设备表现；遵循仓库要求，不使用 Codex 内置浏览器验证。
