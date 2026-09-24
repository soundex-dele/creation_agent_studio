# 会议与访谈助手

应用 ID / renderer：`meeting-assistant`；Django app label：`meeting_assistant`。

个人录音工作台。上传后通过持久化 media Run 自动转录、分析，生成时间分段逐字稿、
主题摘要、决策与候选行动项。访谈另有观点、原话、事实和文章提纲。
候选行动项默认不选中，必须通过确认接口才能创建本人的待办。
文档导出为独立的在线文档；分享文档不会共享录音。

## 安装与运行

从仓库根目录，使用项目虚拟环境：

```powershell
backend\venv\Scripts\python.exe backend/manage.py validate_app_center
backend\venv\Scripts\python.exe backend/manage.py migrate meeting_assistant --noinput
backend\venv\Scripts\python.exe backend/manage.py sync_app_center --package meeting-assistant
```

需要目标组织已安装 `documents`、`ideas-todos`，且用户有运行权限，才能使用对应导出按钮。
缺少目标应用不会影响录音、逐字稿或分析结果保存。
安装后重启 web 和 media execution worker，并重建 frontend。
worker 须加载新应用清单，且允许 `meeting-assistant` executor；沿用平台的执行服务配置。

- `MEETING_AUDIO_ROOT`：默认 `MEDIA_ROOT` 的同级目录 `meeting-audio`。
  标准 Docker 配置下为 `/data/meeting-audio`，使用现有共享 `runtime_data` 卷。
  自定义部署必须让 web 和 worker 挂载同一路径。此目录不得作为公开静态资源。
- `CREATION_TOOLBOX_WHISPER_MODEL`：沿用共享转录引擎配置，默认 `tiny`，CPU/int8。
  需要更高中文转录质量时可配置较大模型。worker 需能读取已缓存的模型，首次下载需要网络。
- 音频解码使用现有 `faster-whisper` / PyAV 依赖；支持 MP3/WAV/M4A/AAC/FLAC/OGG，
  上限 200 MiB、两小时。浏览器不支持的编码可转换为 MP3 后重新上传。
- AI 分析使用现有组织模型路由和 `AGENT_ENGINE_ADAPTER`；模型服务不可用时保留逐字稿，
  可单独重试分析。不会调用旧 `batch-transcribe` 应用。
- 现有 Nginx `/api/` 上限为 1024 MiB，已能容纳带 multipart 开销的 200 MiB 录音；
  自定义代理须允许至少 201 MiB 请求以及足够的上传/校验超时。

每小时运行以下维护命令，清理崩溃或 Windows 文件占用留下的孤立音频（只清理一小时前的无记录文件）：

```powershell
backend\venv\Scripts\python.exe backend/manage.py maintain_meeting_audio
```

备份数据库和私有音频目录。任务状态与阶段支持刷新后恢复；worker 异常由现有租约回收机制标记失败，
用户可重试。观察 media worker 日志、任务失败和私有目录磁盘使用量。

## 数据与接口

前缀：`/api/v1/organizations/{organization_id}/applications/{application_id}/meeting-assistant`。
单租户部署自动提供现有的无 organization 别名。

- `GET/POST /records`：20 条分页；支持 `page`、`search`、`kind`；创建使用 multipart，字段
  `audio`、`title`、`kind=meeting|interview`、`recorded_on`、`language=zh|en|auto`。
- `GET/PATCH/DELETE /records/{id}`：私有详情、元数据修改和删除。
- `PATCH /records/{id}/transcript`：`version` 与 `{id,text}` 分段编辑列表；不允许改时间戳或原文。
- `POST /records/{id}/runs`：`version`、`operation=process|analyze`，携带 `Idempotency-Key`。
- `POST /records/{id}/cancel`：取消当前任务。
- `POST /records/{id}/access`：一小时有效播放 token；`GET/HEAD /content?token=…` 支持单区间 Range。
  每次读取重新检查所有者成员资格、应用权限和记录存在性。
- `PATCH /records/{id}/actions/{action_id}`：携带记录 `version` 和候选项 `revision` 编辑候选标题、描述、优先级、日期。
- `POST /records/{id}/confirm-actions`：`version`、`confirmed=true`、`action_ids`、`action_versions`（ID 到 revision 的映射）；
  事务内检查用户实际核对的候选内容并创建待办，其他标签页修改过的候选须重新确认。
- `POST /records/{id}/documents`：`version`、`kind=transcript|minutes|materials` 与 `Idempotency-Key`。

运行期间禁止校对和编辑候选项。校对、类型或日期修改增加版本号，过期分析不能确认或导出。
转录分段保留稳定 ID、起止秒数和原文；模型只引用分段 ID，时间由服务端源数据决定。
长录音按最多约 12000 字符分块，分析后按原顺序合并，合并相同观点的来源，不静默截断。
结构或引用错误允许模型修正一次，仍无效则明确失败。
再次分析不会修改已经独立导出的文档/待办；相同标题且来源重叠的已确认行动项保留确认状态。
删除记录会取消任务并删除私有音频，已生成文档/待办保留。Run 审计仍保留但不存放转录正文；
录音删除或权限撤回后不能访问其 Run 详情。

## 验证

```powershell
cd backend
.\venv\Scripts\python.exe -m pytest app_center/meeting_assistant/backend/tests app_center/documents/backend/tests app_center/ideas_todos/backend/tests
cd ..\frontend
npm run test -- src/pages/Apps/__tests__/meetingAssistant.test.tsx src/pages/Apps/__tests__/documents.test.ts src/lib/__tests__/applicationCatalog.test.ts
npm run lint
npm run build
```

自动测试替代真实模型调用，验证权限、状态恢复、租约/版本隔离、引用、导出和确认流程。
实际转录质量和摘要质量需要部署配置完成后的真实录音验收。验证不使用 Codex 内置浏览器。
