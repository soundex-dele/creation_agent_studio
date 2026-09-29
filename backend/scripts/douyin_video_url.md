# 直接引用 DTK v5 源码获取抖音视频地址

脚本从本地 `backend/third_party/Douyin_TikTok_Download_API/src` 导入源码：

```text
抖音链接或作品 ID
  → dtk.urls.resolve / require_content_id
  → DouyinAdapter 构造作品详情请求
  → NativeSigner 生成 a_bogus 和 x-secsdk-web-signature
  → WreqTransport 携带 Cookie 和匹配的浏览器指纹直接请求抖音
  → DouyinAdapter.parse_content 提取无水印视频地址
```

无需 DTK API Key、API 服务、Worker、数据库、Redis 或 Go 下载器。
这已替换此前通过 HTTP 调用 DTK 服务的版本。

## 环境

v5 源码要求 Python 3.12/3.13；主项目的 Python 3.11 环境不能直接导入。
从仓库根目录建立独立环境（本机已完成）：

```bash
git submodule update --init backend/third_party/Douyin_TikTok_Download_API
uv venv --python 3.13 backend/.venv-dtk
uv pip install --python backend/.venv-dtk/bin/python -r backend/scripts/douyin_video_url.requirements.txt
```

DTK 以 Git submodule 引入，固定到主仓库记录的提交。克隆主仓库时也可使用
`git clone --recurse-submodules` 一并拉取。不要直接更新到上游最新提交而跳过兼容性验证。

Windows 对应解释器是 `backend\.venv-dtk\Scripts\python.exe`。

## Cookie 与浏览器信息

独立脚本不启动 v5 的浏览器身份生成服务，需要自行提供有效 Cookie。
可以来自未登录的游客浏览器，不要求登录账号；必须具有可用的 UIFID Cookie，
以便源码生成作品详情接口所需签名。仅有 `ttwid` 不足以满足这一条件。
Cookie 中存在 UIFID 也不代表它一定有效，实际结果由抖音返回决定。

将你自己浏览器中抖音请求的 Cookie 存到仓库外的本地文件，例如
`/tmp/douyin-cookie.txt`。支持以下三种内容：

- 完整 Cookie 请求头的值：`名称=值; 名称=值`，也接受 `Cookie:` 前缀。
- JSON 对象：`{"名称":"值"}`。
- 浏览器导出的 JSON 数组：`[{"name":"名称","value":"值"}]`。

复制同一浏览器请求的完整 User-Agent，通过 `DOUYIN_USER_AGENT` 或
`--user-agent` 提供。当前脚本支持桌面 Chrome/Chromium。
`--screen`、`--language`、`--timezone` 应与该浏览器一致，默认分别为
`1920x1080`、`zh-CN`、`Asia/Shanghai`。
Cookie 文件不要提交进仓库，也不要把登录 Cookie 分享给他人。

## 使用

从仓库根目录运行：

```bash
export DOUYIN_USER_AGENT='替换为取得Cookie时浏览器的完整User-Agent'

backend/.venv-dtk/bin/python backend/scripts/douyin_video_url.py \
  'https://v.douyin.com/替换为真实短链/' \
  --cookie-file /tmp/douyin-cookie.txt --json

backend/.venv-dtk/bin/python backend/scripts/douyin_video_url.py \
  '替换为纯数字作品ID' \
  --cookie-file /tmp/douyin-cookie.txt
```

也接受包含分享链接的整段文案。未指定 `--cookie-file` 时读取 `DOUYIN_COOKIE`。
可用 `--proxy` 指定取得 Cookie 时使用的代理出口。
`--timeout` 设置整个过程的超时秒数，默认 30。没有缓存，每次执行直接请求抖音。

默认标准输出只有一个无水印视频 URL。`--json` 输出 `content_id`、`title`、
首选地址 `url`、去重后的备用地址 `urls` 和 `referer`。
按平台返回顺序选择明确标记为无水印的流，不保证最高码率，不回退到带水印流。
脚本只获取地址，不下载视频，也不验证 CDN 地址是否仍可访问；地址过期后需要重新解析。

遇到风控、空响应、图集或没有视频地址时返回错误，不自动反复重试。
源码中的签名与请求指纹也可能随抖音变化而失效。

## 离线验证

测试使用工程自带的合成响应样本，执行真实源码的签名、传输适配、响应分类和解析逻辑，
只替换最底层 HTTP 客户端；短链跳转通过模拟响应验证。不会请求抖音，也不会读取真实 Cookie。

```bash
backend/.venv-dtk/bin/python -m unittest discover -s backend/scripts -p 'test_douyin_video_url.py' -v
```

## 媒体候选顺序

默认 `url` 和 `urls` 中优先选择 DTK 返回的 `v11*.douyinvod.com` 地址（当前部署实测可播放），同组保持原顺序；无 v11 时保留原来的首选地址。其他 CDN 仍作为备用。只重排完整候选，不替换域名、不重编码签名参数。该规则与抖音对标助手页面和下载共用。
