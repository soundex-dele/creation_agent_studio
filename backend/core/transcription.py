"""Shared, lazy-loaded Whisper transcription with stable segment timestamps."""
import os
from functools import lru_cache


@lru_cache(maxsize=2)
def whisper_model(model_name):
    from faster_whisper import WhisperModel
    return WhisperModel(model_name, device="cpu", compute_type="int8")


def transcribe_segments(path, language="zh", *, cancelled=lambda: False, progress=lambda value: None):
    model = whisper_model(os.environ.get("CREATION_TOOLBOX_WHISPER_MODEL", "tiny"))
    language = None if language == "auto" else (language or "zh").split("-", 1)[0]
    segments, info = model.transcribe(str(path), language=language)
    result, raw_text = [], []
    for segment in segments:
        if cancelled():
            raise InterruptedError("转录已取消。")
        text = segment.text
        raw_text.append(text)
        if text.strip():
            result.append({"id": f"s{len(result) + 1}", "start": float(segment.start),
                           "end": float(segment.end), "text": text, "original_text": text})
        progress(float(segment.end))
    return {"segments": result, "text": "".join(raw_text).strip(), "duration": float(info.duration), "language": info.language}


def transcribe_audio(path, language):
    return transcribe_segments(path, language)["text"]
