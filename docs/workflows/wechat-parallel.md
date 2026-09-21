# 公众号正文与封面并行工作流

在工作流列表选择「公众号图文并行预设」，会打开可编辑的图模式草稿。检查配置后创建工作流；运行时填写「选题与素材」。

```text
选题 → 公众号爆款写作
       ├─ 文章 HTML 配图 → 配图导出 PNG 并插入正文
       │                   → Markdown 转 HTML → HTML 分页图文 → 正文页导出 PNG
       └─ HTML 封面生成器 → 封面导出 PNG
```

两个分支仅共同依赖写作。图上的连线既声明执行依赖，也提供对应节点的输出字段选择；页面位置不改变执行顺序。封面默认 2.35:1，正文分页默认 3:4，完整加高页会保留全部内容。

## 文件交接

- 写作输出 `article/article.md`，只包含选定标题和正文。
- 配图输出 `illustrations/manifest.json` 和 HTML 文件。清单的 `files` 按顺序指定 HTML，路径相对于清单目录；`insertions` 为每张图指定 `file`、原稿中的唯一完整段落 `after`、说明文字 `alt`。
- 配图导出节点在全部 PNG 成功后按段落插图，输出原稿同目录的 `article-with-images.md`，保留原稿及其相对资源路径。缺图、缺锚点、重复锚点或重复配图均报错。
- 排版读取 `article/article-with-images.md`，输出同目录的 HTML。
- 分页按技能创建唯一输出目录；`pages/manifest.json` 只列出正文页，不包括预览索引。`pages/report.json` 必须为本次实际报告，状态为 `complete`。
- 封面输出 `cover/cover.html`，单独转换为 PNG。
- 最终结果 `article` 是已插图 Markdown 路径，`pages` 是正文 PNG 列表，`cover` 是封面 PNG 列表。

Agent 节点通过 `config.workflow_artifacts` 声明输出文件。执行器检查文件非空、位于本次工作目录，并在重跑时确认产物已经更新。下游使用 `output.artifacts.<字段名>`，不从聊天说明里猜测路径。

PNG 应用支持原有 `directories`、工作流 `manifest_file`、工作流单文件 `html_file` 三种输入。后两种路径须位于工作目录内。预设启用 `strict`：全部截图成功且 PNG 文件存在才继续。截图等待字体和图片加载，失败会阻断本节点。

## 部署

本次更新包含 HTML 转 PNG 应用 1.1.0 的输入定义，需要在目标组织同步已安装的应用版本。macOS/Linux 从仓库根目录执行（Windows 使用 `backend\venv\Scripts\python.exe`）：

```sh
backend/.venv/bin/python backend/manage.py validate_app_center
backend/.venv/bin/python backend/manage.py sync_app_center --package html-to-png --organization <组织ID>
```

其余应用需已安装：`wechat-viral-article`、`article-html-illustrator`、`markdown-to-html`、`html-to-paged-cards`、`html-cover-generator`。工作节点需要对应完整技能目录、Node.js、Bun/npx、Playwright 与 Chromium，以及可用的模型执行器。通过 `PLAYWRIGHT_NODE_MODULES` 指定包含 `playwright` 的目录。

不需要数据库迁移。更新后重启后端/执行 worker，并重新构建前端。测试使用模拟生成器/截图进程校验文件交接；真正生成效果仍需使用真实选题和执行环境验收。
