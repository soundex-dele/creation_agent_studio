from __future__ import annotations

import os
from functools import lru_cache


@lru_cache(maxsize=2)
def _whisper_model(model_name: str):
    from faster_whisper import WhisperModel

    return WhisperModel(model_name, device="cpu", compute_type="int8")


def transcribe_audio(path: str, language: str) -> str:
    model_name = os.environ.get("CREATION_TOOLBOX_WHISPER_MODEL", "tiny")
    model = _whisper_model(model_name)
    normalized_language = (language or "zh").split("-", 1)[0]
    segments, _info = model.transcribe(path, language=normalized_language)
    return "".join(segment.text for segment in segments).strip()
