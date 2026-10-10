# 仓库解读助手

应用标识、renderer 和 executor：`repo-explainer`；Django label：`repo_explainer`。

把公开 GitHub、源码 ZIP、服务端 Git 工作区保存为私有源码快照，生成带代码依据的功能解读，再选择生成视频文案或图文文案。仓库页只写文案；视频文案可交接给文案转剪映或动画制作，由目标应用设计分镜。图文文案只编辑和导出。

## 部署

使用现有系统模型引擎、成员用量检查和持久执行协调器的 `media` worker。仓库分析不依赖写作技能；文案生成分别读取 `CODEX_SKILLS_DIRECTORY/write-short-video-copy/SKILL.md` 和 `CODEX_SKILLS_DIRECTORY/write-image-text-copy/SKILL.md`。允许已安装技能目录为符号链接或 Windows junction，技能文件缺失、为空或不可读会明确失败，不退回通用提示词。部署时须在执行服务器安装这两个技能。

服务端将实际技能正文加入 `generate_json` 指令，证据作为独立资料传入。当前范围只生成文案，不要求分镜或图片，覆盖技能默认的可选交付。结果记录技能 slug 和文件 SHA-256；手工保存不能伪造此来源记录。剪映制作仍使用其现有技能及运行环境。

仓库根目录运行：

```powershell
backend\venv\Scripts\python.exe backend/manage.py validate_app_center
backend\venv\Scripts\python.exe backend/manage.py migrate repo_explainer --noinput
backend\venv\Scripts\python.exe backend/manage.py sync_app_center --package repo-explainer
npm.cmd run build --prefix frontend
```

部署后更新 Web 进程、前端及现有执行工作进程；不要另起重复协调器或中断其他运行任务。回退时停用应用入口，保留快照、文案与制作记录，不反向删除生产数据库表。

本地 Git 读取需要执行服务器安装 Git。普通用户只可读取自己的平台工作目录；管理员沿用 `APPLICATION_RUNTIME_ALLOWED_ROOTS` / `APPLICATION_RUNTIME_ALLOW_ALL_PATHS`。不会修改源仓库，不安装依赖，不执行仓库内脚本、hooks 或 filters。工作区复制包含未提交修改和未忽略的新文件，复制期间发现文件变化则失败。

GitHub 来源仅允许公开 `https://github.com/owner/repo`，引用单独填写；通过 API 固定 40 位提交 SHA 后下载归档。拒绝重定向，不使用环境 Git 凭据、`.netrc` 或代理认证；网络错误和 GitHub 限流会明确失败，不使用其他来源替代。

## 输入与分析边界

以下环境变量可配置上限：

| 变量 | 默认值 |
| --- | --- |
| `REPO_EXPLAINER_ARCHIVE_BYTES` | 100 MiB |
| `REPO_EXPLAINER_EXPANDED_BYTES` | 200 MiB |
| `REPO_EXPLAINER_FILES` | 20,000 |
| `REPO_EXPLAINER_FILE_BYTES` | 2 MiB / 文本候选文件 |
| `REPO_EXPLAINER_TEXT_BYTES` | 20 MiB / 快照 |
| `REPO_EXPLAINER_ANALYSIS_CHARS` | 180,000 / 最终证据上下文 |
| `REPO_EXPLAINER_ROUNDS` | 3 / 检索轮次 |

快照保存 UTF-8 文本、文件字节哈希、来源和排除清单。跳过依赖、构建产物、Git 元数据、常见凭据文件、二进制、LFS 指针和外部链接；不拉取子模块。ZIP 拒绝特殊文件、加密、重复路径、路径穿越及解压超限。

快照文本按 80 行分片，超过 12,000 字符的单片不进入模型上下文；原文仍留在快照。先读取文档、入口和清单，再由模型提出查询，由服务器在冻结文件中检索。报告显示实际读取的文件数、片段数及预算限制；不是全仓正确性证明。模型不能直接读取宿主文件、调用工具或运行代码。

功能状态只有 `documented`、`implemented`、`unconfirmed`，无自动实测通过状态。每项确定结论要求有效证据 ID；仅有文档不能标记实现。引用由服务端映射到不可变原文，模型不提供任意引用路径。结构/引用错误最多修复一次，失败保留诊断。

报告将能力合并为最多六组重点用户功能，并控制段落长度，以避免单次长篇输出超时。完整快照仍保留供回溯；这不是完整逐文件审计。

## API

以下前缀位于现有租户 API 内：`/applications/{application_id}/repo-explainer`。全部接口检查组织成员、源应用可运行权限和项目所有者。制作交接额外检查目标应用权限；通用 Run 和持续事件接口保留相同私有边界。

| 方法与路径 | 内容 |
| --- | --- |
| `GET/POST /projects` | 查询（`q` / `archived=1`）或创建项目；列表最多 200 项 |
| `GET/PATCH /projects/{id}` | 项目详情、历史快照/分析/文案/交接；修改标题与归档 |
| `POST /projects/{id}/imports` | `kind=github` + `url/ref`，`kind=local` + `path`，或 multipart `kind=zip` + `file` |
| `POST /projects/{id}/tasks` | `kind=analyze` + `snapshot_id`；或 `kind=write` + `analysis_id/feature_ids/angle/output/audience/style/duration/aspect`；`output` 为 `video`（默认）或 `image_text` |
| `GET /projects/{id}/tasks/{task}` | 状态、阶段、结果、错误、`run_id`、`event_sequence`；通过现有 Run SSE 实时订阅 |
| `POST /projects/{id}/tasks/{task}/cancel` | 取消任务；不会删除历史完成结果 |
| `GET /projects/{id}/snapshots/{snapshot}/evidence?path=…` | 快照原文、哈希、GitHub 固定提交链接 |
| `PUT /projects/{id}/contents/{content}` | `{revision, document}` 乐观并发保存；409 返回当前服务器版本 |
| `GET /projects/{id}/contents/{content}/download` | Markdown，包含旁白、分镜、素材清单、图文及证据编号 |
| `GET /integrations` | 当前有运行权限的剪映与动画应用 |
| `POST /projects/{id}/handoffs` | `{version_id,target_id}` 固定文案版本后创建制作草稿 |
| `GET/PATCH /handoffs/{id}` | 恢复制作用表单；`{revision,draft}` 保存，或 `{revision,conversation_id}` 关联真实会话 |

导入、启动任务和创建交接要求 `Idempotency-Key`，最长 160 字符。未知结果的网络重试沿用原键；修改参数或成功后重新提交使用新键。相同键不同内容拒绝。前端使用支持手机 HTTP 的共享字符串键工具。

新正文 `document` 使用 `schema_version=2`，包含 `kind/title/cover/alternatives/paragraphs/publish_copy/notes/aspect/duration/skill`。`kind` 为 `video` 或 `image_text`；段落包含 `heading/text/feature_ids/evidence_ids`。视频段落是自然口播段，图文段落是逐页文案，不包含分镜或成品图片。完整口播只拼接段落 `text`，不朗读标题、备注或发布配文。

所有段落保留 `needs_review=true`，人工编辑不自动提升可信度。每次保存建立不可变版本；生成新稿创建新作品。并发冲突保留本地文本，由用户选择服务器或本地版本。历史 `scenes/article` 格式仍可读取和导出，可提取其中一种文案保存为新版本，原始版本不改写；无需数据库迁移。旧 `both/article` 生成参数不再接受，未开始的旧任务需重新选择文案类型提交。

入队响应立即显示任务卡，实时显示排队、执行阶段、模型等待/输出字符活动、完成或取消状态；不虚构百分比。SSE 断线自动重连并以 2.5 秒间隔轮询兜底。事件序号避免旧回放覆盖新进度；终态触发结果刷新。未验证的模型正文与推理不进入进度事件。

## 制作交接

- 剪映：`source` 只包含完整口播文案；`requirements` 带入标题、封面及“由目标应用设计分镜”的要求；默认自动配音、不加空镜。URL 只有交接 ID 和源应用 ID。修改在服务端保存，刷新可恢复。关联会话必须属于同一用户、组织及目标聊天应用。交接状态不冒充剪映草稿完成。
- 动画：创建 `StudioDocument` v2 的新作品，将完整文案、目标时长和示意要求放入 `prompt`，`scenes` 为空。用户在动画制作点击“生成分镜”后才开始编排；仓库助手不会拆分镜。导入不超过 120 秒，创作输入不超过 16,000 字符；超限不截断。目标应用仍限制最多 30 幕。
- 图文文案：前端没有制作入口，服务端同样拒绝创建剪映或动画交接。
- 两条路径都不自动启动生成、配音、导出或发布。真实媒体在目标应用补充。目标应用不可用时保留源稿和交接记录。

## 验证

```powershell
backend\venv\Scripts\python.exe -m pytest -c backend/pytest.ini backend/app_center/repo_explainer/backend/tests -q
npm.cmd exec --prefix frontend -- vitest run src/services/__tests__/repoRequests.test.ts src/pages/Apps/__tests__/repoHandoff.test.tsx src/layouts/__tests__/repoExplainerLayout.test.ts
```

新增工作流回归：`repoProgress.test.tsx`、`repoCopywriting.test.tsx`、`applicationIcon.test.tsx`，覆盖实时事件/轮询、历史回放、类型分流、保存冲突与固定版本交接。

真实模型验收需显式设置 `REPO_EXPLAINER_LIVE_TEST=1`，运行 `test_live_smoke.py`。它在测试数据库中分析本仓库的提示词大师源码，生成双格式内容并验证两条交接 API；不会启动视频生成或在生产数据中创建测试项目。

普通测试使用模拟模型与网络，覆盖导入、权限、证据、取消、版本、冲突和制作交接。CSS/路由检查覆盖 full-bleed 的 `app-scroll-page` 滚动契约、767px 单列和短视口。遵守项目禁止 Codex 内置浏览器的要求；这些检查不等同于手机真实布局、触摸滚动、剪映播放或动画视觉验收。

2026-10-10 验收：后端 22 项回归、前端相关 41 项回归、类型检查、针对性 lint、Django 检查、Swagger 生成与生产构建通过。真实模型使用提示词大师当前源码完成一例功能解读、视频/图文生成及两种草稿交接 API 验收。此前长报告曾触发模型超时，压缩输出后通过；单次成功不代表所有仓库的耗时保证。未执行浏览器、手机真机或视频播放验收。
