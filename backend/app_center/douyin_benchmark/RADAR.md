# 全站选题雷达

入口：抖音对标助手 → 选题雷达（`?view=radar`）。现有对标研究中的样本雷达保持原有行为。

1. 手动刷新抖音热榜，或输入一个行业关键词搜索作品。只读取真实上游结果，最多50条、搜索最多5页；不会自动添加账号或调用模型。
2. 选取一次采集中的1–20条资料，可选关联“我的账号”。关联账号需要已有定位；有启用的定位版本时使用该版本，否则使用已保存档案。
3. 生成3个选题建议，核对来源后保存到选题库，再进入创作中心。建议保留来源任务、链接及采集时间。

热榜热度保持上游原始数值，作品互动量只表示搜索样本。缺失指标与零值分开展示，不推算播放量、增长趋势或爆款概率。分页失败保留已取得数据并明确标记；取消的任务可以查看已取得资料，需要重新扫描后才能分析。

## 接口与存储

复用应用级 `POST /tasks` 和字符串 `Idempotency-Key`：

- `{"kind":"radar_hotlist"}`
- `{"kind":"radar_search","keyword":"科普"}`（关键词1–100字）
- `{"kind":"radar_topics","source_task_id":"UUID","source_ids":["hot:来源标识"],"target_account_id":"可选账号UUID"}`

任务列表支持 `kind=radar_hotlist,radar_search,radar_topics`，通用研究历史使用 `exclude_kind` 排除这些类型。输出新增 `radar_items`、`radar_request`（安全的重试参数）、可选 `radar_profile` 与现有 `topics`。来源、定位和生成建议均按组织、应用、用户隔离。复用 Task JSON 快照，无雷达数据库迁移。

应用自有 `radar_source.py` 扩展 DTK 热榜、视频搜索请求及解析；凭据继续通过子进程 stdin 传递，不进入快照、模型或错误信息。搜索可能要求比热榜更严格的登录状态；上游明确要求登录时提示更新采集配置，不绕过验证或回退模拟数据。

## 验证

Windows 后端命令从 `backend` 运行，使用项目虚拟环境及 UTF-8：

```powershell
.\venv\Scripts\python.exe -X utf8 -m pytest app_center/douyin_benchmark/backend/tests/test_radar.py app_center/douyin_benchmark/backend/tests/test_research.py app_center/douyin_benchmark/backend/tests/test_collector_config.py -q
.\venv\Scripts\python.exe -X utf8 manage.py probe_douyin_radar --application <应用ID> --keyword 科普
```

第二条命令只读取热榜和一页搜索结果，不写入应用数据、不调用模型，输出脱敏状态和最多两条来源链接。仅两项均返回实际条目时验收通过；可用 Cookie 和当前网络是前提。

前端使用 `topicRadar.test.tsx` 和 `topicRadarLayout.test.ts`，并回归 `douyinResearch`、`douyinLayout`、`douyinRequests`。布局检查属于静态检查，HTTP 兼容属于模拟检查，不代表浏览器或真实手机视觉验收。
