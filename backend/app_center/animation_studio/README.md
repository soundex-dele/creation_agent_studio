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

v2 使用场景级编辑，不提供任意元素的多轨关键帧编辑、卡通视频模型或对外分享。
编译及播放器校验不等同于内容正确性审稿；正式使用前查看预览，再点击导出。

## v2 工作台

默认入口升级为作品工作台；`animation=<run_id>` 仍定位历史版本，`legacy=1` 可打开原版文字修改界面。
作品支持重命名、搜索、复制、归档/恢复。草稿每次停止输入约 1 秒自动保存，携带修订号；
409 冲突保留当前内容并让用户选择服务器或本地副本。缓存按组织、应用、账号、作品隔离。
任务结果仅在草稿修订号未改变时自动写回，否则保留为 `animation-document` 并提供手动应用入口。

生成版本保持不可变：版本列表、缩略图、并排预览、内容对比和恢复草稿均不覆盖原产物。
旧 TSX 作品继续按旧格式渲染；“复制并转换为分镜工程”依据旧源码、分镜与要求重新编排，
不会宣称转换前后画面完全一致。

场景工程 `project.json` 使用 `schema_version: 2`，包含稳定场景 ID、帧数、文案、旁白、
画面描述、素材、样式、源码和锁定状态，以及音轨、字幕和品牌快照。最多 30 幕、50 个素材，
素材合计仍限 100 MB，时长 5–120 秒、30 fps。场景源码各自通过 AST 校验；组合器负责
排序、音频、字幕和 Logo。文字和颜色经 `scene` 属性传入；画面描述或画幅调整会重新生成
未锁定场景源码。锁定场景必须先单独解锁，不能同时解锁并改写内容。

素材库支持分类、搜索、改名、预览和归档；历史版本始终使用归档中的原始字节。
旁白、音乐、音效支持场景定位、时间、裁剪、音量、循环和淡入淡出。旁白不会静默截断，
超出时长时提示延长分镜。字幕支持 Whisper 识别、手工校对与时间修改、样式及显示开关。
分镜重排会相应调整字幕时间。模板包括知识、产品、流程和数据四类，也可保存自定义变量模板；
品牌预设包含色彩、受支持字体、Logo、字幕样式和片尾。

### 豆包语音

组织管理员在“配音配置”中设置资源 ID、可用音色及组织秘密引用名称。
新版火山控制台使用 API Key（应用 ID 留空）；旧版填写 App ID，秘密引用指向 Access Token。
秘密值由现有 `SecretReference` 的服务端环境引用解析，不存入草稿、Run 输入、预览或源码。
协议依据 [HTTP Chunked V3 官方文档](https://www.volcengine.com/docs/6561/1598757)，
使用官方 `https://openspeech.bytedance.com/api/v3/tts/unidirectional`，默认资源 `seed-tts-2.0`。
音色 ID 必须与已开通资源匹配。合成字符数、音频字节数写入用量记录，不伪造费用。
配音归档后可复用，字幕通过本地 Whisper 对实测音频识别。
缺少凭据时仍可上传录音和制作无声动画；协议模拟测试不代表真实云服务已联调。

### 新增接口

以下路径均位于原租户应用 API 前缀下，继续执行组织、应用、所有者鉴权：

| 方法与路径 | 用途 |
| --- | --- |
| `GET/POST /projects` | 分页搜索或创建作品，`archived=1` 查询归档 |
| `GET/PATCH /projects/{id}` | 草稿、版本和任务详情；修改名称/归档状态 |
| `PUT /projects/{id}/draft` | `{revision, document}` 乐观并发保存 |
| `POST /projects/{id}/copy` | 复制作品 |
| `POST /projects/{id}/restore` | `{revision, version_id}` 恢复为草稿 |
| `POST /projects/{id}/convert` | `{version_id}` 复制旧作品为分镜工程 |
| `POST /projects/{id}/apply-result` | `{revision, run_id}` 应用未自动写回的任务结果 |
| `POST /projects/{id}/tasks` | `storyboard/generate/scene/speech/transcribe`；携带修订号与幂等键 |
| `GET /assets`、`GET/PATCH /assets/{id}` | 私有素材库、媒体读取及改名/分类/归档 |
| `GET/POST /presets` | 内置/个人模板与品牌 |
| `GET/PUT /speech-config` | 配音配置；写入仅限组织管理员 |
| `POST /batches/import` | CSV/XLSX 工作表读取，不执行公式或宏 |
| `GET/POST /batches` | 批次列表、逐行校验及提交 |
| `GET/POST /batches/{id}` | 逐行进度、取消、重试失败项 |

任务、导出、批次提交沿用 `Idempotency-Key`。导出原有空正文仍有效，新增正文接受
`format=mp4/gif/png/srt/vtt`、`resolution=720/1080`、`quality=standard/high`、
`cover_frame`、可选 `scene_id`。GIF 无声音，15 fps，长边 720px，最长 15 秒。
画幅在草稿中调整并生成新版本，导出不执行跨画幅拉伸。

批量制作最多 100 行，使用模板变量映射文本、数字和已有素材 ID；图片地址不自动抓取。
导入文件最多 10 MB、20 张工作表，每表 100 行数据和 100 列。XLSX 公式须先转为值。
每批最多两个同时活动的子任务，父任务通过平台 `wait_for_children` 释放执行槽位。
取消不删除已完成结果；重试复用成功任务，只重做失败阶段。ZIP 按平台产物大小限制分包，
极大文件列在 `results.json` 中并保留在对应作品供单独下载。

## 升级、回退与验收

1. 先通过 SQLite 在线 backup 或 PostgreSQL 备份工具保存一致数据库快照，并保留产物存储。
2. 在副本运行迁移，核对历史 Run 数量与按用户、应用、合法来源链归组的版本关联。
   `0003` 创建实体，`0004` 回填历史版本并为新表启用 PostgreSQL RLS。
3. 安装 `backend/requirements/base.txt` 中的 `openpyxl` 与 `requests`；部署新后端与渲染器。
   工作进程按任务启动并导入适配器；确保新进程使用新代码，再同步 v2 应用清单及前端。
4. 执行原部署命令中的迁移、`validate_app_center` 与 `sync_app_center`。不要重复启动协调器，
   不要中断正在运行的旧任务。开发启动器可能自动执行已发现的应用迁移。
5. 回退时停用新任务入口并切回旧前端/清单，保留新表与所有产物；不在真实数据库反向删除新表。

回归覆盖草稿并发及恢复、历史归组、场景锁定与源码保留、任务幂等、批次派发/失败重试、
导入公式拒绝、字幕时间与豆包流式协议。媒体验收另用真实 Remotion/FFmpeg 构建预览和视频，
核对尺寸、时长、音轨、完整解码、PNG/GIF/SRT/VTT。前端类型、lint、构建、jsdom 和 CSS
滚动契约检查不等于手机真机视觉验证；本项目不使用 Codex 内置浏览器。

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
