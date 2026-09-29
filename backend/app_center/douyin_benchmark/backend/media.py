import ipaddress
import json
import os
import socket
import subprocess
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urljoin
import requests
from django.conf import settings

MAX_BYTES = 500 * 1024 * 1024
MAX_SECONDS = 600


def root():
    return Path(getattr(settings, "DOUYIN_MEDIA_ROOT", os.environ.get("DOUYIN_MEDIA_ROOT", str(Path(settings.BASE_DIR) / "private_media" / "douyin"))))


def path_for(key):
    path = (root() / key).resolve()
    if not path.is_relative_to(root().resolve()) or path == root().resolve():
        raise ValueError("素材路径无效。")
    return path


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


def checked_media_url(url):
    p = urlsplit(url)
    allowed = ("douyinvod.com", "douyin.com", "douyincdn.com", "bytecdn.cn", "ibytedtos.com", "byteimg.com")
    host = p.hostname or ""
    if p.scheme != "https" or p.username or p.password or p.port not in (None, 443) or not any(host == d or host.endswith("." + d) for d in allowed):
        raise ValueError("视频下载地址不在允许的平台域名中，请补传原视频。")
    if any(not ipaddress.ip_address(info[4][0]).is_global for info in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)):
        raise ValueError("视频下载地址无效。")
    return url


def download(url, key, check, *, headers=None):
    path = path_for(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.trust_env = False
    try:
        for _ in range(5):
            check()
            checked_media_url(url)
            with session.get(url, headers=headers or {"Referer": "https://www.douyin.com/"}, stream=True, timeout=(10, 30), allow_redirects=False) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers.get("Location", ""))
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
        raise ValueError("视频重定向次数过多，请补传原视频。")
    except Exception:
        path.unlink(missing_ok=True)
        raise
    finally:
        session.close()


def command(args, timeout=90):
    try:
        return subprocess.run(args, capture_output=True, check=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        raise ValueError("视频处理失败，请检查FFmpeg安装及视频文件。") from None


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
