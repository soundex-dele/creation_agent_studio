"""Normalized DTK data and pagination, plus the legacy optional REST transport.

The application uses collector_config.LocalDTKClient for direct source calls.
"""

from core.observability import log_operation
import os
import re
import time
from urllib.parse import urlsplit, urlunsplit
import requests
from django.conf import settings
from core.douyin_media_urls import prioritize_video_urls, DOUYIN_MEDIA_DOMAINS


class CollectionError(Exception):
    def __init__(self, code="unavailable", diagnostic=None):
        self.code = code
        message = {"not_configured": "请先在采集设置中保存 User-Agent 和 Cookie。", "runtime": "DTK 独立运行环境未就绪，请按部署说明安装。", "credentials": "请检查同一桌面 Chrome 的 User-Agent 和 Cookie，Cookie 需包含有效 UIFID / UIFID_TEMP。", "auth": "抖音接口要求有效登录状态，请更新采集设置后重试。",
            "content_unavailable": "抖音返回作品或账号不可访问，可能已删除、私密或受限；不代表 Cookie 失效。",
            "signature": "DTK 请求签名生成失败或被抖音拒绝，请检查采集源码版本与浏览器指纹配置。",
            "challenge": "抖音返回了验证页面，请在原浏览器完成验证后重试，或补传原视频。",
            "empty_response": "抖音接口未返回作品数据；尚不能判断 Cookie 是否失效，可稍后重试或补传原视频。",
            "risk_control": "抖音拒绝了本次请求，请检查采集网络与浏览器配置，或补传原视频。",
            "limited": "采集服务限流，请稍后重试。", "pagination": "分页未继续推进，已保留获取到的作品。",
            "invalid": "采集接口返回的数据结构不兼容。", "timeout": "采集超时，请稍后重试。",
            "unavailable": "采集服务不可用，请检查服务和登录状态。"}.get(code, "采集失败，请检查服务状态。")
        diagnostic = diagnostic if isinstance(diagnostic, dict) else {}
        endpoint = {"douyin.content_detail": "视频详情", "douyin.author_profile": "账号资料", "douyin.author_posts": "作品列表"}.get(diagnostic.get("endpoint"))
        status = diagnostic.get("http_status")
        if endpoint and type(status) is int and 100 <= status <= 599:
            message += f"（{endpoint}，HTTP {status}）"
        super().__init__(message)


def source_url(text):
    match = re.search(r'https?://[^\s<>"\u3000]+', text)
    if not match:
        raise ValueError("请粘贴抖音账号主页链接或分享文本。")
    url = urlsplit(match.group().rstrip("，。；！、)）"))
    if url.scheme != "https" or url.username or url.password or url.port not in (None, 443):
        raise ValueError("仅支持 HTTPS 抖音链接。")
    if url.hostname == "www.douyin.com":
        if not re.fullmatch(r"/user/[A-Za-z0-9_.=-]+/?", url.path):
            raise ValueError("请使用账号主页链接。")
    elif url.hostname == "v.douyin.com":
        if not re.fullmatch(r"/[A-Za-z0-9_-]+/?", url.path):
            raise ValueError("分享链接无效。")
    else:
        raise ValueError("仅支持 www.douyin.com 或 v.douyin.com 链接。")
    return urlunsplit(("https", url.hostname, url.path.rstrip("/") + "/", "", ""))


def public_image(url):
    try:
        parsed = urlsplit(url or "")
        host = parsed.hostname or ""
        if parsed.scheme == "https" and not parsed.username and any(host == d or host.endswith("." + d) for d in
                ("douyinpic.com", "byteimg.com", "ibytedtos.com", "pstatp.com", "douyincdn.com")):
            return url
    except ValueError:
        pass
    return ""


def platform_media_url(url):
    if not isinstance(url, str):
        return ""
    try:
        parsed = urlsplit(url or "")
        host = (parsed.hostname or "").rstrip(".")
        if (parsed.scheme in ("http", "https") and parsed.username is None and parsed.password is None
                and parsed.port in (None, 443 if parsed.scheme == "https" else 80)
                and any(host == domain or host.endswith("." + domain) for domain in DOUYIN_MEDIA_DOMAINS)):
            return url
    except (ValueError, TypeError):
        pass
    return ""


def ordered_media_urls(urls):
    return prioritize_video_urls(url for url in urls if platform_media_url(url))


def video_urls(content):
    """DTK's media streams are file URLs; web_url is never a download source."""
    if content.get("kind") != "video":
        return []
    media = content.get("media") or {}
    result = []
    for stream in [media.get("video"), *(media.get("streams") or [])]:
        if not isinstance(stream, dict) or stream.get("watermark") is not False:
            continue
        for url in [stream.get("url"), *(stream.get("urls") or [])]:
            if platform_media_url(url) and url not in result:
                result.append(url)
    return ordered_media_urls(result)[:8]


def work_web_url(item):
    """Open a work in the web app, including for previously stored /video URLs."""
    content_id = str(item.get("content_id") or item.get("platform_id") or "")
    if not content_id.isascii() or not content_id.isdigit():
        return ""
    # DTK synthesizes /video and /note links; those detail routes can report an
    # unavailable work even when the API still returns it as public. The web
    # app's modal entry supports both videos and image albums.
    return f"https://www.douyin.com/?modal_id={content_id}"


def normalize_work(item):
    if not isinstance(item, dict) or item.get("platform") != "douyin" or not str(item.get("content_id") or "").isdigit():
        raise CollectionError("invalid")
    stats = item.get("stats") or {}
    counts = {name: (stats.get(key) if type(stats.get(key)) is int and stats[key] >= 0 else None) for name, key in
        (("likes", "digg_count"), ("comments", "comment_count"), ("collects", "collect_count"), ("shares", "share_count"), ("plays", "play_count"))}
    covers = (item.get("media") or {}).get("covers") or []
    return {"platform_id": str(item["content_id"]), "title": str(item.get("title") or "")[:2000],
        "description": str(item.get("description") or "")[:10000], "published_at": item.get("created_at"),
        "duration": item["duration_ms"] / 1000 if isinstance(item.get("duration_ms"), (int, float)) else None,
        "kind": item.get("kind"), "url": work_web_url(item), "_media_urls": video_urls(item),
        "cover": public_image(covers[0].get("url")) if covers else "", **counts}


class DTKClient:
    def __init__(self, *, check=lambda: None):
        self.base = getattr(settings, "DOUYIN_DTK_URL", os.environ.get("DOUYIN_DTK_URL", "")).rstrip("/")
        self.key = getattr(settings, "DOUYIN_DTK_KEY", os.environ.get("DOUYIN_DTK_KEY", ""))
        self.check = check
        if not self.base or not self.key:
            raise CollectionError("not_configured")
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers["Authorization"] = f"Bearer {self.key}"

    @log_operation
    def request(self, method, path, **kwargs):
        self.check()
        try:
            response = self.session.request(method, self.base + path, timeout=(5, 35), allow_redirects=False, **kwargs)
            if response.status_code in (401, 403):
                raise CollectionError("auth")
            if response.status_code == 429:
                raise CollectionError("limited")
            response.raise_for_status()
            body = response.json()
        except requests.Timeout:
            raise CollectionError("timeout") from None
        except (requests.RequestException, ValueError):
            raise CollectionError() from None
        if not isinstance(body, dict) or body.get("success") is not True:
            code = str((body.get("error") or {}).get("code", "")) if isinstance(body, dict) else ""
            raise CollectionError("auth" if any(s in code for s in ("AUTH", "IDENTITY", "COOKIE")) else "limited" if "LIMIT" in code else "unavailable")
        return body.get("data")

    @log_operation
    def fetch(self, path, params):
        data = self.request("GET", path, params={**params, "wait": 0, "refresh": "true"})
        deadline = time.monotonic() + 180
        while isinstance(data, dict) and data.get("task_id"):
            self.check()
            if data.get("state") == "done":
                return data.get("data")
            if data.get("state") == "failed":
                code = str((data.get("error") or {}).get("code", ""))
                raise CollectionError("auth" if any(s in code for s in ("AUTH", "IDENTITY", "COOKIE")) else "unavailable")
            if time.monotonic() > deadline:
                raise CollectionError("timeout")
            time.sleep(1)
            data = self.request("GET", f'/api/v1/tasks/{data["task_id"]}')
        return data

    @log_operation
    def profile(self, url):
        value = self.fetch("/api/v1/douyin/user", {"url": url})
        if not isinstance(value, dict) or value.get("platform") != "douyin" or not value.get("uid"):
            raise CollectionError("invalid")
        return {"platform_id": str(value.get("sec_uid") or value["uid"]), "name": str(value.get("nickname") or "")[:200],
                "signature": str(value.get("signature") or "")[:2000], "stats": value.get("stats") or {}}

    def pages(self, platform_id, count):
        cursor, seen_cursors, seen_items = None, set(), set()
        for _ in range(20):
            self.check()
            params = {"sec_user_id": platform_id, "count": 20}
            if cursor:
                params["cursor"] = cursor
            page = self.fetch("/api/v1/douyin/user/posts", params)
            if not isinstance(page, dict) or not isinstance(page.get("items"), list):
                raise CollectionError("invalid")
            items = []
            for raw in page["items"]:
                item = normalize_work(raw)
                if item["platform_id"] not in seen_items:
                    seen_items.add(item["platform_id"])
                    items.append(item)
                    if len(seen_items) >= count:
                        break
            complete = len(seen_items) >= count or not page.get("has_more")
            yield items, complete
            if complete:
                return
            cursor = page.get("cursor")
            if not cursor or cursor in seen_cursors:
                raise CollectionError("pagination")
            seen_cursors.add(cursor)
            time.sleep(1)
        raise CollectionError("pagination")

    @log_operation
    def detail(self, platform_id):
        return self.fetch("/api/v1/douyin/video", {"aweme_id": platform_id})
