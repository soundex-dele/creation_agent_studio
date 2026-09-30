
from core.observability import log_operation
import ipaddress
import json
import os
import re
import socket
import subprocess
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urljoin
import requests
from django.conf import settings
from .provider import CollectionError, platform_media_url, video_urls, ordered_media_urls

MAX_BYTES = 500 * 1024 * 1024
MAX_SECONDS = 600


def root():
    return Path(getattr(settings, "DOUYIN_MEDIA_ROOT", os.environ.get("DOUYIN_MEDIA_ROOT", str(Path(settings.BASE_DIR) / "private_media" / "douyin"))))


def path_for(key):
    path = (root() / key).resolve()
    if not path.is_relative_to(root().resolve()) or path == root().resolve():
        raise ValueError("素材路径无效。")
    return path


@log_operation
def store_upload(upload):
    if not upload.size or upload.size > MAX_BYTES:
        raise ValueError("视频需大于0字节且不超过500 MB。")
    key = f"uploads/{uuid.uuid4()}/source.mp4"
    path = path_for(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        size = 0
        with path.open("wb") as dest:
            for chunk in upload.chunks():
                size += len(chunk)
                if size > MAX_BYTES:
                    raise ValueError("视频超过500 MB。")
                dest.write(chunk)
        probe(path)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return key


class MediaAddressError(ValueError):
    """A refused candidate may be skipped; its target must never be requested."""


def checked_media_url(url, *, redirected=False):
    label = "视频重定向地址" if redirected else "视频下载地址"
    try:
        p = urlsplit(url)
        host = p.hostname or ""
    except (TypeError, ValueError):
        raise MediaAddressError(f"{label}格式无效。") from None
    # Only expose a bounded hostname, never credentials, paths or signed queries.
    visible_host = host if re.fullmatch(r"[a-zA-Z0-9.:-]{1,253}", host) else "无法识别主机"
    if not platform_media_url(url):
        raise MediaAddressError(f"{label}被拦截（主机：{visible_host}；域名、协议、端口或凭据格式不受支持）。")
    port = 443 if p.scheme == "https" else 80
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        raise requests.ConnectionError("视频域名解析失败。") from None
    if not addresses or any(not ipaddress.ip_address(info[4][0]).is_global for info in addresses):
        raise MediaAddressError(f"{label}被拦截（主机：{visible_host}；解析结果包含非公共地址）。")
    return url


@log_operation
def download(url, key, check, *, headers=None):
    path = path_for(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.trust_env = False
    try:
        for hop in range(5):
            check()
            checked_media_url(url, redirected=hop > 0)
            with session.get(url, headers=headers or {"Referer": "https://www.douyin.com/"}, stream=True, timeout=(10, 30), allow_redirects=False) as response:
                if response.is_redirect:
                    try:
                        url = urljoin(url, response.headers.get("Location", ""))
                    except ValueError:
                        raise MediaAddressError("视频重定向地址格式无效。") from None
                    continue
                response.raise_for_status()
                if int(response.headers.get("Content-Length", "0")) > MAX_BYTES:
                    raise ValueError("视频超过500 MB，请选择更短的作品。")
                size = 0
                with path.open("wb") as dest:
                    for chunk in response.iter_content(128 * 1024):
                        check()
                        size += len(chunk)
                        if size > MAX_BYTES:
                            raise ValueError("视频超过500 MB。")
                        dest.write(chunk)
                return path
        raise MediaAddressError("视频重定向次数过多，请补传原视频。")
    except Exception:
        path.unlink(missing_ok=True)
        raise
    finally:
        session.close()


@log_operation
def download_video(cached_urls, client, platform_id, key, check):
    """Use the post-list media first; renew details only when missing or expired."""
    headers = client.media_headers()
    blocked = []
    def attempt(urls):
        for url in ordered_media_urls(urls)[:3]:
            check()
            if not platform_media_url(url):
                continue
            try:
                return download(url, key, check, headers=headers)
            except MediaAddressError as exc:
                blocked.append(exc)
                continue
            except requests.RequestException:
                # Never propagate signed URLs in requests' exception messages.
                continue
        return None
    path = attempt(cached_urls)
    if path is not None:
        return path
    try:
        detail = client.detail(platform_id)
    except CollectionError:
        if blocked:
            raise blocked[-1] from None
        raise
    if str(detail.get("content_id") or "") != str(platform_id):
        raise ValueError("详情接口返回的作品 ID 不匹配，请刷新作品后重试。")
    urls = video_urls(detail)
    if not urls:
        raise ValueError("DTK 未返回可用的视频文件地址；作品可能为图文、私密或已删除，可补传原视频。")
    path = attempt(urls)
    if path is None:
        if blocked:
            raise blocked[-1]
        raise ValueError("视频文件地址不可用，请刷新作品或补传原视频。")
    return path


@log_operation
def command(args, timeout=90):
    try:
        return subprocess.run(args, capture_output=True, check=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        raise ValueError("视频处理失败，请检查FFmpeg安装及视频文件。") from None


@log_operation
def probe(path):
    raw = command(["ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe", "-show_format", "-show_streams", "-of", "json", str(path)])
    try:
        info = json.loads(raw)
        duration = float(info["format"]["duration"])
        if not any(s.get("codec_type") == "video" for s in info["streams"]):
            raise ValueError()
        if not 0 < duration <= MAX_SECONDS:
            raise ValueError()
    except (KeyError, ValueError, TypeError):
        raise ValueError("请选择包含画面且时长不超过10分钟的视频。") from None
    return duration


def frame_times(duration):
    end = max(0, duration - min(.5, duration / 2))
    return sorted(set(round(min(end, t), 3) for t in [0, 1, 2, 3] + [duration * i / 12 for i in range(1, 13)]))[:16]


@log_operation
def extract(path, prefix, check):
    duration = probe(path)
    directory = path_for(prefix)
    directory.mkdir(parents=True, exist_ok=True)
    audio = directory / "audio.wav"
    check()
    command(["ffmpeg", "-v", "error", "-y", "-protocol_whitelist", "file,pipe", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000", str(audio)])
    frames = []
    for index, at in enumerate(frame_times(duration)):
        check()
        filename = f"frame-{index}.jpg"
        command(["ffmpeg", "-v", "error", "-y", "-protocol_whitelist", "file,pipe", "-ss", str(at), "-i", str(path), "-frames:v", "1", "-vf", "scale=640:-2", "-pix_fmt", "yuvj420p", str(directory / filename)])
        if not (directory / filename).is_file():
            continue
        frames.append({"id": f"f{index}", "time": at, "key": f"{prefix}/{filename}"})
    if not frames:
        raise ValueError("未提取到可用关键帧，请补传原视频。")
    return audio, frames, duration
