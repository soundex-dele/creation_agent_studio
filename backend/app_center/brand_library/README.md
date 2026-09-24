# 品牌资料库

`brand-library` 是个人私有的独立应用。一份档案对应一个品牌或账号，包含账号定位、品牌语气、视觉规范，以及独立维护的产品和范文。名称必填，其余内容可以逐步完善。仅保存文本和来源链接，不抓取链接、上传素材或自动提取资料。

## 接口与权限

以下路径均位于 `/api/v1/organizations/{organization_id}` 下；单租户部署使用现有无组织前缀别名。

- `GET /brand-library/profiles`：供创作应用选择档案，仅返回当前用户可运行的品牌资料库应用内的私有档案。
- `GET/POST /applications/{application_id}/brand-library/profiles`
- `GET/PATCH/DELETE /applications/{application_id}/brand-library/profiles/{id}`
- `GET/POST .../profiles/{id}/products`、`GET/PATCH/DELETE .../products/{item_id}`
- `GET/POST .../profiles/{id}/examples`、`GET/PATCH/DELETE .../examples/{item_id}`

列表使用 `search` 和 `page`，每页 20 条。组织、所有者、应用和父档案由服务端设置；组织管理员也不能通过这些接口读取其他人的档案。PostgreSQL 迁移开启组织级 RLS，用户私有隔离由查询层强制执行。

## 创作引用

十个创作应用通过 `default_config.brand_reference` 声明 `enabled`、`default_modules` 和 `fields`（表单字段到资料字段的映射）。没有开启的应用不会出现引用入口。

现有 `POST /api/v1/apps/{slug}/compose-prompt/` 接收可选输入：

```json
{
  "prompt_id": "write-image-text-copy",
  "answers": {"source": "新品介绍"},
  "explicit_fields": ["audience"],
  "brand_reference": {
    "profile_id": "品牌档案 UUID",
    "modules": ["positioning", "voice", "products"],
    "product_ids": ["产品 UUID"],
    "example_ids": []
  }
}
```

模块可选 `positioning/products/voice/examples/visual`。产品和范文只引用明确选择的条目。字段有对应资料且未列入 `explicit_fields` 时继承品牌值；本次明确修改的要求优先。取消引用恢复原表单值。

返回值兼容原接口，引用时额外返回 `brand_reference` 摘要（档案、更新时间、模块、条目 ID、继承字段）。最终文本包含来源和边界说明；资料不改变应用原有职责或保留原文要求。引用总长度上限 24000 字，超过时明确报错、不截断。无资料、失效档案或非法条目不静默忽略。

预览后编辑选择会清除旧预览，进行中的旧请求结果也不会重新出现。发送后，资料文本随现有消息保存；更新或删除档案不会追溯修改历史消息。首版不改变自动工作流或智能体全局提示词。

## 安装与验证

在仓库根目录使用项目虚拟环境：

```powershell
backend\venv\Scripts\python.exe backend\manage.py validate_app_center
backend\venv\Scripts\python.exe backend\manage.py migrate brand_library --noinput
backend\venv\Scripts\python.exe backend\manage.py sync_app_center --package brand-library
```

同样同步这十个应用，以发布新的引用配置：`write-image-text-copy`、`write-short-video-copy`、`wechat-viral-article`、`wechat-viral-topics`、`html-cover-generator`、`article-html-illustrator`、`gzh-design`、`markdown-to-html`、`wechat-html-optimizer`、`html-to-paged-cards`。重启 Web 进程，使 Django 加载新应用及路由。

后端测试位于 `backend/tests`，覆盖资料权限和 CRUD、组合兼容性、引用约束、十个真实 manifest 及安装幂等。前端 `brandLibrary.test.tsx` 覆盖编辑、失败恢复、选择切换、预览失效和组织切换；使用 jsdom，不依赖浏览器。
