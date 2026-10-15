# 选题探索

`topic-explorer` 是独立的多平台聊天应用。用户先填写想法或素材，可选平台、形式、主要目标、方向、读者与补充要求，然后预览并发送探索请求。

`provision.py` 按组织安装独立的 `topic-explorer-assistant`，不绑定写作 Skill，不修改共享内容创作智能体。需要补充信息或选择候选时，必须调用 `request_user_input` 提问工具，每轮 1—3 个关键问题，通过现有问题卡片收集选择或自由回答；收到工具返回的真实回答后继续。信息足够后提供三个不同切口，选中后在对话中交付选题说明和提纲。不自动回存或生成正文。

宣传助手的「探索选题」直接携带已确认素材和明确范围，所有交接字段均为字符串。未填写的范围保持空白；选择“暂不确定”和清空均可留待对话探索。资料链接未经读取不视为已核验。

## 安装与验证

在仓库根目录使用项目虚拟环境：

```powershell
.\backend\venv\Scripts\python.exe backend/manage.py migrate project_promotion
.\backend\venv\Scripts\python.exe backend/manage.py sync_app_center --package topic-explorer
.\backend\venv\Scripts\python.exe backend/manage.py sync_app_center --package project-promotion
.\backend\venv\Scripts\python.exe backend/manage.py validate_app_center
.\backend\venv\Scripts\python.exe -m pytest app_center/topic_explorer app_center/project_promotion/backend/tests
```

单元和集成测试验证表单契约、交接、迁移与安装，不代表模型行为评估。真实模型评估使用当前配置引擎，有实际模型调用：

```powershell
.\backend\venv\Scripts\python.exe backend/manage.py shell -c "from app_center.topic_explorer.evaluate import run; run()"
```

结果写入忽略目录 `artifacts/topic-explorer-evaluation.json`，含输入场景标识、验收要点及真实回复，需逐项人工评阅。引擎不可用时停止，不将未完成场景算通过。评估使用合成素材；不读取用户项目，也不验证浏览器渲染。

评估区分 `question_tool` 和普通文字，需提问的场景只有产生真实问题请求才算通过。可以继续验证同一模型回合的提问、提交模拟回答、候选选择和最终交付：

```powershell
.\backend\venv\Scripts\python.exe backend/manage.py shell -c "from app_center.topic_explorer.evaluate import run_interactive; run_interactive()"
```

该检查使用当前配置的 Codex 引擎原生 `requestUserInput` 协议和默认执行模式，不需要用户切换 Plan 模式；模拟回答仅用于评估，不进入用户会话。输出为 `artifacts/topic-explorer-interactive.json`。其他引擎未验证提问工具能力，不以纯文字代替成功的工具调用。

素材交接迁移保留历史选题和版本交接；已有素材交接时拒绝回退旧约束，避免丢失新数据。
