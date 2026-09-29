#!/usr/bin/env python3
"""直接导入 DTK v5 源码，获取抖音视频无水印地址；无需 API 服务。"""

import argparse
import asyncio
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

SOURCE = Path(__file__).resolve().parents[1] / "third_party/Douyin_TikTok_Download_API/src"
if sys.version_info < (3, 12) or sys.version_info >= (3, 14):
    raise SystemExit("DTK v5 需要 Python 3.12/3.13，请使用 backend/.venv-dtk/bin/python")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(SOURCE))
from core.douyin_media_urls import prioritize_video_urls
try:
    import httpx
    from dtk.core.errors import DtkError
    from dtk.core.logging import configure
    from dtk.core.types import BrowserFamily, Outcome, Platform
    from dtk.platforms.douyin.adapter import ADAPTER
    from dtk.platforms.douyin.endpoints import CONTENT_DETAIL
    from dtk.signing.base import RequestSpec as SigningRequest, SigningSession, StaticFingerprint
    from dtk.signing.native.signer import NativeSigner
    from dtk.signing.native.websign import pick_uifid
    from dtk.transport.base import Fingerprint, RequestSpec, TransportFailure, TransportIdentity
    from dtk.transport.wreq_transport import WreqTransport
    from dtk.urls import ResourceKind, require_content_id, resolve
except ImportError as exc:
    raise SystemExit("缺少源码或依赖，请按 douyin_video_url.md 安装独立运行环境") from exc


class VideoUrlError(RuntimeError):
    pass


def load_cookies(text):
    """Accept a Cookie header, a JSON mapping, or browser-exported cookie array."""
    text = text.strip()
    if not text:
        raise VideoUrlError("请提供 --cookie-file，或设置 DOUYIN_COOKIE（可以使用游客 Cookie）")
    try:
        if text.startswith(("{", "[")):
            value = json.loads(text)
            if isinstance(value, list):
                value = {item["name"]: item["value"] for item in value}
            if not isinstance(value, dict) or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in value.items()
            ):
                raise ValueError("invalid cookie mapping")
            cookies = value
        else:
            # Match dtk.identity.importing._parse_header: browser Cookie values
            # may contain raw JSON/quotes which make SimpleCookie silently drop
            # the entire header. Split only at semicolons and the first '=';
            # keep values byte-for-byte, including percent escapes and padding.
            text = re.sub(r"^cookie\s*:\s*", "", text, flags=re.IGNORECASE)
            cookies = {}
            for chunk in text.split(";"):
                name, separator, value = chunk.partition("=")
                name = name.strip()
                if separator and name:
                    if not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", name):
                        raise ValueError("invalid cookie name")
                    cookies[name] = value.strip()
    except (ValueError, KeyError, TypeError) as exc:
        raise VideoUrlError("Cookie 格式错误：使用 Cookie 请求头或 JSON 对象/数组") from exc
    if not cookies:
        raise VideoUrlError("未解析到 Cookie，请检查文件是否为完整 Cookie 请求头或 JSON 对象/数组")
    if not pick_uifid(cookies):
        raise VideoUrlError(f"已解析 {len(cookies)} 项 Cookie，但未找到有效的 UIFID / UIFID_TEMP；"
                            "无法生成完整签名，请检查抖音网页请求中的 Cookie")
    return cookies


def make_identity(cookies, user_agent, screen="1920x1080", language="zh-CN",
                  zone="Asia/Shanghai", proxy=None):
    match = re.search(r"(?:Chrome|Chromium)/(\d+)", user_agent)
    if not match or "Mobile" in user_agent:
        raise VideoUrlError("请提供取得 Cookie 时桌面 Chrome/Chromium 的 User-Agent")
    if not re.fullmatch(r"[1-9]\d{1,4}x[1-9]\d{1,4}", screen):
        raise VideoUrlError("screen 格式应为宽x高，例如 1920x1080")
    if "Windows" in user_agent:
        platform = "Win32"
    elif "Macintosh" in user_agent:
        platform = "MacIntel"
    elif "Linux" in user_agent:
        platform = "Linux x86_64"
    else:
        raise VideoUrlError("无法从 User-Agent 识别桌面操作系统")
    fingerprint = Fingerprint(
        browser_family=BrowserFamily.CHROME, browser_major=int(match[1]),
        user_agent=user_agent, platform=platform, screen=screen,
        language=language, timezone=zone,
    )
    return TransportIdentity(id="local-douyin", platform=Platform.DOUYIN,
                             fingerprint=fingerprint, cookies=cookies, proxy_url=proxy)


async def resolve_id(target, identity, timeout):
    target = target.strip()
    if target.isascii() and target.isdigit():
        return require_content_id(target, platform=Platform.DOUYIN)
    # The source validates every redirect hop. No login cookies go to short-link hosts.
    async with httpx.AsyncClient(
        headers={"User-Agent": identity.fingerprint.user_agent},
        timeout=timeout, follow_redirects=False, proxy=identity.proxy_url,
        trust_env=False,
    ) as client:
        async def redirect(url):
            # Once a redirect exposes the id, avoid fetching the video HTML page.
            from dtk.urls import identify
            kind = identify(url)
            if kind.resource_id and kind.resource is ResourceKind.VIDEO:
                return None
            async with client.stream("GET", url) as response:
                if 300 <= response.status_code < 400:
                    return response.headers.get("location")
                if response.status_code >= 400:
                    raise VideoUrlError(f"分享短链返回 HTTP {response.status_code}")
                return None
        kind = await resolve(target, redirect)
    if kind.platform is not Platform.DOUYIN or kind.resource is not ResourceKind.VIDEO:
        raise VideoUrlError("请输入抖音作品链接，而非用户主页或其他平台链接")
    return require_content_id(kind.resource_id or "", platform=Platform.DOUYIN)


async def fetch_video(content_id, identity, timeout=30, transport=None):
    """Reuse actual source builders, both signature layers, transport and parser."""
    spec = ADAPTER.build_request(CONTENT_DETAIL, aweme_id=content_id,
                                 profile=ADAPTER.profile_for(identity.fingerprint))
    signed = await NativeSigner(Platform.DOUYIN).sign(
        SigningRequest.get(spec["url"], spec["params"], spec["headers"]),
        StaticFingerprint.of(identity.fingerprint),
        SigningSession(cookies=identity.cookies, proxy_url=identity.proxy_url,
                       identity_id=identity.id),
    )
    own_transport = transport is None
    transport = transport if transport is not None else WreqTransport()
    try:
        response = await transport.request(identity, RequestSpec(
            # Signed query must reach the server unchanged, never re-encode it.
            url=signed.signed_url(spec["url"]),
            headers={**spec["headers"], **signed.headers}, endpoint=CONTENT_DETAIL,
        ), timeout=timeout)
        classification = transport.classify(response)
        if classification.outcome is not Outcome.OK:
            raise VideoUrlError(f"抖音请求失败：HTTP {response.status}，"
                                f"{classification.outcome.value} / {classification.rule}")
        payload = response.json_or_none()
        if not isinstance(payload, dict):
            raise VideoUrlError("抖音未返回 JSON，Cookie 可能失效或请求受到限制")
        content = ADAPTER.parse_content(payload, fetched_at=datetime.now(timezone.utc))
        return video_urls(content.model_dump(mode="json"))
    finally:
        if own_transport:
            await transport.close()


def video_urls(content):
    if content.get("kind") != "video":
        raise VideoUrlError("解析结果是图集，没有单个视频下载地址")
    media = content.get("media") or {}
    urls = []
    for stream in [media.get("video"), *(media.get("streams") or [])]:
        if not isinstance(stream, dict) or stream.get("watermark") is not False:
            continue
        for url in [stream.get("url"), *(stream.get("urls") or [])]:
            if (isinstance(url, str) and urlsplit(url).scheme in {"http", "https"}
                    and urlsplit(url).hostname and url not in urls):
                urls.append(url)
    urls = prioritize_video_urls(urls)
    if not urls:
        raise VideoUrlError("作品没有可用的无水印地址，可能已删除、私密或受限")
    return {"content_id": content.get("content_id"), "title": content.get("title"),
            "url": urls[0], "urls": urls, "referer": "https://www.douyin.com/"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", help="作品 ID、完整/短分享链接或分享文案")
    parser.add_argument("--cookie-file", type=Path, help="Cookie 请求头或 JSON 文件；否则读 DOUYIN_COOKIE")
    parser.add_argument("--user-agent", default=os.environ.get("DOUYIN_USER_AGENT", ""),
                        help="同一浏览器的 User-Agent，也可通过 DOUYIN_USER_AGENT 设置")
    parser.add_argument("--screen", default="1920x1080", help="浏览器屏幕尺寸，默认 1920x1080")
    parser.add_argument("--language", default="zh-CN")
    parser.add_argument("--timezone", default="Asia/Shanghai")
    parser.add_argument("--proxy", help="可选代理，使用取得 Cookie 时的网络出口")
    parser.add_argument("--timeout", type=float, default=30, help="整个解析过程超时秒数，默认 30")
    parser.add_argument("--json", action="store_true", help="输出包含备用地址的 JSON")
    args = parser.parse_args()
    # Keep stdout usable in a shell pipeline; suppress source-library routine logs.
    configure(level="critical")
    try:
        if not math.isfinite(args.timeout) or args.timeout <= 0:
            raise VideoUrlError("timeout 必须是有限正数")
        cookies = load_cookies(args.cookie_file.read_text(encoding="utf-8-sig")
                              if args.cookie_file else os.environ.get("DOUYIN_COOKIE", ""))
        identity = make_identity(cookies, args.user_agent, args.screen,
                                 args.language, args.timezone, args.proxy)
        async def run():
            async with asyncio.timeout(args.timeout):
                content_id = await resolve_id(args.target, identity, args.timeout)
                return await fetch_video(content_id, identity, args.timeout)
        result = asyncio.run(run())
    except TransportFailure:
        # The source exception embeds its signed URL; don't expose visitor tokens.
        print("错误：抖音请求未完成，请检查网络、代理和浏览器指纹配置", file=sys.stderr)
        return 1
    except DtkError as exc:
        print(f"错误：{exc.code.value}: {exc}", file=sys.stderr)
        return 1
    except TimeoutError:
        print("错误：请求超时", file=sys.stderr)
        return 1
    except (VideoUrlError, OSError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    except httpx.HTTPError:
        print("错误：分享链接请求失败，请检查网络", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else result["url"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
