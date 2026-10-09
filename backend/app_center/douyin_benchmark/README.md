# 抖音对标助手

独立应用 `douyin-benchmark`：个人对标账号 → 跨账号研究／评论需求 → 灵感和选题库 → 个人创作档案／脚本与表达实验 → 关联发布作品 → 指标追踪和复盘。保留单账号分析、视频拆解、文案改写、脚本版本和动画制作导入。订阅为用户主动开启的定时采集；不自动发布，也不把公开互动数据解释为播放量、完播率或未来效果。

## 我的账号与个人文风

入口 `?view=owned&owned=<accountId>` 支持多个自己的账号，保留原有入口与展示参数。每个账号绑定独立创作档案；旧档案不自动绑定，新账号也不继承其他账号的默认文风。

- 从已采集作品添加样本，优先复用成功转写；缺失时可转写或粘贴正文。样本分为“代表我的风格／只参考内容／不学习”。转写结果需核对后保存。每次最多20篇、12万字符；建议5—10篇，少于3篇正文标注初步分析。仅标题只可分析定位。
- 分析任务只产生草稿，结论必须引用原文连续片段。编辑定位、规则、示例及完整提示词后确认新版本；可复制提示词、查看历史、重新启用旧版本。共享经历从文本灵感中显式选取，专属经历、产品事实与拍摄条件随确认版本保存。
- 每次生成3个账号选题，说明支柱、适配原因、素材缺口及重复提醒（仅覆盖已采集最近100条）。选题与脚本冻结账号、文风版本、样本和共享素材。后续编辑或切换版本不影响已有任务。不提供“AI率”或未获取的完播率。
- 已完成的选题卡片提供“开始写作”：通过`POST tasks`的`kind=article`、`source_task_id`和`topic_index`生成完整文章，沿用该选题冻结的文风和事实快照。文章标题、正文、待核实事项分别保存；可编辑、保存历史版本、复制正文和导出Markdown。文章独立于拍摄脚本，不受视频时长或分镜要求限制；删除来源账号后仍保留已保存文章。此扩展无需新增迁移。
- API：`voice-samples` 沿用私有记录的分页、CRUD和revision冲突校验；`creator-profiles` 增加account、active_version等字段；`GET/POST creator-profiles/{id}/voice-versions` 查看历史／确认版本，`POST …/voice-versions/{versionId}/activate` 启用历史版本；`POST tasks` 支持`voice_analysis`与`target_account_id`，选题支持省略主题。
- 删除账号后保留已确认档案、样本文本、版本和已保存文案，清除失效外键。新表沿用组织RLS和应用／用户访问隔离。

部署前应用迁移0008、0009（包含PostgreSQL RLS）：在仓库根目录运行 `backend\venv\Scripts\python.exe -X utf8 backend\manage.py migrate`。Windows测试使用项目虚拟环境和`-X utf8`，避免测试夹具按GBK读取UTF-8文件。

## 账号分析导出

打开账号工作台的「对标账号」，选择已完成且有结论的历史分析，点击结果标题旁的「导出 Markdown」。新完成的分析也可直接导出；下载失败可重试。报告包含样本统计、时长分布、分类结论和编号出处，使用该任务冻结的作品及视频拆解快照，账号名称与主页链接使用导出时的当前信息。

下载接口为 `GET …/douyin-benchmark/accounts/{accountId}/tasks/{taskId}/download`，沿用账号私有访问权限，返回 UTF-8 Markdown 附件并禁用缓存；不支持的任务类型、未成功或无结论的任务返回 400。此功能无需数据库迁移。

## 跨账号研究与创作闭环

页面提供“对标研究、选题库、创作中心、作品复盘、订阅通知”五个入口，旧的 `?account=` 链接继续可用。`view` 和 `task` 查询参数可定位应用级页面和历史任务，保留 entry/standalone/embedded 展示参数。

- 选题雷达使用最近7／30／90天的已采集作品，默认30天，最多200条，按账号轮流抽样并显示覆盖范围。已有转写优先，没有转写只分析标题和描述。首次建立基线；后续“新出现”表示同范围报告中未出现的主题名称，需核对原作。
- 2–5个账号可直接比较样本指标；AI内容分析单独启动。突出作品占比沿用发布满48小时、至少10条有效点赞样本及3倍中位数规则。定向刷新旧作品不会改变主页研究样本。
- 联合拆解支持2–5条视频，复用有效历史拆解；缺失时创建子任务，父任务进入 waiting_children 并释放执行资源。结果显示每条状态，至少两条有有效资料才生成结论。引用采用任务ID和片段／帧ID组合，支持核对原始出处。
- 收藏作品、转写片段、开头、关键帧或自由文本；选题状态为待研究／待创作／待拍摄／已发布。可添加标签、笔记、排序序号，并通过拖放或状态控件移动。
- 创作档案可保存多份并设置默认，生成任务冻结定位、受众、经历、产品、表达习惯和拍摄条件；本次填写内容可覆盖默认值。个人资料仍可与现有品牌定位／语气引用共同使用。
- 表达实验从保存版本生成各3个开头、标题及封面短句，支持编辑、收藏、保存候选版本和组合应用。应用开头会添加在原稿开头，应在脚本编辑器检查衔接；这不是效果预测或已完成的A/B测试。
- 评论采集默认100条一级评论，可选50／100／200条；可包含每条一级评论最多20条回复，每作品总计最多500条。分页中断保留已采集内容，需求分析引用具体评论。研究仅使用评论正文、关联ID、时间与点赞等必要字段，不保存评论者资料。
- 将账号标记为“我的账号”后，可关联已发布作品、选题、脚本版本和实际标题／开头。使用DTK公开点赞、评论、收藏及可获取的分享数据；不接入官方授权、手填指标或CSV导入。

所有新增资源按组织、应用、所有者隔离。应用级 Task 显式保存三项归属；迁移从旧账号回填，账号关联可为空。删除账号时停止订阅并清除来源研究；独立选题和已保存文案保留，来源不可用。模型调用前冻结输入、校验引用并记账；媒体签名地址不进入新研究提示词。

## 私有订阅与日报

升级不自动开启订阅。默认每24小时刷新，支持6／12／24小时及20／50／100条主页作品，另可指定最多20条重点追踪作品。后台刷新、增长提醒与日报只做数据计算，不自动启动模型。

调度接入现有 `run_automation_scheduler`，私有订阅不写入组织共享 Automation。Windows及Unix部署脚本在启动执行worker时同时启动scheduler；桌面启动器原本已有scheduler，无需重复启动。账号已有采集时跳过本轮，同一用户的自动采集串行执行，停机只补最近一轮。网络不可用或超时退避重试一次；认证、平台验证或权限问题暂停订阅，修复后主动恢复。清除配置会暂停订阅并取消在途采集。

默认增长规则：相邻采集增长至少50%，且点赞增加100或评论／收藏增加20，任一指标满足即提醒；前值为零只检查绝对增量。规则可编辑，保留负增量与缺失值，按采集区间去重。日报在北京时间每天09:00汇总前24小时新增作品、指标变化和异常，无变化不生成。通知仅应用内可见。

## 扩展部署与验证

数据库升级前停止写入并备份；已有部署更新后运行：

```powershell
backend\venv\Scripts\python.exe -X utf8 backend/manage.py migrate douyin_benchmark --noinput
backend\venv\Scripts\python.exe -X utf8 backend/manage.py backfill_douyin_observations
```

历史观测回填按500条分批读取，可以重复执行；回填前趋势接口仍可读取旧 Snapshot。重启Web、coordinator/media worker和scheduler，并发布新的前端构建。新增表与任务归属配置PostgreSQL RLS；SQLite测试不等同于PostgreSQL部署验证。

现有账号级接口保持兼容，新增应用级 `/works`、`/tasks`、`/creator-profiles`、`/inspirations`、`/ideas`、`/comparisons`、`/publications`、`/subscriptions`、`/notifications`、`/digests`。作品提供 `/trend` 和 `/comments`；任务提供取消、版本、下载、关键帧、候选应用；订阅提供 `/refresh`。可编辑记录使用 revision 冲突检测，任务与立即刷新要求 Idempotency-Key。

真实采集探测命令可加 `--comments` 验证评论解析。2026-09-30本机实测：账号资料和第一页返回成功，作品详情的点赞／评论／收藏字段及8条评论正文通过；第二页作品返回HTTP 200空响应，完整多页／下载探测未完成。不能据此认定Cookie失效，也不把离线样本通过写成完整线上验收。本机文本模型也已验证结构化分析与引用校验（1条有效观察）。UI以自动化测试、CSS布局检查和构建验证，不使用内置浏览器，不声称完成视觉或真机验证。

## 爆款文案复刻

所有视频作品均可点击“爆款复刻”，无需达到表现突出指标。自动复用该作品最近一次成功、非空的转写或拆解原文（补传视频变更后不复用旧素材的转写）；没有可用原文时仅提取音频并调用本地 Whisper，不提取关键帧或分析画面。“重新转写”强制创建新转写任务。空转写允许手工补全；下载、无音轨及模型错误保留任务和明确重试入口。

校正原文后填写可选改写要求，生成一篇同主题完整正文，保留核心观点、事实和大致篇幅，优化开头、衔接与口语表达，不把原作者经历写成用户经历。模型提示词约束不能代替人工核实。此流程不生成标题、分镜、清单或成片。改写任务冻结校正原文及要求，不覆盖原始识别内容，历史记录可恢复该快照。结果编辑后保存为新版本，旧版本保留，并使用 revision 检测并发冲突；未保存内容可复制，导出须先保存。

图文作品也可点击“爆款复刻”：先打开表单，自动填入去重后的标题与描述，允许手动补充图片文字。此流程未读取图片内文字，不下载素材、不调用 Whisper，也不做 OCR。填写可选“创作主题”后提交，非空时围绕指定主题写作，留空沿用素材主题；参考原文不能为空。

图文写作从服务端 `CODEX_SKILLS_DIRECTORY/wechat-viral-article/` 加载 `SKILL.md` 及其引用的 `references/`、`templates/` Markdown 资料，注入结构化生成指令。部署时须在执行 worker 可读取的技能目录保留完整技能包；缺失、不可读、空文件、越界引用或资料总量超过160,000字节会明确报错，不回退普通提示词。图文结果仍为 `{text}`，内容是一个 Markdown 标题和完整文章，不输出候选选题、标题列表或自检过程。主题与原始作品类型、标题、描述、校正原文和要求均冻结，历史可恢复；技能的算法与流量断言不视为已核实事实，生成不承诺爆款效果。

复用原有私有 Task／ScriptVersion JSON 存储，无新增迁移；部署时更新前端并重启 Web、coordinator 和 media worker。

## 采集运行方式与验收边界

按 `backend/scripts/douyin_video_url.py` 的直接源码调用方式集成：复用 Cookie 解析、浏览器指纹、原生签名、WreqTransport 和 DTK 标准化解析器，扩展账号主页解析、作者资料和作品分页。当前使用本地 **DTK v5.1.2** 源码 commit `d8f874cd5b647b0ca087a57b15a458c3864439fa`（见 `deploy/provider-lock.json`）。不需要 DTK API 服务、API key、Docker、Redis 或 Qt worker。

主应用继续使用 Python 3.11，通过 JSON stdin/stdout 调用独立 Python 3.12/3.13 进程。凭据只通过 stdin 管道传递，不出现在命令行、Run 输入、模型提示词、错误信息或任务日志中。取消／超时会终止并回收子进程。每页重新读取当前用户配置，清除配置后后续请求停止。

采集入口兼容 `wreq 0.12/0.13`：0.13 将响应正文和响应头改为 `memoryview`，公共传输适配器在交给固定版本 DTK 前统一转为 `bytes`，避免收到 HTTP 200 后在响应分类阶段触发 `TypeError`，并保留响应头分类、重复响应头合并和 Set-Cookie 过滤行为。该适配由账号采集与视频地址脚本共用，不修改固定版本的 DTK 子模块；依赖范围限制为 `wreq>=0.12,<0.14`。测试包含本机 HTTP 服务和实际 wreq 客户端，不仅使用替身响应。

**真实账号链路验收边界**：最近实测结果见上方“扩展部署与验证”。自动化检查另使用 DTK 仓库样本验证签名、传输封装和解析，不替代线上验收。页面配置检查仅验证格式和运行环境，不声称 Cookie 有效。

采集失败时，在 media worker 日志中查找同一 `run_id` 的 `collector.failed` 行：`code` 为错误分类，`stage` 区分短链解析（`resolve_url`）、签名（`sign`）、网络传输（`transport`）、响应分类（`response`）和数据解析（`parse`）；另保留已知接口名、HTTP 状态和异常类型。没有响应时 HTTP 状态为 `-`。日志不输出 Cookie、签名地址、响应正文或原始异常消息。网络传输失败按 `unavailable` / `timeout` 最多重试一次，不再误报为数据结构不兼容；仅有外层 `CollectionError` / `execution_adapter_failed` 无法确定根因。

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
5. 保存配置后添加账号或刷新已有账号。同一组织、同一应用的所有用户共用一套 Cookie 和 User-Agent；Cookie 明文保存并回显，可查看和编辑，留空保留原值。保存对所有用户生效；“清除已保存配置”会清除共享配置、暂停该应用所有用户的采集订阅并取消采集任务。配置不跨组织或应用共享，账号、作品与创作内容仍按用户隔离。迁移 `0010_collector_cookies_plaintext` 使用原 Django `SECRET_KEY` 解密旧配置，`0011_shared_collector_config` 将同一应用的多份旧配置合并为最近保存的一份；后续读写不再依赖加密密钥，删除最后保存配置的用户也不会删除共享配置。通过 HTTPS 访问页面，反向代理不要记录配置请求体。

| 配置 | 作用 |
| --- | --- |
| `DOUYIN_DTK_PYTHON` | 可选，独立 Python 3.12/3.13 解释器路径；默认 `backend/.venv-dtk/bin/python` |
| `DOUYIN_MEDIA_ROOT` | 私有素材目录，默认 `backend/private_media/douyin`；Web 与 worker 共享，不映射为公开媒体目录 |
| `DOUYIN_WHISPER_ROOT` | 原版 Whisper 本地模型目录，默认 `~/.cache/whisper`（Windows 当前用户为 `C:\Users\admin\.cache\whisper`） |
| `DOUYIN_WHISPER_MODEL` | 默认 `base`，加载目录内 `base.pt`；也可填写 `.pt` 文件的绝对路径 |

文本与关键帧分析统一使用系统 `AGENT_ENGINE_ADAPTER` 及其默认模型，无需组织提供方。旧的 `answer_provider`、`answer_model`、`vision_provider`、`vision_model` 不再参与应用生成路由。系统引擎在临时目录中分析输入资料，支持取消；每次请求执行成员用量检查并记录真实 usage。

关键帧通过引擎的原生图片输入提交，目前支持 Codex app-server，无需另配视觉 API。引擎不支持图片输入或调用失败时，视觉分析标记失败，保留已取得的转写与关键帧；未提取到关键帧则标记待完成。失败任务保留原记录，修复系统引擎后重新发起分析；协调器为新任务启动独立子进程并加载当前运行时代码。

结构化模型生成的时限由 `APPLICATION_GENERATION_TIMEOUT_SECONDS` 控制，默认 300 秒，覆盖账号分析、文案与关键帧分析等调用。服务器处理较多资料时可在 `backend/.env` 设置为 `600` 等正整数，并重启执行服务。它与 `CODEX_REQUEST_TIMEOUT_SECONDS`（单次 app-server RPC 回复等待时间）不同。达到生成时限会尝试中断当前 Codex turn，页面明确提示生成超时，不自动重复模型请求；延长时限不能代替排查模型服务停滞或网络故障。

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

“我的账号”的定位／文风分析、选题和文章写作，以及研究创作结果页，支持显示生成中的公开回复。执行器将有界预览写入私有任务的 `progress.ai_preview`，最多每秒写入一次，页面复用约 2.5 秒轮询；不会显示推理、工具参数或模型诊断。预览按可读字段呈现，重试会替换上一轮内容，失败保留已收到片段，成功后清除预览并显示通过校验的正式结果。模型若不提供增量消息，只能在完整回复到达后显示。无需数据库迁移；已开始的旧任务不会补发预览。

前缀 `/api/v1/organizations/{organization_id}/applications/{application_id}/douyin-benchmark`；单租户模式支持已有省略组织前缀的别名。

- `GET/PUT/DELETE /collector-config`：组织内当前应用的共享采集配置；有应用访问权限的用户共用，Cookie 明文保存并回显，空值保留。
- `GET /connection`、`GET /brands`：本地配置检查、可引用私有品牌（仅定位与语气）。
- `GET/POST /accounts`；`GET/PATCH/DELETE /accounts/{id}`：添加时创建采集任务，支持备注与分组。
- `GET /accounts/{id}/works`：`batch_id/search/sort/outstanding`；`POST .../works/{work_id}/upload` 接收 multipart `video`。
- `GET/POST /accounts/{id}/tasks`：操作 `collect/account/breakdown/topics/script/transcribe/rewrite`；`GET .../tasks/{task_id}`、`POST .../cancel`、`GET .../frames/{frame_id}`。
- `transcribe` 仅支持视频，输入 `work_id` 与可选 `force`（默认 false），输出 `text/segments/duration`。`rewrite` 输入 `work_id/source_text` 及可选 `rewrite_requirements`（默认空）；视频还必须传 `source_task_id`，来源为同作品成功的转写或拆解。图文无需且不接受 `source_task_id`，支持可选 `theme`（最多2,000字符，留空沿用原主题）。原文最多20,000字符，要求最多3,000字符，结果为非空且最多20,000字符的 `{text}`。私有任务详情 `copy_context` 返回作品类型、标题、描述、来源任务ID、校正原文、主题及要求，便于历史恢复；旧任务缺少类型时按视频兼容。
- `GET/POST .../tasks/{task_id}/versions`：读取或保存脚本／改写正文；按任务类型校验内容。`GET .../versions/{version_id}/download`：Markdown，改写任务仅导出正文。
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
