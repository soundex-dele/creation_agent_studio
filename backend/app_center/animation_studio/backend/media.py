import json
import math
import subprocess
import tempfile
from pathlib import Path

from rest_framework.exceptions import ValidationError
from app_center.ai_drawing.backend.images import inspect_image


def probe(path):
    try:
        result = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                                capture_output=True, timeout=30, check=True)
        return json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise ValidationError("无法读取媒体，请检查文件及执行主机 ffprobe 配置。") from exc


def inspect_upload(upload, *, allow_short=False):
    if upload.size > 50 * 1024 * 1024:
        raise ValidationError("录音不能超过 50 MB；图片不能超过 20 MB。")
    content = upload.read(50 * 1024 * 1024 + 1)
    if len(content) > 50 * 1024 * 1024:
        raise ValidationError("文件超过大小限制。")
    extension = Path(upload.name).suffix.lower()
    if extension in (".png", ".jpg", ".jpeg", ".webp"):
        if len(content) > 20 * 1024 * 1024:
            raise ValidationError("图片不能超过 20 MB。")
        info = inspect_image(content)
        return content, {"mime_type": info["mime_type"], "duration": None}
    if extension not in (".mp3", ".wav", ".m4a"):
        raise ValidationError("请选择 PNG/JPEG/WebP 图片或 MP3/WAV/M4A 录音。")
    with tempfile.TemporaryDirectory(prefix="animation-probe-") as directory:
        path = Path(directory) / ("audio" + extension)
        path.write_bytes(content)
        info = probe(path)
    streams = info.get("streams", [])
    formats = set(info.get("format", {}).get("format_name", "").split(","))
    expected = {".mp3": "mp3", ".wav": "wav", ".m4a": "mov"}[extension]
    if expected not in formats or not streams or any(s.get("codec_type") != "audio" for s in streams):
        raise ValidationError("文件不是受支持的纯音频格式。")
    try:
        duration = float(info["format"]["duration"])
    except (KeyError, ValueError, TypeError):
        raise ValidationError("无法确定录音时长。") from None
    if not math.isfinite(duration) or not (0.05 if allow_short else 5) <= duration <= 120:
        raise ValidationError("录音时长须在 5–120 秒之间，不会自动截断录音。")
    return content, {"mime_type": {".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4"}[extension], "duration": duration}
