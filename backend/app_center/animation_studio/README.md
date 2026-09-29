# 动画制作

独立 AI 动画工作台：填写文案 → HTML 预览 → 对话式文字修改 → 显式导出 MP4。
生成使用 Remotion Player 构建自包含 HTML，**不会自动渲染视频**。
导出固定引用一个已完成版本的源码归档；导出成功后工作台默认播放 MP4。
失败或取消保留原预览，修改创建新版本，原视频和源码不覆盖。

## 部署

需要 Node.js 20+、项目虚拟环境、可用的 Codex 登录、FFmpeg/ffprobe。
推荐 `CODEX_TRANSPORT=app-server`，沿用平台实际的 `CODEX_BINARY` / `CODEX_MODEL` 配置。
动画生成规范在 `authoring.md`，不依赖安装到个人目录的 Skill。

在仓库根目录执行：

```powershell
npm.cmd ci --prefix backend/app_center/animation_studio/engine
npm.cmd run browser --prefix backend/app_center/animation_studio/engine
backend\venv\Scripts\python.exe backend\manage.py validate_app_center
backend\venv\Scripts\python.exe backend\manage.py migrate animation_studio --noinput
backend\venv\Scripts\python.exe backend\manage.py sync_app_center --package animation-studio
```

重载 Web 服务和现有执行协调器，使用 `--worker-pool all` 或 `media`。
不要在同一个 SQLite 数据库上重复启动协调器，也不要中断其他运行中任务。
渲染器优先使用 `ANIMATION_BROWSER_EXECUTABLE`；Windows 下自动查找常见安装位置的
Chrome/Edge，否则使用 Remotion 下载的 Chrome Headless Shell。
运行预览构建也需要无头浏览器，以验证播放器、开头、中间和结尾帧。
Noto Sans SC 字体由锁定版本的 `@fontsource/noto-sans-sc` 提供（SIL OFL），按作品字符
选择字体子集后嵌入，预览不访问 Google Fonts 或其他外部资源。

## 接口

租户 API 前缀：`/applications/{application_id}/animation-studio`。

| 方法与路径 | 内容 |
| --- | --- |
| `POST /assets` | multipart `file` 上传图片或录音，返回私有素材 ID |
| `GET /generations?page=1` | 当前用户每页 20 个版本，包含对应导出任务 |
| `GET /generations/{run_id}` | 当前版本、产物和导出状态 |
| `POST /generations` | `prompt`、`aspect`、`duration`、`style`、`asset_ids`、可选 `source_run_id` |
| `POST /generations/{run_id}/exports` | 导出指定已完成版本；正文为空 |

生成和导出接口必须提供 `Idempotency-Key`。未知结果的网络重试沿用原键；已知失败后的
重做使用新键。生成和导出分别使用独立 Run；列表只返回生成版本。
进度、取消、事件和短期文件访问链接复用平台 Run API。签名文件链接在有效期内具有
持有即访问的语义；签发前验证组织、应用和所有者，通用 Run 接口同样执行所有者校验。

默认 16:9、1920×1080、30fps、30 秒、无声；也支持 9:16 和 1:1。
时长 5–120 秒。静态 PNG/JPEG/WebP 单个不超过 20 MB；纯音频 MP3/WAV/M4A 单个不超过
50 MB，校验实际容器和时长。每个版本最多 10 个素材、100 MB，总共一段录音。
有录音时按实际时长向上取整到帧，不截断音频；修改继承原素材，新录音替换原录音。

## 执行与产物

- 生成：AI 返回完整 TSX 和分镜 → AST 校验 → 固定工程构建 → 浏览器执行校验 → 归档。
- 导出：恢复版本归档 → 固定工程渲染 H.264 → 校验时长、尺寸、音轨和完整解码 → 归档。
- AI 构建错误最多修复两次。失败源码标记为 `animation-diagnostic-source`，不冒充可导出版本。
- 生成源码只允许 React、Remotion 和归档素材导入；不接受 AI 提供的构建配置或依赖安装。
- HTML 使用 `sandbox="allow-scripts"` 的不透明来源 iframe，配合 CSP 阻止联网和父页面访问。
  MP4 通过 Blob 播放以支持在 attachment 文件服务上拖动进度。平台通用 HTML 预览策略保持原样。
- 预览包包含脚本、图片、录音及字体，不依赖任务目录。源码 ZIP 包含原素材、固定依赖、
  分镜、动画组件和构建说明，不包含缓存或 node_modules。源码和视频都能单独下载。
- 子进程使用独立进程组；取消或超时结束进程树。生成调用最长 600 秒/次，预览构建最长
  300 秒/次，视频渲染最长 1200 秒；工作目录清理失败不覆盖任务结果。

首版不包含自动配音、手动时间轴、卡通视频模型或 GIF。编译及播放器校验不等同于内容
正确性审稿；正式使用前可在 HTML 播放器查看效果，再点击导出。

## 验证

```powershell
backend\venv\Scripts\python.exe -m pytest -c backend/pytest.ini backend/app_center/animation_studio/backend/tests -q
npm.cmd test --prefix backend/app_center/animation_studio/engine
cd frontend
npx.cmd vitest run src/pages/Apps/__tests__/animationStudio.test.ts src/layouts/__tests__/animationScrolling.test.ts src/lib/__tests__/applicationCatalog.test.ts
npm.cmd run build
```

媒体检查可对独立源码目录执行 `node runner.mjs preview <project>` 和 `node runner.mjs render <project>`。
设置 `ANIMATION_CAPTURE_FRAMES=1` 可保存 HTML 开头、中间和结尾 PNG；用 FFmpeg 提取 MP4
相同帧比较（排除播放器控制栏，并容许 H.264 压缩误差）。另外检查一例非整秒录音，确保
视频覆盖完整音频。`node runner.mjs stills <project>` 可生成 Remotion 无压缩对照帧。
不使用 Codex 内置浏览器。CSS 契约和 jsdom 检查不代表手机真机触摸验证。
