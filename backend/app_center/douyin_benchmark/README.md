# 抖音对标助手

独立应用 `douyin-benchmark`：个人对标账号 → 采集批次与作品快照 → 账号分析／视频转写与关键帧 → 3个新选题 → 可编辑脚本版本与 Markdown。首版不定时采集、不发布、不制作成片、不采集评论。

## 采集运行方式与验收边界

按 `backend/scripts/douyin_video_url.py` 的直接源码调用方式集成：复用 Cookie 解析、浏览器指纹、原生签名、WreqTransport 和 DTK 标准化解析器，扩展账号主页解析、作者资料和作品分页。当前使用本地 **DTK v5.1.2** 源码 commit `d8f874cd5b647b0ca087a57b15a458c3864439fa`（见 `deploy/provider-lock.json`）。不需要 DTK API 服务、API key、Docker、Redis 或 Qt worker。

主应用继续使用 Python 3.11，通过 JSON stdin/stdout 调用独立 Python 3.12/3.13 进程。凭据只通过 stdin 管道传递，不出现在命令行、Run 输入、模型提示词、错误信息或任务日志中。取消／超时会终止并回收子进程。每页重新读取当前用户配置，清除配置后后续请求停止。

**真实账号链路仍待验证**：当前没有导入可供实测的浏览器 Cookie。自动化检查使用 DTK 仓库样本验证真实签名、传输封装、资料/分页/详情解析；这些检查不代表抖音线上请求成功。页面检查仅验证格式和运行环境，不声称 Cookie 有效。

## 部署与页面配置

1. 部署上述固定 commit 的 DTK 源码至 `backend/third_party/Douyin_TikTok_Download_API`。此目录是独立源码依赖，部署时需一并提供；勿将其依赖安装进主项目 Python 3.11 环境。
2. 参照 `backend/scripts/douyin_video_url.md` 建立独立环境：

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
| `CREATION_TOOLBOX_WHISPER_MODEL` | 复用共享转写模型，默认 tiny |

应用 deployment `config_override` 可设置 `answer_provider`、`answer_model`、`vision_provider`、`vision_model`。文本模型默认采用组织路由；视觉模型必须明确设置 `vision_model`，支持 OpenAI-compatible 图片输入。每次请求执行成员用量检查并记录真实 usage。未配置或调用失败的视觉分析会标记待完成／失败，保留已取得转写与关键帧。

依赖 FFmpeg、ffprobe 和项目已有 faster-whisper。转写使用本地 CPU。单视频最多500 MiB、10分钟；每条作品最多16帧（开头0/1/2/3秒及全片均匀采样）。关键帧不等同完整视听分析。单次采集选择20／50／100条，串行分页，异常保留已取得部分，不自动无限重试。

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

## 数据语义

- 每次采集保留独立批次及逐作品快照；刷新更新作品索引，不覆盖历史批次。分页重复游标终止并报告部分成功。
- “完成”指本次请求数量满足或平台已到末页，不表示抓取了整个账号历史。字段缺失为 null，0 是有效值。
- 同账号、同批次、发布满48小时且点赞有效的样本不少于10条，中位数大于0，才能计算点赞倍数；3倍及以上标记突出。新作品不参与；指标不表示因果或未来爆款概率。
- 账号结论引用作品 ID 或已完成拆解 ID；视频结论引用转写段落或帧 ID。服务端校验引用存在，但这不是语义真伪证明；UI 支持核对出处。
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
