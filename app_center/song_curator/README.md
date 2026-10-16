# 歌曲推荐官

应用 ID / renderer / executor：`song-curator`；入口 `/applications/{id}/song-curator`。

截图上传（支持粘贴）→ AI 识别 → 原图对照、修改、去重 → 确认保存。识别不直接写入歌单；模糊歌手保留空值。也支持逐首录入或按行粘贴 `歌名 — 歌手`。每批最多 5 张静态 PNG/JPEG/WebP、单张 20 MB；每个用户在当前应用最多保留 500 MB 图片、20 张未提交图片、50 张歌单，每张 500 首。

推荐支持整张／部分歌单及流派、场景、心情、年代、语言、探索程度。超过 50 首的种子全部按 50 首分批分析；进度与结果中的 processedSeeds 反映处理数。默认每次最多 10 首，生成最多 30 个候选后排除种子、最近 10 次可见成功推荐和不感兴趣的歌曲；听过的歌曲默认排除，可在偏好中关闭。喜欢反馈最近 50 条进入模型上下文；全部排除反馈在服务端执行。反馈最多 2000 条，可逐条撤销。种子、反馈和偏好在任务提交时冻结。

**JSON 文件导入**：页头「导入 JSON 歌单」支持 Playlist Out 导出的 `{name, tracks:[{title,artist,album,version?}]}`，也支持直接的歌曲数组。可选择 `.json` 或包含 JSON 内容的 `.txt` 文件，UTF-8（兼容 BOM），最大 5 MB、500 首。文件在浏览器本地解析，不调用 AI、不上传原文件；自动填入歌单名称，进入现有核对编辑器后可去重、新建或追加歌单。部分导出或数量不一致会提示，缺失歌名、无效字段和超限整批报错，不静默丢弃歌曲。只导入歌曲文字信息，不采用外部 ID、链接、VIP／可播放标记或核验状态。

每条理由均为 AI 判断，并非实际音频分析。iTunes Search API 仅验证歌曲元数据，不保证网易云／QQ 上架或可播放。英文优先 US，中文／日韩优先 HK，其余根据歌曲文字判断；未匹配则查询另一目录。对歌名、歌手、专辑（提供时）、版本严格匹配，不确定的简繁体／别名不猜测，可能显示待核验。区分 verified / ambiguous / not_found / unavailable；Live、重混、伴奏等与原曲分开。来源链接只接受 Apple 官方 HTTPS 域名。音乐平台跳转使用固定搜索地址，不提供音源、内置播放、账号同步或歌词下载。

## 数据与执行

歌单、反馈、图片、任务按组织／应用／用户隔离，组织管理员不自动获得其他用户资料。`generate_json` 复用平台模型、额度与用量记录；当前图片输入需要支持图片的 Codex 系统适配器。失败提供手动录入入口。每个任务不自动重试付费模型调用；长歌单会有多次分批分析调用。应用写入结果前检查当前 attempt、有效租约、取消状态和应用权限。

目录限流采用数据库 CAS 的全局 3.1 秒间隔，适配本地多进程及共享数据库部署。该公共节流表仅存服务名和时间戳，不存用户信息，故不启用租户 RLS。网络连接／读取超时分别 4／8 秒、禁止重定向、响应限制 1 MiB；正结果缓存 24 小时，空结果 10 分钟。缓存使用平台配置，本地进程缓存、集群可用 Redis；缓存未命中仍受全局数据库限流。服务不可用时保留推荐结果并标注，不假报核验成功。

## API

前缀 `/api/v1/organizations/{organization_id}/applications/{application_id}/song-curator`：

- `GET /state`：`{revision,preferences,feedback,playlists}`。
- `PATCH /state`：原子操作 `{revision,requestKey,action,...}`；action 为 create/rename/delete/add/remove/confirm/feedback/preferences。目标使用 playlistId，歌曲使用 tracks 或 trackIds；confirm 额外使用 taskId，仅成功且未导入的识别任务可确认。
- `POST /images`：multipart file，`Idempotency-Key` 请求头；`GET /images/{id}` 鉴权原图；`DELETE /images/{id}` 移除未提交图片。
- `POST /tasks`：`{revision,requestKey,kind:import|similar|conditions,imageIds?,playlistId?,trackIds?,filters?}`，同载荷重放返回原任务、改载荷复用键返回 409。
- `GET /tasks?page=N`：每页 20 条；`GET /tasks/{id}`、`POST /tasks/{id}/cancel`、`DELETE /tasks/{id}`。
- `GET /playlists/{id}/export?fileType=txt|csv`；CSV 防公式注入。不要使用 DRF 保留的 `format` 参数。

所有业务写入按 library revision 检测冲突；相同请求键／载荷在 revision 检查前重放。前端网络失败保留请求键，成功或载荷改变后换键，复用平台 HTTP 兼容辅助函数。刷新或关闭页面后已提交后台任务仍保留，可在历史中打开；未保存的核对编辑是页面草稿，应确认后再离开。

删除任务立即禁止访问并取消运行，然后删除所属原图。文件删除失败保留记录供清理命令重试，不删除已保存歌单。部署维护时运行 `cleanup_song_images`，它也清理超过 24 小时未提交的上传。

## 部署与检查

从仓库根目录，使用项目虚拟环境：

```powershell
backend\venv\Scripts\python.exe -X utf8 backend/manage.py validate_app_center
backend\venv\Scripts\python.exe -X utf8 backend/manage.py migrate song_curator --noinput
backend\venv\Scripts\python.exe -X utf8 backend/manage.py sync_app_center --package song-curator
backend\venv\Scripts\python.exe -X utf8 backend/manage.py cleanup_song_images
backend\venv\Scripts\python.exe -X utf8 -m pytest app_center/song_curator/backend/tests -q
```

重新启动前后端及现有 media/all worker；不要同时再启动第二个本地 SQLite 数据服务。首次安装需要应用清单被前后端重新发现。

```powershell
cd frontend
npx vitest run ../app_center/song_curator/frontend/pages/__tests__/songCurator.test.tsx src/layouts/__tests__/songCuratorLayout.test.ts src/layouts/__tests__/mobileScrolling.test.ts src/lib/__tests__/applicationCatalog.test.ts
npx eslint "../app_center/song_curator/frontend/**/*.{ts,tsx}" src/layouts/__tests__/songCuratorLayout.test.ts --config .eslintrc.cjs --resolve-plugins-relative-to . --max-warnings 0
npm run build
```

测试使用模拟模型／目录响应，并覆盖真实平台 Run 提交与租约检查。手机 HTTP 兼容性通过缺失／抛错 randomUUID 及无 crypto 的模拟流程验证；页面继承父容器高度，由 app-scroll-page 滚动，静态 CSS 检查包含入口模式、手机宽度和短横屏。以上不等于真实模型识别效果、浏览器视觉或真机触摸验收。不使用 Codex 应用内浏览器。
