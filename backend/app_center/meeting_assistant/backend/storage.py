"""Private audio storage; never use public MEDIA_URL for recordings."""
import os
from pathlib import Path
from django.conf import settings
from rest_framework.exceptions import ValidationError

MAX_BYTES = 200 * 1024 * 1024
MAX_SECONDS = 7200
EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}


def object_path(key):
    root = Path(getattr(settings, "MEETING_AUDIO_ROOT", os.environ.get(
        "MEETING_AUDIO_ROOT", str(Path(settings.MEDIA_ROOT).parent / "meeting-audio")))).resolve()
    path = (root / key).resolve()
    if path == root or root not in path.parents:
        raise ValueError("无效的音频位置。")
    return path


def probe_audio(path):
    import av
    try:
        with av.open(str(path)) as container:
            if not container.streams.audio:
                raise ValueError("missing audio")
            stream = container.streams.audio[0]
            duration = float(stream.duration * stream.time_base) if stream.duration else (
                float(container.duration / av.time_base) if container.duration else 0)
            if duration > MAX_SECONDS:
                raise ValidationError("录音不能超过两小时。")
            # Decode every frame using bounded memory: reject corrupt files and
            # containers with misleading duration metadata before scheduling.
            decoded = 0.0
            for frame in container.decode(stream):
                decoded += frame.samples / frame.sample_rate
                if decoded > MAX_SECONDS + 1:
                    raise ValidationError("录音不能超过两小时。")
            if decoded <= 0:
                raise ValueError("empty audio")
            return decoded
    except ValidationError:
        raise
    except Exception as exc:
        raise ValidationError("录音无法解码，请上传有效的音频文件。") from exc


def store_upload(upload, key):
    if Path(upload.name).suffix.lower() not in EXTENSIONS:
        raise ValidationError("支持 MP3、WAV、M4A、AAC、FLAC 和 OGG。")
    if upload.size <= 0 or upload.size > MAX_BYTES:
        raise ValidationError("录音大小须为 1 字节至 200 MiB。")
    path = object_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            size = 0
            for chunk in upload.chunks():
                size += len(chunk)
                if size > MAX_BYTES:
                    raise ValidationError("录音不能超过 200 MiB。")
                handle.write(chunk)
        return probe_audio(path)
    except Exception:
        path.unlink(missing_ok=True)
        raise
