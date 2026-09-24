# AI 绘图

独立的 Codex 绘图工作台，支持每次生成一张图片、单张参考图文字编辑、
历史作品继续修改、原图预览和下载。每次修改创建新的 Run，不覆盖原图。

## 执行主机要求

- 使用项目虚拟环境、已安装的 Codex CLI 和 `CODEX_TRANSPORT=app-server`。
- Codex 当前会话必须实际提供内置图像生成工具。启用 `image_generation`
  功能开关不代表当前登录方式、模型或账号一定具有生图能力。
- 沿用 `CODEX_BINARY`、`CODEX_MODEL` 和执行主机的 Codex 登录配置。
  未设置 `CODEX_BINARY` 时，项目可能优先选择桌面版随附的二进制，
  不一定是 PATH 中的 `codex`。应对**项目实际使用的二进制及执行账号**检查登录。
- 不配置 `IMAGE_API_KEY`，不调用 Images API，不自动切换其他图像生成服务。
- 首版要求 `imageGeneration` 完成事件包含 `savedPath`；仅有文字回复按失败处理。

Windows 仓库根目录安装：

```powershell
backend\venv\Scripts\python.exe backend\manage.py validate_app_center
backend\venv\Scripts\python.exe backend\manage.py migrate ai_drawing --noinput
backend\venv\Scripts\python.exe backend\manage.py sync_app_center --package ai-drawing
```

重新加载 Web 服务和已有执行协调器，使其发现新的应用及执行器。
没有协调器时，从仓库根目录启动：

```powershell
backend\venv\Scripts\python.exe backend\manage.py run_execution_coordinator --worker-pool all
```

不要在同一个 SQLite 数据库上重复启动协调器。Run 排队后由 `media` 池执行。
默认单次生图超时 600 秒，可通过应用部署的 `timeout_seconds` 配置调整。
不自动重试，失败后由用户主动发起新任务。

## 接口和存储

应用前缀为租户 API 根路径下的 `/applications/{application_id}/ai-drawing`：

| 方法与路径 | 用途 |
| --- | --- |
| `POST /references` | multipart `file` 上传单张静态 PNG/JPEG/WebP，最多 20 MB |
| `GET /references/{id}/content` | 经过登录、组织、应用和所有者校验的参考图读取 |
| `GET /generations?page=1` | 每页 20 条当前用户的绘图记录 |
| `POST /generations` | 创建任务，必须提供 `Idempotency-Key` |
| `GET /generations/{run_id}` | Run 状态及已经归档的 drawing artifacts |

生成输入：`prompt`（1–8000 字符）、`orientation`（auto/square/landscape/portrait），
可选 `reference_id` 或 `source_artifact_id`，两者不能同时指定。
方向仅作为生成偏好，页面展示实际输出尺寸。
执行器再次校验参考图权限，避免通过通用 Run 接口绕过检查。

进度、取消与图片访问复用现有 Run API；`progress.updated` 的阶段为
`generating` / `saving`，图片通过 `artifact.created` 到达。
所有者校验同时应用于通用任务历史、详情、事件、取消与文件访问链接签发。
图片访问链接复用平台短期签名 URL，在有效期内具有持有即访问的语义。

上传图片存于平台 artifact storage，`DrawingReference` 保存私有元数据。
图片生成在每次任务的独立工作目录中执行；完成事件返回的图片只能来自该目录
或执行账号的 `$CODEX_HOME/generated_images`。校验真实图片内容后，由协调器
持久保存成 RunArtifact，随后才提交任务成功状态。目录不会扫描，模型文本不会
被当作图片路径解析，Base64 和工具原始本机路径不会发布到绘图前端。
取消前已归档的图片继续可用。引用的原作品被删除时，后续修改应重新选择参考图。
工作目录清理会短暂重试；Windows 进程仍占用目录时，将保留该任务目录并记录
服务端警告，不影响生成结果，也不覆盖原始错误。确认占用进程退出后可清理残留目录。

## 验证

```powershell
cd backend
.\venv\Scripts\python.exe -m pytest app_center/ai_drawing/backend/tests core/agent_engine/tests/test_adapters.py -q
cd ..\frontend
npx vitest run src/pages/Apps/__tests__/aiDrawing.test.ts src/lib/__tests__/applicationCatalog.test.ts
npm run build
```

真实验收：从应用中心打开 AI 绘图，生成一张图片；下载并刷新页面确认历史和图片
仍可读取；点击“继续修改”改变背景，确认得到新作品且原图仍在。
如果返回“当前会话可能未提供内置生图工具”，请先恢复执行主机的生图能力，
再重复文生图和编辑验收。模拟测试通过不能代替真实出图验证。
