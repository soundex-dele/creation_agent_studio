"""Local OpenAI Whisper checkpoints, compatible with creation_master's cache."""

from core.observability import log_operation
import os
import threading
from functools import lru_cache
from pathlib import Path


_model_lock = threading.Lock()


def model_path():
    root = Path(os.environ.get("DOUYIN_WHISPER_ROOT", "~/.cache/whisper")).expanduser()
    name = os.environ.get("DOUYIN_WHISPER_MODEL", "base")
    path = Path(name).expanduser()
    if not path.is_absolute():
        path = root / (name if name.endswith(".pt") else f"{name}.pt")
    if not path.is_file():
        raise ValueError("未找到本地 Whisper 模型，请将 base.pt 放入 ~/.cache/whisper，"
                         "或配置 DOUYIN_WHISPER_ROOT / DOUYIN_WHISPER_MODEL。")
    return path.resolve()


@lru_cache(maxsize=1)
def _load_model(path):
    try:
        import whisper
    except ImportError:
        raise ValueError("转写依赖缺失，请在后端虚拟环境安装 openai-whisper。") from None
    # An existing checkpoint path bypasses Whisper's model downloader entirely.
    return whisper.load_model(str(path))


@log_operation
def transcribe_segments(path, language="zh", *, cancelled=lambda: False,
                        progress=lambda value: None, stage=lambda value: None):
    def check():
        if cancelled():
            raise InterruptedError("转录已取消。")

    check()
    checkpoint = model_path()
    stage("加载本地 Whisper 模型")
    # Serialize access to the cached model; decoder hooks are not thread-safe.
    while not _model_lock.acquire(timeout=.25):
        check()
    try:
        check()
        model = _load_model(checkpoint)
        check()
        import whisper

        stage("转写口播")
        audio = whisper.load_audio(str(path))
        check()
        progress(0)
        language = None if language == "auto" else (language or "zh").split("-", 1)[0]
        transcript = model.transcribe(
            audio, language=language, task="transcribe", verbose=None,
            fp16=model.device.type == "cuda",
            initial_prompt="以下是普通话的句子。" if language == "zh" else None,
        )
        check()
        segments, raw_text = [], []
        for segment in transcript["segments"]:
            check()
            text = segment["text"]
            raw_text.append(text)
            if text.strip():
                segments.append({"id": f"s{len(segments) + 1}",
                                 "start": float(segment["start"]), "end": float(segment["end"]),
                                 "text": text, "original_text": text})
        duration = len(audio) / whisper.audio.SAMPLE_RATE
        progress(duration)
        return {"segments": segments, "text": "".join(raw_text).strip(),
                "duration": duration, "language": transcript.get("language", language)}
    finally:
        _model_lock.release()
