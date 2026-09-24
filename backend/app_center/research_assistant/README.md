# 资料研究助手

应用 ID / renderer / executor：`research-assistant`。Django label：`research_assistant`。

个人项目支持文字 PDF、DOCX（包括正文表格）、TXT、Markdown、粘贴文章，以及从有权限的在线文档、个人网盘导入。每份资料保留独立快照；原始文档后续修改、撤回共享或删除不会改变已导入副本。扫描 PDF、加密 PDF、旧版 DOC 和网页抓取不在首版范围内。

生成研究报告、观点对照或写作资料包；每次运行冻结目标、要求和资料版本。执行器逐批读取所有选中资料的片段、提取逐字证据，再进行目标检索和综合。综合阶段对每份资料使用有界证据预算，覆盖情况明确列出检查的片段和候选证据数量；不表示所有事实都已验证。结构或引用校验失败会重试一次，仍失败则不发布成果。事实、推断及摘录必须带有效证据，观点对照逐份展示观点或未涉及。

出处保存资料版本、分块 ID、页码／章节／段落位置及逐字摘录。页面直接按结构化数据渲染，原文和模型文本不执行 HTML。Markdown 和在线文档从同一结构生成，保留引用及带权限的回溯链接。网盘导出使用已有配额和上传服务；在线文档导出创建新的私人文档，可以再使用文档应用的分享功能。分享成果不会授予研究项目访问权限。

## 配置与执行

复用组织的模型提供方（OpenAI-compatible chat/completions）和现有 durable worker。应用部署的 `config_override` 可设置 `answer_provider`、`answer_model`；未设置时使用组织默认路由模型。每次模型请求都执行成员用量检查并记录实际 usage，不需要额外 Agent 或 Skill 部署。

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `RESEARCH_MAX_SOURCES` | 20 | 项目有效资料数，移出资料仍保留供历史引用 |
| `RESEARCH_MAX_FILE_BYTES` | 52428800 | 单文件 50 MiB |
| `RESEARCH_MAX_TEXT_BYTES` | 2097152 | 粘贴文本 2 MiB |
| `RESEARCH_EMBEDDING_PROVIDER` | 空 | 新项目使用的组织向量提供方名称 |
| `RESEARCH_EMBEDDING_MODEL` | 空 | 新项目使用的向量模型；为空时关键词检索 |
| `RESEARCH_PUBLIC_URL` | 空 | 导出文件中的前端回溯地址，生产建议设置，例如 `https://studio.example.com` |

向量维度沿用 `KNOWLEDGE_EMBEDDING_DIMENSIONS`。向量服务暂不可用时检索降级为关键词。资料存储计入现有组织知识库容量；网盘导出另计网盘容量。

未设置公开地址时，回溯链接优先使用与允许主机／CORS 配置相符的浏览器 Origin 或 Referer，支持开发环境前后端端口不同的场景；最后回退到请求站点地址。

内部知识库 `scope=research` 不通过组织知识库 CRUD、检索或下载入口公开。项目、生成 Run、索引 Run、事件和下载均要求有效组织成员、研究应用权限和项目所有者身份；管理员不会因组织角色而获得其他人的研究资料。

删除项目立即禁止访问、取消运行、停用索引，随后清理原文件和分块。失败的清理保留 `cleanup_pending`，部署时安排定期执行 `cleanup_research_projects`；命令失败返回非零状态供监控告警。审计 Run 保留但不可通过项目访问。已导出的独立文件不随项目删除，其回溯链接将不可用。

## 部署与验证

从仓库根目录运行：

```powershell
backend\venv\Scripts\python.exe backend/manage.py validate_app_center
backend\venv\Scripts\python.exe backend/manage.py migrate --noinput
backend\venv\Scripts\python.exe backend/manage.py sync_app_center --package research-assistant
backend\venv\Scripts\python.exe backend/manage.py cleanup_research_projects
```

重启 web、knowledge worker 和 media worker，使它们加载新的模型与 executor 注册。随后发布前端生产构建。迁移前备份数据库及对象存储。首次部署新增知识库 scope 字段，既有记录默认是 `organization`，不改变其检索范围。

```powershell
backend\venv\Scripts\python.exe -m pytest backend/app_center/research_assistant/backend/tests backend/apps/knowledge/tests backend/app_center/documents/backend/tests backend/app_center/my_drive/backend/tests
cd frontend
npm run test -- src/pages/Apps/__tests__/researchAssistant.test.tsx src/lib/__tests__/applicationCatalog.test.ts
npm run lint
npm run build
```

模型测试使用确定性替身验证证据、异常和覆盖路径；不依赖实际付费模型。验证遵守项目规定，不使用 Codex 内置浏览器。

## API

前缀 `/api/v1/organizations/{organization_id}/applications/{application_id}/research-assistant`；单租户模式同时支持省略组织段的路径。契约包含在 `contracts/openapi.json`，前端应用类型位于 `frontend/src/services/researchAssistant.ts`。

- `/projects`：分页、搜索、创建；`/projects/{id}`：读取、编辑、删除。
- `/integrations`：当前有权限的联动应用及上传限制；`/imports`：按应用、目录和搜索条件分页选择资料。
- `/projects/{id}/sources`：资料列表；POST 接收单个 multipart 文件、JSON 文本或来源引用。前端将批量文件逐项上传以隔离失败。重复资料返回原 ID 和 `reused=true`。
- `/sources/{source_id}`：移出；`/retry`：重试失败索引；`/content`：下载不可变原件。
- `/projects/{id}/results`：分页历史、创建生成；POST 必须携带 `Idempotency-Key`，同键不同要求返回 409。
- `/results/{result_id}`：状态及已成功发布的结构化输出；`/cancel`：取消；`/citations/{citation_id}`：带上下文的出处。
- `/results/{result_id}/download`：Markdown；`/export`：保存在线文档或网盘，必须携带 `Idempotency-Key`。网盘支持可选 `parent`，工作台默认保存根目录。

导入、移出和生成通过项目行锁串行验证。运行阶段始终使用冻结的资料版本；再次生成创建新的历史记录，失败任务不覆盖成功成果。
