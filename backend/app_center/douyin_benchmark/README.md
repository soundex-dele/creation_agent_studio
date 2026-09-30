# 抖音对标助手

独立应用 `douyin-benchmark`：个人对标账号 → 采集批次与作品快照 → 账号分析／视频转写与关键帧 → 3个新选题 → 可编辑脚本版本与 Markdown。首版不定时采集、不发布、不制作成片、不采集评论。

## 采集运行方式与验收边界

按 `backend/scripts/douyin_video_url.py` 的直接源码调用方式集成：复用 Cookie 解析、浏览器指纹、原生签名、WreqTransport 和 DTK 标准化解析器，扩展账号主页解析、作者资料和作品分页。当前使用本地 **DTK v5.1.2** 源码 commit `d8f874cd5b647b0ca087a57b15a458c3864439fa`（见 `deploy/provider-lock.json`）。不需要 DTK API 服务、API key、Docker、Redis 或 Qt worker。

主应用继续使用 Python 3.11，通过 JSON stdin/stdout 调用独立 Python 3.12/3.13 进程。凭据只通过 stdin 管道传递，不出现在命令行、Run 输入、模型提示词、错误信息或任务日志中。取消／超时会终止并回收子进程。每页重新读取当前用户配置，清除配置后后续请求停止。

**真实账号链路仍待验证**：当前没有导入可供实测的浏览器 Cookie。自动化检查使用 DTK 仓库样本验证真实签名、传输封装、资料/分页/详情解析；这些检查不代表抖音线上请求成功。页面检查仅验证格式和运行环境，不声称 Cookie 有效。

## 部署与页面配置

1. 从仓库根目录使用统一安装脚本（默认全量安装也包含此步骤）：

```powershell
# Windows
.\install-dependencies.ps1 -App douyin-benchmark
```

```sh
# Linux / macOS
bash install-dependencies.sh --app douyin-benchmark
```

脚本初始化并校验上述固定 commit 的 DTK Git 子模块，创建或复用 `backend/.venv-dtk`，安装采集依赖并运行离线测试。新建时优先使用主项目 Python 3.12/3.13，否则通过 uv 准备 Python 3.13。已有环境不兼容或不完整时会报错，需移走旧环境后重跑。使用 `--skip-submodules` 时仍需保留固定版本的干净 Git 检出。FFmpeg 缺失时加 `-SystemDeps` / `--system-deps`。
2. 也可参照 `backend/scripts/douyin_video_url.md` 手动部署固定版本源码并建立独立环境：

```sh
uv venv --python 3.13 backend/.venv-dtk
uv pip install --python backend/.venv-dtk/bin/python -r backend/scripts/douyin_video_url.requirements.txt
```

3. Web 与 media worker 都需要上述源码和独立运行环境。非默认路径设置 `DOUYIN_DTK_PYTHON` 为独立解释器绝对路径；Windows 默认使用 `backend/.venv-dtk/Scripts/python.exe`。
4. 进入应用 → **采集设置**，粘贴同一桌面 Chrome/Chromium 浏览器抖音网页请求的 User-Agent 和 Cookie。Cookie 支持请求头、JSON 对象、浏览器导出的 JSON 数组，需包含有效 `UIFID` 或 `UIFID_TEMP`。屏幕尺寸、语言和时区应与该浏览器一致。无需向开发者发送凭据。
5. 保存配置后添加账号或刷新已有账号。Cookie 使用 Django `SECRET_KEY` 派生的独立 Fernet 密钥加密，按组织、应用和所有者隔离。API 只回传 `has_cookies`，编辑留空保留原值，“清除已保存配置”仅删除本人的配置。密钥变更后需重新保存 Cookie；生产环境保护 `SECRET_KEY`，通过 HTTPS 访问页面，反向代理不要记录配置请求体。

| 配置 | 作用 |
| --- | --- |
| `DOUYIN_DTK_PYTHON` | 可选，独立 Python 3.12/3.13 解释器路径；默认 `backend/.venv-dtk/bin/python` |
| `DOUYIN_MEDIA_ROOT` | 私有素材目录，默认 `backend/private_media/douyin`；Web 与 worker 共享，不映射为公开媒体目录 |
| `DOUYIN_WHISPER_ROOT` | 原版 Whisper 本地模型目录，默认 `~/.cache/whisper`（Windows 当前用户为 `C:\Users\admin\.cache\whisper`） |
| `DOUYIN_WHISPER_MODEL` | 默认 `base`，加载目录内 `base.pt`；也可填写 `.pt` 文件的绝对路径 |

应用 deployment `config_override` 可设置 `answer_provider`、`answer_model`、`vision_provider`、`vision_model`。文本模型优先采用组织路由；组织尚未创建提供方且未指定 `answer_provider` / `answer_model` 时，使用系统 `AGENT_ENGINE_ADAPTER` 对应的引擎（例如已登录的 Codex）及其默认模型，无需另填 API 提供方。显式 API 配置错误、已禁用的提供方或 API 请求失败不会切换引擎。系统引擎在临时目录中分析输入资料，支持取消；每次请求执行成员用量检查并记录真实 usage。

视觉模型仍需明确设置 `vision_model`，支持 OpenAI-compatible 图片输入。未配置或调用失败的视觉分析会标记待完成／失败，保留已取得转写与关键帧。失败任务保留原记录，修复配置后重新发起分析；协调器为新任务启动独立子进程并加载当前运行时代码。

依赖 FFmpeg、ffprobe 和 `openai-whisper`，与 creation_master 使用相同的原版 `.pt` 模型格式。默认复用执行 worker 用户的 `~/.cache/whisper/base.pt`，直接加载本地文件，不自动下载模型；文件缺失时提示配置错误。部署到其他机器或服务账号时需提前放置模型或配置上述路径。自动使用可用 CUDA，否则使用 CPU。页面区分加载模型和转写阶段；原版 Whisper 在整段识别完成后更新进度，识别调用期间不能即时中断，返回后会检查取消状态。单视频最多500 MiB、10分钟；每条作品最多16帧（开头0/1/2/3秒及全片均匀采样）。关键帧不等同完整视听分析。单次采集选择20／50／100条，串行分页，异常保留已取得部分，不自动无限重试。

## 应用安装

从仓库根目录，所有后端命令使用项目虚拟环境；Windows 对应 `backend\venv\Scripts\python.exe`。

```sh
backend/.venv/bin/python backend/manage.py validate_app_center
backend/.venv/bin/python backend/manage.py migrate douyin_benchmark --noinput
backend/.venv/bin/python backend/manage.py sync_app_center --package douyin-benchmark
```

安装后重启 Web、执行 coordinator 和 media worker，发布前端构建。该包新增独立数据库表，不更改其他应用数据。所有者、组织、应用三层查询隔离，PostgreSQL 加组织 RLS；管理员不因此获得私人数据。Run 输入只保存任务 ID，成果仅由私有应用接口读取。生成前冻结资料、创作要求和用户明确选中的品牌定位／语气快照。

```sh
backend/.venv/bin/python backend/manage.py probe_douyin_collection --organization 组织UUID --application 应用ID --owner 用户ID --account 已添加账号UUID
```

真实验收必须满足：作者资料、至少两页去重作品、实际指标、一个视频下载并通过 ffprobe；然后在应用内完成拆解、选择选题、保存并下载脚本。未取得模型与采集配置时不得将替身测试当作此验收。

## 视频地址与升级

`web_url` 是来源作品页，DTK 的视频文件地址来自 `media.video.url` / `media.video.urls`，备用清晰度来自 `media.streams`；不会使用作品 ID 拼接媒体下载地址。应用保存列表已返回的无水印媒体地址，并在作品库分别展示“播放视频”和“抖音来源页”。图文来源使用 `/note/{id}`。

升级时执行 `migrate douyin_benchmark` 并重启 Web 与 media worker。**已有作品需手动“刷新作品数据”一次**，旧记录此前未保留列表中的媒体地址。拆解冻结本次选择的媒体候选地址，优先尝试这些地址；缺失或 CDN 请求失败时重新请求详情获取地址。URL 单独保存在私人作品和任务输入中，不进入指标快照、模型提示词或通用 Run 日志。播放地址可能过期，重新刷新作品可更新。根据当前环境的可播放反馈，脚本、页面和下载统一优先选择 DTK 实际返回的 `v11*.douyinvod.com` 候选，保留其他地址作回退；不会拼接域名或改写签名参数。既有记录读取时也会重排已有候选，不需要为调整顺序重新采集。

HTTP(S) 媒体地址均按 DTK 返回值处理，仅允许平台 CDN 域名和公共 IP，下载时不发送采集 Cookie。允许列表覆盖固定版本 DTK 的 Douyin 媒体域名（含 `zjcdn.com` 等地区 CDN），每个重定向仍检查协议、域名、端口和 DNS 公共地址。某候选被拒绝时会尝试备用地址；所有候选失败时错误区分原地址与重定向地址，并仅显示主机名，不暴露签名路径或查询参数。平台验证、签名失败、空响应与作品不可访问分别提示，不能仅凭这些错误断言 Cookie 已失效。

## 数据语义

- 每次采集保留独立批次及逐作品快照；刷新更新作品索引，不覆盖历史批次。分页重复游标终止并报告部分成功。
- “完成”指本次请求数量满足或平台已到末页，不表示抓取了整个账号历史。字段缺失为 null，0 是有效值。
- 同账号、同批次、发布满48小时且点赞有效的样本不少于10条，中位数大于0，才能计算点赞倍数；3倍及以上标记突出。新作品不参与；指标不表示因果或未来爆款概率。
- 账号结论引用作品 ID 或已完成拆解 ID；视频口播结论只引用转写段落 ID，画面结论只引用帧 ID。每次分析向模型明确提供允许引用的 ID 清单；结构或引用校验失败时最多自动重新生成一次，每次调用照常检查额度并记录用量。网络、配置或额度错误不自动重试；再次校验失败时保留已取得的转写与关键帧。服务端校验引用存在，但这不是语义真伪证明；UI 支持核对出处。
- 失败或取消不覆盖既有成果。重试通过再次刷新、分析或拆解创建新任务；脚本手动保存创建新版本，使用 revision 防止覆盖并发编辑。
- 移除账号取消任务并删除关联数据。已导出的文件独立保留。定期运行 `cleanup_douyin_media` 清理删除账号、失效上传等产生的24小时以上孤立素材；运行失败返回非零状态。有效历史任务引用的素材保留。

## 接口

前缀 `/api/v1/organizations/{organization_id}/applications/{application_id}/douyin-benchmark`；单租户模式支持已有省略组织前缀的别名。

- `GET/PUT/DELETE /collector-config`：本人采集配置；Cookie 只写入不回显，空值保留。
- `GET /connection`、`GET /brands`：本地配置检查、可引用私有品牌（仅定位与语气）。
- `GET/POST /accounts`；`GET/PATCH/DELETE /accounts/{id}`：添加时创建采集任务，支持备注与分组。
- `GET /accounts/{id}/works`：`batch_id/search/sort/outstanding`；`POST .../works/{work_id}/upload` 接收 multipart `video`。
- `GET/POST /accounts/{id}/tasks`：操作 `collect/account/breakdown/topics/script`；`GET .../tasks/{task_id}`、`POST .../cancel`、`GET .../frames/{frame_id}`。
- `GET/POST .../tasks/{task_id}/versions`：读取或保存脚本；`GET .../versions/{version_id}/download`：Markdown。
- 创建账号、任务要求 `Idempotency-Key`。同键同参重放，同键异参409；脚本保存必须携带读到的最新 `revision`。

## 检查

```sh
backend/.venv/bin/python backend/app_center/douyin_benchmark/deploy/verify_source.py
backend/.venv-dtk/bin/python backend/app_center/douyin_benchmark/collector_source_checks.py
backend/.venv-dtk/bin/python -m unittest discover -s backend/scripts -p test_douyin_video_url.py
backend/.venv/bin/python -m pytest backend/app_center/douyin_benchmark/backend/tests -q
npm run test --prefix frontend -- src/pages/Apps/__tests__/douyinBenchmark.test.tsx src/layouts/__tests__/douyinLayout.test.ts src/layouts/__tests__/mobileScrolling.test.ts src/lib/__tests__/applicationCatalog.test.ts
npm run lint --prefix frontend
npm run build --prefix frontend
```

页面使用 `ApplicationShell fullBleed` 和全局 `app-scroll-page`，父容器限定高度。CSS／jsdom 检查覆盖手机、767/768边界和短视口，不代表已做浏览器或真实设备触屏验证；遵守仓库不使用 Codex 内置浏览器的规定。
